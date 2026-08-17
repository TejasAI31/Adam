"""Llama-cpp Engine loading wrapper using llama-server (OpenAI API spec)."""

import json
import urllib.request
import urllib.error
from config.settings import model_cfg


class LlamaServerClient:
    """Lightweight HTTP wrapper around llama-server's /v1/chat/completions endpoint."""

    def __init__(self, host: str, port: int, timeout: float = 60.0):
        self.base_url = f"http://{host}:{port}/v1/chat/completions"
        self.health_url = f"http://{host}:{port}/health"
        self.timeout = timeout

    def ping(self) -> bool:
        """Check if llama-server is online."""
        try:
            req = urllib.request.Request(self.health_url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except Exception:
            return False

    def create_chat_completion(
        self, 
        messages: list, 
        stream: bool = False, 
        max_tokens: int = 512, 
        temperature: float = 0.7,
        tools: list = None,
        tool_choice: str = "auto"
        ):
        
        payload = {
            "model": getattr(model_cfg, "llm_model_name", "default"),
            "messages": messages,
            "stream": stream,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "cache_prompt": True,
        }
        
        # Inject tools (ensure it is always an array to avoid Jinja template loop crashes)
        payload["tools"] = tools if tools is not None else []
        if tools:
            payload["tool_choice"] = tool_choice
        
        if not stream:
            import requests
            try:
                r = requests.post(
                    self.base_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=self.timeout
                )
                r.raise_for_status()
                return r.json()
            except Exception as e:
                print(f"[llama-server HTTP Error]: {e}, falling back to urllib")
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    self.base_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    return result

        # Handle SSE Streaming response using requests for unbuffered real-time output
        def stream_generator():
            import requests
            try:
                r = requests.post(
                    self.base_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    stream=True,
                    timeout=self.timeout
                )
                r.raise_for_status()
                for line in r.iter_lines(decode_unicode=True):
                    if line:
                        line = line.strip()
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                yield json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                print(f"\n[llama-server Stream Error]: {e}, falling back to urllib stream")
                # Fallback to urllib
                try:
                    data = json.dumps(payload).encode("utf-8")
                    req = urllib.request.Request(
                        self.base_url,
                        data=data,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    response = urllib.request.urlopen(req, timeout=self.timeout)
                    for line in response:
                        line = line.decode("utf-8").strip()
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                yield json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                except Exception as ex:
                    print(f"\n[llama-server Fallback Stream Error]: {ex}")
                    return

        return stream_generator()

    def __call__(self, prompt: str, max_tokens: int = 512):
        """Fallback non-chat interface for text completions."""
        res = self.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            max_tokens=max_tokens,
        )
        return {"text": res["choices"][0]["message"]["content"]}


def load_llm_engine() -> LlamaServerClient:
    print(f"Connecting to llama-server at http://{model_cfg.server_host}:{model_cfg.server_port}...")
    client = LlamaServerClient(
        host=model_cfg.server_host,
        port=model_cfg.server_port,
        timeout=model_cfg.server_timeout,
    )

    if not client.ping():
        print(f"[WARNING] Could not connect to llama-server at {model_cfg.server_host}:{model_cfg.server_port}. Ensure server is running.")
    else:
        print("Connected to llama-server successfully.")

    return client