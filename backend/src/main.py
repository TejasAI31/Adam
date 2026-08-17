"""Main loop entry point for the Adam full-duplex speech engine."""
import os
import sys

# Crucial: Disable Hugging Face lazy loading so PyInstaller compiled imports resolve eagerly
os.environ["TRANSFORMERS_NO_LAZY_LOADING"] = "1"

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")
warnings.filterwarnings("ignore", category=UserWarning, module="torchcodec")

# Ensure working directory is set to executable directory for PyInstaller compiled executable
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

import src.utils.dll_setup

# Explicit eager imports of lazy-loaded transformers/pyannote submodules to ensure PyInstaller bundles them
try:
    import transformers.pipelines
    import transformers.models.auto
    import transformers.models.auto.processing_auto
    from transformers import pipeline, AutoProcessor
except ImportError:
    pass

try:
    import pyannote.pipeline
    import pyannote.audio.core.pipeline
    from pyannote.audio import Pipeline as PyannotePipeline
except ImportError:
    pass

import logging
import os
import select
import sys
import threading
import warnings
import pyaudio
import webrtcvad

from config.settings import audio_cfg, model_cfg
from src.audio.device import SHARED_AUDIO
from src.audio.dsp import preprocess_audio
from src.stt.whisperx_engine import load_stt_engine
from src.llm.llama_engine import load_llm_engine
from src.tts.qwen_tts import load_tts_engine, warmup_and_generate_chime
from src.orchestration.duplex_manager import FullDuplexManager
from src.llm.tools.math_tools import MATH_TOOLS_MAP, MATH_TOOL_SCHEMAS
from src.llm.tools.websearch_tool import WEBSEARCH_TOOL_MAP, WEBSEARCH_TOOL_SCHEMAS
from src.llm.tools.ytmusic_tools import YTMUSIC_TOOL_MAP, YTMUSIC_TOOL_SCHEMAS
from src.llm.tools.url_opener_tool import BROWSER_TOOL_MAP, BROWSER_TOOL_SCHEMAS
from src.llm.tools.system_tools import SYSTEM_TOOLS_MAP, SYSTEM_TOOLS_SCHEMAS

from src.utils.text_cleaner import TTSTextCleaner

# Register all tool schemas including newly added image tools
tools = (
    MATH_TOOL_SCHEMAS
    + WEBSEARCH_TOOL_SCHEMAS
    + YTMUSIC_TOOL_SCHEMAS
    + BROWSER_TOOL_SCHEMAS
    + SYSTEM_TOOLS_SCHEMAS
)

tool_maps = {
    **MATH_TOOLS_MAP,
    **WEBSEARCH_TOOL_MAP,
    **YTMUSIC_TOOL_MAP,
    **BROWSER_TOOL_MAP,
    **SYSTEM_TOOLS_MAP,
}

# Silence warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
logging.getLogger("pyannote").setLevel(logging.ERROR)
logging.getLogger("speechbrain").setLevel(logging.ERROR)
logging.getLogger("onnxruntime").setLevel(logging.ERROR)
logging.getLogger("whisperx").setLevel(logging.ERROR)
logging.getLogger("whisperx.vads.pyannote").setLevel(logging.ERROR)

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"


def check_text_input():
    """Non-blocking check for user console text input (Linux/macOS)."""
    if sys.platform != "win32":
        if select.select([sys.stdin], [], [], 0.0)[0]:
            return sys.stdin.readline().strip()
    return None


def run_full_duplex_loop():
    # 1. Instantiate Core Models
    llm = load_llm_engine()
    stt_model = load_stt_engine()
    tts_model = load_tts_engine()

    # 2. Warmup & System Initialization
    warmup_and_generate_chime(tts_model, llm)
    manager = FullDuplexManager(llm_model=llm, tts_model=tts_model)
    vad = webrtcvad.Vad(audio_cfg.vad_aggressiveness)

    default_input_index = SHARED_AUDIO.get_default_input_device_info()["index"]

    stream = SHARED_AUDIO.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=audio_cfg.sample_rate,
        input=True,
        input_device_index=default_input_index,  # Explicit device assignment
        frames_per_buffer=audio_cfg.frame_size,
)

    triggered = False
    voiced_frames, ring_buffer = [], []

    # Queue for asynchronous text input (Windows compatibility)
    text_input_queue = []

    if sys.platform == "win32":
        def input_listener():
            while True:
                try:
                    user_text = input()
                    if user_text and user_text.strip():
                        text_input_queue.append(user_text.strip())
                except (EOFError, KeyboardInterrupt):
                    break

        threading.Thread(target=input_listener, daemon=True).start()

    print("\n[SYSTEM ACTIVE] Adam is online. Say 'Adam' or speak directly to interact.")
    print("[TEXT CHAT ENABLED] You can also type commands into the terminal.")
    print("Type '/quiet <text>' or '/mute <text>' to bypass speech output.\n")

    try:
        while True:
            # Check for terminal text inputs
            text_prompt = None
            if sys.platform == "win32":
                if text_input_queue:
                    text_prompt = text_input_queue.pop(0)
            else:
                text_prompt = check_text_input()

            if text_prompt:
                bypass_speech = False
                cleaned_text = text_prompt.strip()

                if cleaned_text.startswith(("/quiet ", "/mute ")):
                    bypass_speech = True
                    cleaned_text = cleaned_text.split(" ", 1)[1].strip()

                if cleaned_text:
                    if manager.is_speaking:
                        manager.interrupt()

                    print(f"\nUser (Text): {cleaned_text}")

                    if bypass_speech:
                        def run_quiet_pipeline(prompt):
                            if hasattr(manager, "process_text_only"):
                                manager.process_text_only(prompt)
                            elif hasattr(manager, "process_pipeline"):
                                try:
                                    manager.process_pipeline(
                                        prompt,
                                        speech_enabled=False,
                                        tools=tools,
                                        available_functions=tool_maps,
                                    )
                                except TypeError:
                                    if hasattr(llm, "create_chat_completion"):
                                        res = llm.create_chat_completion(
                                            messages=[{"role": "user", "content": prompt}],
                                            max_tokens=model_cfg.max_output_tokens,
                                        )
                                        response_text = res["choices"][0]["message"]["content"].strip()
                                    else:
                                        res = llm(prompt, max_tokens=model_cfg.max_output_tokens)
                                        response_text = res["choices"][0]["text"].strip()
                                        
                                    clean_response = TTSTextCleaner.clean_for_tts(response_text)
                                    print(f"\nAdam (Quiet): {clean_response}")
                            else:
                                res = llm(prompt, max_tokens=model_cfg.max_output_tokens)
                                response_text = res["choices"][0]["text"].strip()
                                clean_response = TTSTextCleaner.clean_for_tts(response_text)
                                print(f"\nAdam (Quiet): {clean_response}")

                        pipeline_thread = threading.Thread(
                            target=run_quiet_pipeline,
                            args=(cleaned_text,),
                            daemon=True,
                        )
                    else:
                        pipeline_thread = threading.Thread(
                            target=manager.process_pipeline,
                            args=(cleaned_text,),
                            kwargs={
                                "tools": tools,
                                "available_functions": tool_maps,
                            },
                            daemon=True,
                        )
                    pipeline_thread.start()

            # --- ORIGINAL STT & VAD PIPELINE (UNTOUCHED) ---
            frame = stream.read(audio_cfg.frame_size, exception_on_overflow=False)
            if not frame:
                continue

            is_speech = vad.is_speech(frame, audio_cfg.sample_rate)

            if not triggered:
                ring_buffer.append((frame, is_speech))
                if len(ring_buffer) > audio_cfg.padding_frames:
                    ring_buffer.pop(0)

                num_voiced = sum(1 for _, speech in ring_buffer if speech)
                if num_voiced > 0.8 * len(ring_buffer):
                    triggered = True
                    voiced_frames.extend([f for f, _ in ring_buffer])
                    ring_buffer.clear()
            else:
                voiced_frames.append(frame)
                ring_buffer.append((frame, is_speech))
                if len(ring_buffer) > audio_cfg.padding_frames:
                    ring_buffer.pop(0)

                num_unvoiced = sum(1 for _, speech in ring_buffer if not speech)
                current_duration = (
                    len(voiced_frames) * audio_cfg.frame_duration_ms
                ) / 1000.0

                if (
                    num_unvoiced > 0.8 * len(ring_buffer)
                    or current_duration >= audio_cfg.max_speech_duration
                ):
                    if current_duration >= audio_cfg.min_speech_duration:
                        raw_chunk = b"".join(voiced_frames)
                        clean_audio_array = preprocess_audio(raw_chunk)

                        result = stt_model.transcribe(
                            clean_audio_array,
                            batch_size=model_cfg.stt_batch_size,
                        )
                        segments = result.get("segments", [])
                        transcription = " ".join(
                            [s.get("text", "").strip() for s in segments]
                        ).strip()

                        if transcription and "adam" in transcription.lower():
                            if manager.is_speaking:
                                manager.interrupt()

                            print(f"\nUser: {transcription}")
                            pipeline_thread = threading.Thread(
                                target=manager.process_pipeline,
                                args=(transcription,),
                                kwargs={
                                    "tools": tools,
                                    "available_functions": tool_maps,
                                },
                                daemon=True,
                            )
                            pipeline_thread.start()

                    triggered = False
                    ring_buffer.clear()
                    voiced_frames.clear()

    except KeyboardInterrupt:
        print("\n[INFO] Shutting down full duplex system...")
    finally:
        manager.stop_requested.set()
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass


if __name__ == "__main__":
    run_full_duplex_loop()