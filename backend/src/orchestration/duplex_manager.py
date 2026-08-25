"""Manager for tracking async TTS generation, PyAudio stream playback, user interrupts,
and tool-driven visual screen interaction with adaptive context memory optimization.
"""

import base64
import copy
import json
import os
import queue
import re
import threading
import time
import warnings
import numpy as np
import pyaudio
import soundfile as sf

from config.settings import CHIME_PATH, model_cfg
from src.audio.device import SHARED_AUDIO
from src.llm.prompts import BUTLER_INSTRUCTION, SYSTEM_PROMPT
from src.utils.text_cleaner import TTSTextCleaner

warnings.filterwarnings("ignore")


class FullDuplexManager:

    def __init__(self, llm_model, tts_model):
        self.llm = llm_model
        self.tts = tts_model
        self.on_playback_status = None

        self.text_queue = queue.Queue()
        self.audio_queue = queue.Queue()

        self.is_speaking = False
        self.interrupt_event = threading.Event()
        self.stop_requested = threading.Event()

        self.current_request_id = 0
        self.history = []
        self.history_lock = threading.Lock()

        # --- MEMORY OPTIMIZATION CONFIGURATION ---
        self.max_history_turns = getattr(model_cfg, "max_history_len", 6) * 2
        self.max_tool_output_len = getattr(model_cfg, "max_tool_output_len", 1500)
        self.max_estimated_tokens = getattr(model_cfg, "max_estimated_tokens", 20000)

        self.gen_thread = threading.Thread(
            target=self._tts_generation_worker, daemon=True
        )
        self.play_thread = threading.Thread(
            target=self._audio_playback_worker, daemon=True
        )
        self.gen_thread.start()
        self.play_thread.start()

    @staticmethod
    def _format_image_uri(image_input: str) -> str:
        """Converts file path, raw base64 string, or URI into a standard base64 data URI."""
        if not image_input:
            return None

        if image_input.startswith("data:image/"):
            return image_input

        if os.path.isfile(image_input):
            ext = os.path.splitext(image_input)[1].lower().replace(".", "")
            mime_type = (
                f"image/{ext}"
                if ext in ["png", "jpg", "jpeg", "webp"]
                else "image/png"
            )
            with open(image_input, "rb") as img_file:
                b64_data = base64.b64encode(img_file.read()).decode("utf-8")
            return f"data:{mime_type};base64,{b64_data}"

        return f"data:image/png;base64,{image_input}"

    def _extract_image_paths(self, tool_output: str) -> list:
        """Generalized utility to detect image file paths returned by any tool output."""
        if not isinstance(tool_output, str):
            return []

        # Matches paths ending in common image extensions
        pattern = r"([a-zA-Z]:\\[^:\n\r\"]+\.(?:png|jpg|jpeg|webp)|/[^:\n\r\"]+\.(?:png|jpg|jpeg|webp))"
        matches = re.findall(pattern, tool_output, re.IGNORECASE)
        valid_paths = [p for p in matches if os.path.exists(p)]

        # Fallback check if the string itself is a direct path
        if not valid_paths and os.path.exists(tool_output.strip()):
            ext = os.path.splitext(tool_output.strip())[1].lower()
            if ext in [".png", ".jpg", ".jpeg", ".webp"]:
                valid_paths.append(tool_output.strip())

        return valid_paths

    def _estimate_tokens(self, messages: list) -> int:
        """Heuristic token estimation (~4 chars per token) to monitor context budget."""
        char_count = 0
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                char_count += len(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        char_count += len(item.get("text", ""))
                    elif isinstance(item, dict) and item.get("type") == "image_url":
                        char_count += 1000  # Virtual overhead for images

            if "tool_calls" in msg and msg["tool_calls"]:
                char_count += len(json.dumps(msg["tool_calls"]))
        return char_count // 4

    def _prune_and_compress_history(self):
        """Memory Optimization Engine:
        1. Strips heavy base64 image strings from all messages.
        2. Applies sliding window turn limits.
        3. Aggressively prunes tool output history if context limit is exceeded.
        """
        with self.history_lock:
            if not self.history:
                return

            # Strip all inline Base64 images to prevent memory bloat
            for msg in self.history:
                content = msg.get("content")
                if isinstance(content, list):
                    new_content = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "image_url":
                            new_content.append(
                                {
                                    "type": "text",
                                    "text": "[Previous frame image removed to conserve memory]",
                                }
                            )
                        else:
                            new_content.append(item)
                    msg["content"] = new_content
                elif isinstance(content, str):
                    if "data:image/" in content:
                        msg["content"] = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "[Image Data Removed]", content)

            # Apply strict rolling window max_turns limit while keeping tool-call pairs atomic
            if len(self.history) > self.max_history_turns:
                start_idx = len(self.history) - self.max_history_turns
                while start_idx > 0 and self.history[start_idx].get("role") == "tool":
                    start_idx -= 1
                self.history = self.history[start_idx:]

            # Adaptive token check & Emergency Fixing Measures
            est_tokens = self._estimate_tokens(self.history)
            if est_tokens > self.max_estimated_tokens:
                # Compression Pass 1: Compact tool outputs in history
                for msg in self.history:
                    if msg.get("role") == "tool" and isinstance(
                        msg.get("content"), str
                    ):
                        if len(msg["content"]) > 300:
                            msg["content"] = (
                                msg["content"][:300]
                                + "\n...[Content truncated for context safety]"
                            )

                # Compression Pass 2: If still overflowing, drop oldest turns until compliant
                while (
                    len(self.history) > 2
                    and self._estimate_tokens(self.history) > self.max_estimated_tokens
                ):
                    self.history.pop(0)

    def add_to_history(self, user_text, assistant_text):
        with self.history_lock:
            if user_text:
                self.history.append({"role": "user", "content": user_text})
            if assistant_text:
                self.history.append(
                    {"role": "assistant", "content": assistant_text}
                )
        self._prune_and_compress_history()

    def interrupt(self):
        """Purge ongoing processing queues immediately on interruption."""
        self.interrupt_event.set()
        self.is_speaking = False
        self.current_request_id += 1
        if self.on_playback_status:
            try:
                self.on_playback_status(False)
            except Exception:
                pass

        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
                self.text_queue.task_done()
            except queue.Empty:
                break

        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
                self.audio_queue.task_done()
            except queue.Empty:
                break

    def _tts_generation_worker(self):
        """Worker 1: Consumes text sentences and generates raw audio buffers in parallel."""
        while not self.stop_requested.is_set():
            try:
                item = self.text_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            if item is None:
                self.text_queue.task_done()
                continue

            raw_text, idx, req_id = item
            text_to_speak = TTSTextCleaner.clean_for_tts(raw_text)

            if (
                req_id != self.current_request_id
                or self.interrupt_event.is_set()
            ):
                self.text_queue.task_done()
                continue

            if text_to_speak and self.tts is not None:
                try:
                    from config.settings import model_cfg
                    speaker = getattr(model_cfg, "tts_speaker", "Aiden")
                    
                    language = "English"
                    if speaker in ["Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric"]:
                        language = "Chinese"
                    elif speaker == "Ono_Anna":
                        language = "Japanese"
                    elif speaker == "Sohee":
                        language = "Korean"

                    wavs, sr = self.tts.generate_custom_voice(
                        text=text_to_speak,
                        language=language,
                        speaker=speaker,
                        instruct=BUTLER_INSTRUCTION,
                    )

                    if (
                        req_id == self.current_request_id
                        and not self.interrupt_event.is_set()
                    ):
                        audio_data = wavs[0]
                        self.audio_queue.put((audio_data, sr, idx, req_id))
                except Exception as e:
                    print(f"\n[TTS Error]: {e}")

            self.text_queue.task_done()

    def _audio_playback_worker(self):
        """Worker 2: Plays generated audio chunks concurrently as soon as TTS yields them."""
        stream = None
        stream_rate = None

        while not self.stop_requested.is_set():
            try:
                item = self.audio_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            if item is None:
                self.audio_queue.task_done()
                continue

            audio_data, sr, idx, req_id = item

            if (
                req_id != self.current_request_id
                or self.interrupt_event.is_set()
            ):
                self.audio_queue.task_done()
                continue

            try:
                if self.on_playback_status:
                    try:
                        self.on_playback_status(True)
                    except Exception:
                        pass

                if stream is not None and stream_rate != sr:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                    stream = None

                if stream is None:
                    stream = SHARED_AUDIO.open(
                        format=pyaudio.paFloat32,
                        channels=1,
                        rate=sr,
                        output=True,
                    )
                    stream_rate = sr

                if isinstance(audio_data, np.ndarray):
                    raw_bytes = audio_data.astype(np.float32).tobytes()
                else:
                    raw_bytes = audio_data

                chunk_size = 4096
                for i in range(0, len(raw_bytes), chunk_size):
                    if (
                        self.interrupt_event.is_set()
                        or req_id != self.current_request_id
                    ):
                        break
                    stream.write(raw_bytes[i : i + chunk_size])

            except Exception as e:
                print(f"\n[Playback Error]: {e}")
            finally:
                self.audio_queue.task_done()
                if self.audio_queue.empty() and self.on_playback_status:
                    try:
                        self.on_playback_status(False)
                    except Exception:
                        pass

        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass

    def _extract_text_from_pdf_data(self, base64_data: str) -> str:
        import io
        import base64
        from pypdf import PdfReader
        
        # Strip data URI header if present
        if "," in base64_data:
            base64_data = base64_data.split(",")[1]
            
        pdf_bytes = base64.b64decode(base64_data)
        pdf_file = io.BytesIO(pdf_bytes)
        
        reader = PdfReader(pdf_file)
        text_content = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_content.append(text)
        return "\n".join(text_content).strip()

    def _clean_history_images_and_files(self):
        with self.history_lock:
            for msg in self.history:
                content = msg.get("content")
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                text_parts.append(item.get("text", ""))
                            elif item.get("type") == "image_url":
                                text_parts.append("[Image]")
                        else:
                            text_parts.append(str(item))
                    msg["content"] = "\n".join(text_parts).strip()
                elif isinstance(content, str):
                    if "data:image/" in content:
                        msg["content"] = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "[Image Data Removed]", content)

    def process_pipeline(
        self,
        prompt,
        image_input=None,
        attachments=None,
        tools=None,
        available_functions=None,
        speech_enabled=True,
        callback=None,
    ):
        """Pipeline Producer: Handles multi-turn streaming with vision support,
        dynamic tool call dispatching, and generalized vision injection.
        """
        if not prompt or not prompt.strip():
            if attachments or image_input:
                prompt = "Please analyze the uploaded files."
            else:
                return

        self.interrupt_event.clear()
        self.search_count_in_turn = 0
        self.is_speaking = True
        self.current_request_id += 1
        req_id = self.current_request_id

        # Detect disabled tools to dynamically instruct the LLM
        disabled_tools = []
        all_standard_tools = [
            "evaluate_expression", "solve_quadratic", "calculate_statistics",
            "web_search", "ytm_search_and_get", "ytm_get_browse_context",
            "open_browser_urls", "take_screenshot", "scan_screen_elements",
            "click_element_by_name"
        ]
        if available_functions is not None:
            for t in all_standard_tools:
                if t not in available_functions:
                    disabled_tools.append(t)
        else:
            disabled_tools = all_standard_tools

        self.disabled_tools_instruction = ""
        if disabled_tools:
            self.disabled_tools_instruction = (
                "\n\nDISABLED TOOLS NOTICE:\n"
                "The following tools are explicitly DISABLED by the user: " + ", ".join(disabled_tools) + ".\n"
                "If the user asks you to perform a task that requires one of these disabled tools, "
                "you MUST NOT attempt to use other tools as workarounds (for example, if 'web_search' is disabled, "
                "you are forbidden from using 'open_browser_urls' or 'ytm_search_and_get' to search or browse). "
                "Instead, you must immediately halt, state clearly to the user that the tool is disabled, "
                "explain what you cannot do, and ask the user for confirmation/permission before performing "
                "any alternative actions (e.g. asking: 'I do not have access to web search. Would you like me to open the browser for you?')."
            )


        clean_prompt = re.sub(r"[^\w\s]", "", prompt.lower()).strip()

        # Command shortcuts
        greetings = {
            "hey adam",
            "hi adam",
            "hello adam",
            "adam",
            "yo adam",
            "hi",
            "hello",
        }
        if clean_prompt in greetings:
            greeting_resp = "At your service. What can I do for you?"
            print(f"\nAdam: {greeting_resp}")
            if callback:
                callback("text", greeting_resp)
            if speech_enabled:
                self.text_queue.put((greeting_resp, 0, req_id))
            self.add_to_history(prompt, greeting_resp)
            self.is_speaking = False
            return

        stop_phrases = {
            "stop",
            "stop speaking",
            "shut up",
            "adam stop",
            "be quiet",
            "cancel",
        }
        if clean_prompt in stop_phrases:
            stop_resp = "Very well."
            print(f"\nAdam: {stop_resp}")
            if callback:
                callback("text", stop_resp)
            if speech_enabled:
                self.text_queue.put((stop_resp, 0, req_id))
            self.is_speaking = False
            return

        # Handle multiple file attachments (images + PDFs)
        if attachments is None:
            attachments = []

        if image_input:
            # For backward compatibility, wrap single image_input as an attachment if not already present
            has_single_image = False
            for att in attachments:
                if att.get("data") == image_input:
                    has_single_image = True
                    break
            if not has_single_image:
                attachments.append({
                    "name": "image.png",
                    "type": "image",
                    "data": image_input
                })

        image_uris = []
        pdf_texts = []
        history_files = []

        for att in attachments:
            att_name = att.get("name", "file")
            att_type = att.get("type", "")
            att_data = att.get("data", "")

            if not att_data:
                continue

            if att_type == "image" or att_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                image_uri = self._format_image_uri(att_data)
                if image_uri:
                    image_uris.append(image_uri)
                    history_files.append(f"[Uploaded Image: {att_name}]")
            elif att_type == "pdf" or att_name.lower().endswith(".pdf"):
                try:
                    pdf_text = self._extract_text_from_pdf_data(att_data)
                    if pdf_text:
                        # Truncate extremely large PDFs to prevent context window explosion and prefill lags
                        max_pdf_chars = 40000
                        if len(pdf_text) > max_pdf_chars:
                            pdf_text = pdf_text[:max_pdf_chars] + "\n...[Content truncated to conserve context size]"
                        pdf_texts.append(f"--- START OF FILE: {att_name} ---\n{pdf_text}\n--- END OF FILE: {att_name} ---")
                    else:
                        pdf_texts.append(f"--- START OF FILE: {att_name} ---\n[No extractable text found in this PDF]\n--- END OF FILE: {att_name} ---")
                except Exception as pdf_err:
                    pdf_texts.append(f"--- START OF FILE: {att_name} ---\n[Error reading PDF: {pdf_err}]\n--- END OF FILE: {att_name} ---")
                history_files.append(f"[Uploaded PDF: {att_name}]")

        # Prepare content for current LLM call (this includes full image urls and PDF texts)
        llm_prompt_text = prompt
        if pdf_texts:
            llm_prompt_text = (
                "You have been provided with the text content of the uploaded PDF file(s). "
                "Read and analyze the document context below carefully, then answer the user's prompt based on it.\n\n"
                + "\n\n".join(pdf_texts) + "\n\n"
                + "User Prompt: " + prompt
            )

        if image_uris:
            user_content = [{"type": "text", "text": llm_prompt_text}]
            for img_uri in image_uris:
                user_content.append({"type": "image_url", "image_url": {"url": img_uri}})
        else:
            user_content = llm_prompt_text

        # For rolling history, only store the filenames and original prompt text
        history_prefix = ""
        if history_files:
            history_prefix = " ".join(history_files) + "\n\n"

        history_user_content = f"{history_prefix}{prompt}".strip()

        with self.history_lock:
            self.history.append({"role": "user", "content": history_user_content})

        # Run memory compression before generating response
        self._prune_and_compress_history()

        sentence_delimiters = re.compile(r"(?:(?<=[.!?])\s+|[;:]\s*|\n+)")
        chunk_idx = 0

        max_tool_rounds = 20
        current_round = 0

        try:
            while (
                current_round < max_tool_rounds
                and not self.interrupt_event.is_set()
            ):
                current_round += 1
                buffer = ""
                full_response = ""
                tool_calls_accumulator = {}
                is_tool_round = False
                round_text_buffer = ""
                round_text_sent = False

                with self.history_lock:
                    messages = [{"role": "system", "content": SYSTEM_PROMPT + self.disabled_tools_instruction}] + list(
                        self.history
                    )

                # Find the latest user message in the current turn's history and temporarily replace it
                # with the full user_content (containing base64 images/PDF texts) for the LLM call.
                for idx in reversed(range(len(messages))):
                    if messages[idx]["role"] == "user":
                        last_msg = copy.copy(messages[idx])
                        last_msg["content"] = user_content
                        messages[idx] = last_msg
                        break

                cleaned_messages = self._clean_messages_for_template(messages)

                response_stream = self.llm.create_chat_completion(
                    messages=cleaned_messages,
                    stream=True,
                    max_tokens=model_cfg.max_output_tokens,
                    tools=tools,
                )

                if current_round == 1:
                    print("\nAdam Output: ", end="", flush=True)

                for chunk in response_stream:
                    if (
                        self.interrupt_event.is_set()
                        or req_id != self.current_request_id
                    ):
                        break

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})

                    if "tool_calls" in delta and delta["tool_calls"]:
                        is_tool_round = True
                        for t_call in delta["tool_calls"]:
                            t_index = t_call.get("index", 0)
                            if t_index not in tool_calls_accumulator:
                                tool_calls_accumulator[t_index] = {
                                    "id": t_call.get(
                                        "id", f"call_{t_index}_{time.time()}"
                                    ),
                                    "type": t_call.get("type", "function"),
                                    "function": {"name": "", "arguments": ""},
                                }

                            # Ensure call ID is maintained if present in chunk
                            if t_call.get("id"):
                                tool_calls_accumulator[t_index]["id"] = t_call["id"]

                            func_delta = t_call.get("function", {})
                            if func_delta.get("name"):
                                tool_calls_accumulator[t_index]["function"]["name"] += func_delta["name"]
                            if func_delta.get("arguments"):
                                tool_calls_accumulator[t_index]["function"]["arguments"] += func_delta["arguments"]
                        continue

                    content = delta.get("content", "")
                    if content:
                        print(content, end="", flush=True)
                        full_response += content
                        if not is_tool_round:
                            if current_round > 1:
                                if not round_text_sent:
                                    round_text_buffer += content
                                    if len(round_text_buffer) >= 40 or any(c in round_text_buffer for c in [".", "!", "?", "\n"]):
                                        cleaned_buf = re.sub(
                                            r"^\s*(right away|certainly|at once|sure|okay|of course|let me check|let me verify|let me search)\b[\.\!\?\s]*",
                                            "",
                                            round_text_buffer,
                                            flags=re.IGNORECASE
                                        )
                                        round_text_sent = True
                                        if cleaned_buf and callback:
                                            callback("text", cleaned_buf)
                                else:
                                    if callback:
                                        callback("text", content)
                            else:
                                if callback:
                                    callback("text", content)

                # Flush remaining buffer if not sent
                if current_round > 1 and not round_text_sent and round_text_buffer and not is_tool_round:
                    cleaned_buf = re.sub(
                        r"^\s*(right away|certainly|at once|sure|okay|of course|let me check|let me verify|let me search)\b[\.\!\?\s]*",
                        "",
                        round_text_buffer,
                        flags=re.IGNORECASE
                    )
                    if cleaned_buf and callback:
                        callback("text", cleaned_buf)

                # --- TOOL EXECUTION & DISPATCHING ---
                if tool_calls_accumulator and not self.interrupt_event.is_set():
                    print("\n[Executing Tool Calls...]")
                    formatted_tool_calls = list(tool_calls_accumulator.values())
                    tool_results = []
                    visual_payloads = []

                    for t_data in formatted_tool_calls:
                        func_name = t_data["function"]["name"]
                        raw_args = t_data["function"]["arguments"]

                        try:
                            func_args = json.loads(raw_args) if raw_args.strip() else {}
                        except json.JSONDecodeError as parse_err:
                            print(f"\n[Tool Args Error]: Failed to parse arguments '{raw_args}': {parse_err}")
                            func_args = {}

                        print(f" -> Invoking Tool: {func_name}({func_args})")
                        if callback:
                            callback("tool_start", {"name": func_name, "arguments": func_args})

                        # Check if tool is disabled/deselected in tools tab
                        known_tools = {
                            "evaluate_expression",
                            "solve_quadratic",
                            "calculate_statistics",
                            "web_search",
                            "ytm_search_and_get",
                            "ytm_get_browse_context",
                            "open_browser_urls",
                            "take_screenshot",
                            "scan_screen_elements",
                            "click_element_by_name"
                        }
                        if func_name in known_tools and (available_functions is None or func_name not in available_functions):
                            access_denied_msg = "I do not have access to the needed tools."
                            if callback:
                                callback("tool_end", {"name": func_name, "output": access_denied_msg})
                                callback("text", access_denied_msg)
                            if speech_enabled:
                                self.text_queue.put((access_denied_msg, 0, req_id))
                            with self.history_lock:
                                self.history.append(
                                    {"role": "assistant", "content": access_denied_msg}
                                )
                            return

                        # Direct execution through provided environment functions
                        if available_functions and func_name in available_functions:
                            try:
                                if func_name == "web_search":
                                    self.search_count_in_turn += 1
                                    if self.search_count_in_turn > 2:
                                        print(" -> Search limit reached! Bypassing execution.")
                                        tool_output = "Search limit reached for this turn. Please synthesize the final response from the already retrieved search results."
                                    else:
                                        tool_output = available_functions[func_name](**func_args)
                                else:
                                    tool_output = available_functions[func_name](**func_args)
                            except Exception as exec_err:
                                tool_output = f"Error executing {func_name}: {exec_err}"
                        else:
                            tool_output = f"Error: Function '{func_name}' is not registered in available_functions."

                        # Inject textual screen element layout when take_screenshot is called
                        # so that text-only models (like Qwen3.5) can read the screen content textually.
                        if func_name == "take_screenshot" and available_functions and "scan_screen_elements" in available_functions:
                            try:
                                layout = available_functions["scan_screen_elements"]()
                                tool_output = f"{tool_output}\n\nVisible Screen Accessibility Tree Layout:\n{layout}"
                            except Exception as scan_err:
                                print(f"[Warning] Failed to scan screen elements: {scan_err}")

                        if callback:
                            callback("tool_end", {"name": func_name, "output": str(tool_output)})

                        # --- GENERALIZED VISION PIPELINE ---
                        extracted_images = self._extract_image_paths(str(tool_output))
                        for img_path in extracted_images:
                            b64_uri = self._format_image_uri(img_path)
                            if b64_uri:
                                visual_payloads.append(
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": b64_uri},
                                    }
                                )

                        # Memory Optimization: Truncate oversized raw tool output strings before adding to context
                        str_output = str(tool_output)
                        if len(str_output) > self.max_tool_output_len:
                            str_output = (
                                str_output[: self.max_tool_output_len]
                                + f"\n...[Output truncated to {self.max_tool_output_len} chars]"
                            )

                        tool_results.append(
                            {
                                "tool_call_id": t_data["id"],
                                "role": "tool",
                                "name": func_name,
                                "content": str_output,
                            }
                        )

                    # Strip thinking tags from intermediate responses
                    clean_int_response = full_response
                    if clean_int_response:
                        clean_int_response = re.sub(r"<think>.*?</think>", "", clean_int_response, flags=re.DOTALL).strip()
                        if not clean_int_response:
                            clean_int_response = full_response.strip()
                        if current_round > 1:
                            clean_int_response = re.sub(
                                r"^\s*(right away|certainly|at once|sure|okay|of course|let me check|let me verify|let me search)\b[\.\!\?\s]*",
                                "",
                                clean_int_response,
                                flags=re.IGNORECASE
                            ).strip()

                    # Update history with tool calls and outputs
                    with self.history_lock:
                        self.history.append(
                            {
                                "role": "assistant",
                                "content": clean_int_response if clean_int_response else None,
                                "tool_calls": formatted_tool_calls,
                            }
                        )
                        self.history.extend(tool_results)

                        # Inject visual context or dummy user message to satisfy template parsers
                        if visual_payloads:
                            content_block = [
                                {
                                    "type": "text",
                                    "text": "Visual frame captured from action execution:",
                                }
                            ] + visual_payloads
                            self.history.append(
                                {
                                    "role": "user",
                                    "content": content_block,
                                }
                            )
                        else:
                            self.history.append(
                                {
                                    "role": "user",
                                    "content": "Tool outputs provided above. Please process and continue.",
                                }
                            )

                    # Run inline history compression after tool updates
                    self._prune_and_compress_history()

                    # Re-enter while loop to get the LLM's summary response based on the new tool results
                    continue

                # Strip thinking tags from final responses
                clean_final_response = full_response
                if clean_final_response:
                    clean_final_response = re.sub(r"<think>.*?</think>", "", clean_final_response, flags=re.DOTALL).strip()
                    if not clean_final_response:
                        clean_final_response = full_response.strip()
                    if current_round > 1:
                        clean_final_response = re.sub(
                            r"^\s*(right away|certainly|at once|sure|okay|of course|let me check|let me verify|let me search)\b[\.\!\?\s]*",
                            "",
                            clean_final_response,
                            flags=re.IGNORECASE
                        ).strip()

                if (
                    clean_final_response
                    and not self.interrupt_event.is_set()
                    and req_id == self.current_request_id
                ):
                    if speech_enabled:
                        sentences = sentence_delimiters.split(clean_final_response)
                        for s in sentences:
                            complete_sentence = s.strip()
                            if complete_sentence:
                                self.text_queue.put(
                                    (complete_sentence, chunk_idx, req_id)
                                )
                                chunk_idx += 1
                    with self.history_lock:
                        self.history.append(
                            {"role": "assistant", "content": clean_final_response}
                        )

                # Final memory check at turn end
                self._prune_and_compress_history()
                self._clean_history_images_and_files()
                break

        except Exception as e:
            print(f"\n[LLM Pipeline Error]: {e}")
        finally:
            self.is_speaking = False

    def _clean_messages_for_template(self, messages):
        cleaned = []
        valid_tool_ids = set()
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            tool_calls = msg.get("tool_calls")
            
            # Format None content
            if content is None:
                content = ""
                
            # Skip empty user messages
            if role == "user":
                if isinstance(content, str) and not content.strip():
                    continue
                elif not content:
                    continue
            
            # Skip empty assistant messages with no tool calls
            if role == "assistant":
                if not tool_calls:
                    if isinstance(content, str) and not content.strip():
                        continue
                    elif not content:
                        continue
                else:
                    for tc in tool_calls:
                        if isinstance(tc, dict) and tc.get("id"):
                            valid_tool_ids.add(tc["id"])
            
            # If a tool message is orphaned (preceding assistant tool_calls sliced out), convert it to user context
            if role == "tool":
                tid = msg.get("tool_call_id")
                if not tid or tid not in valid_tool_ids:
                    tool_name = msg.get("name", "tool")
                    cleaned.append({
                        "role": "user",
                        "content": f"[Previous Tool Result for {tool_name}]: {content}"
                    })
                    continue
                        
            clean_msg = {"role": role, "content": content}
            if tool_calls:
                clean_msg["tool_calls"] = tool_calls
            if "tool_call_id" in msg:
                clean_msg["tool_call_id"] = msg["tool_call_id"]
            if "name" in msg:
                clean_msg["name"] = msg["name"]
            cleaned.append(clean_msg)
        return cleaned