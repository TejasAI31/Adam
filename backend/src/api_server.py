import os
import sys

# Limit thread pools for CPU math libraries (NumPy, PyTorch, OpenMP, etc.) to 4 threads
# and optimize CUDA allocator memory fragmentation
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"
os.environ["OPENBLAS_NUM_THREADS"] = "4"
os.environ["VECLIB_MAXIMUM_THREADS"] = "4"
os.environ["NUMEXPR_NUM_THREADS"] = "4"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# Mock importlib.metadata.version to resolve torchcodec in PyInstaller compiled environment
import importlib.metadata
_orig_version = importlib.metadata.version
def _mock_version(package_name):
    try:
        return _orig_version(package_name)
    except importlib.metadata.PackageNotFoundError:
        if package_name == "torchcodec":
            return "0.7.0"
        raise
importlib.metadata.version = _mock_version

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")
warnings.filterwarnings("ignore", category=UserWarning, module="torchcodec")
import json

# Ensure working directory is set to executable directory for PyInstaller compiled executable
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

import time
import shutil
import queue
import logging
import asyncio
import threading
import subprocess
import dataclasses
import urllib.request
from typing import Dict, List, Optional
from pydantic import BaseModel
import psutil
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# Ensure correct pathing
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.utils.dll_setup

# Explicit eager imports of lazy-loaded transformers/pyannote submodules to ensure PyInstaller bundles them
def _pyinstaller_eager_imports():
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


from config.settings import audio_cfg, model_cfg
from src.audio.device import SHARED_AUDIO

def run_garbage_collector():
    while True:
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            # 1. Clean screenshots directory
            screenshots_dir = os.path.join(base_dir, "screenshots")
            if os.path.exists(screenshots_dir):
                for f in os.listdir(screenshots_dir):
                    if f != ".gitkeep":
                        file_path = os.path.join(screenshots_dir, f)
                        if os.path.isfile(file_path):
                            mtime = os.path.getmtime(file_path)
                            if time.time() - mtime > 30:
                                try:
                                    os.remove(file_path)
                                except Exception:
                                    pass
                                    
            # 2. Clean outputs directory
            outputs_dir = os.path.join(base_dir, "outputs")
            if os.path.exists(outputs_dir):
                for f in os.listdir(outputs_dir):
                    if f not in ["chime.wav", ".gitkeep"]:
                        file_path = os.path.join(outputs_dir, f)
                        if os.path.isfile(file_path):
                            mtime = os.path.getmtime(file_path)
                            if time.time() - mtime > 30:
                                try:
                                    os.remove(file_path)
                                except Exception:
                                    pass
        except Exception:
            pass
        time.sleep(10)

# Start garbage collector thread
threading.Thread(target=run_garbage_collector, daemon=True).start()

app = FastAPI(title="Adam API Server")

# Allow Electron to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global engine states
llama_process: Optional[subprocess.Popen] = None
llm_client = None
stt_engine = None
tts_engine = None
duplex_manager = None
session_histories = {}

cached_resources = {
    "cpu": 0.0,
    "ram": {"used": 0.0, "total": 0.0, "percent": 0.0},
    "gpu": 0.0,
    "vram": {"used": 0.0, "total": 0.0, "percent": 0.0}
}

def update_resource_stats_once():
    global cached_resources
    import psutil
    import shutil
    import subprocess
    
    # 1. CPU / RAM
    try:
        cpu_usage = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        ram_usage = ram.percent
        ram_total = ram.total / (1024**3)
        ram_used = ram.used / (1024**3)
        cached_resources["cpu"] = cpu_usage
        cached_resources["ram"] = {
            "used": round(ram_used, 2),
            "total": round(ram_total, 2),
            "percent": round(ram_usage, 1)
        }
    except:
        pass
        
    # 2. GPU / VRAM
    gpu_usage = 0.0
    vram_used = 0.0
    vram_total = 0.0
    
    # Try pynvml if available
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        gpu_usage = float(util.gpu)
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        vram_used = mem_info.used / (1024**3)
        vram_total = mem_info.total / (1024**3)
    except:
        pass
        
    # Fallback to nvidia-smi if nvml failed or is not available
    if vram_total == 0.0:
        nv_smi = shutil.which("nvidia-smi") or "C:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe"
        if os.path.exists(nv_smi) or shutil.which("nvidia-smi"):
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=1.0
                )
                if res.returncode == 0:
                    parts = res.stdout.strip().split(",")
                    gpu_usage = float(parts[0].strip())
                    vram_used = float(parts[1].strip()) / 1024.0
                    vram_total = float(parts[2].strip()) / 1024.0
            except:
                pass
        
    # Fallback to PyTorch memory check if cuda is loaded
    if vram_total == 0.0:
        try:
            import torch
            if torch.cuda.is_available():
                dev = torch.cuda.current_device()
                free, total = torch.cuda.mem_get_info(dev)
                vram_total = total / (1024**3)
                vram_used = (total - free) / (1024**3)
        except:
            pass
    
    vram_percent = 0.0
    if vram_total > 0:
        vram_percent = (vram_used / vram_total) * 100.0
        
    cached_resources["gpu"] = gpu_usage
    cached_resources["vram"] = {
        "used": round(vram_used, 2),
        "total": round(vram_total, 2),
        "percent": round(vram_percent, 1)
    }

# Prime the resource metrics immediately
try:
    update_resource_stats_once()
except:
    pass

def resource_monitor_thread_fn():
    import time
    while True:
        try:
            update_resource_stats_once()
        except:
            pass
        time.sleep(2.0)


def get_sessions_json_path():
    from config.settings import get_user_data_dir
    import shutil
    app_data_path = os.path.join(get_user_data_dir(), "sessions.json")
    
    # Migrates bundled sessions.json to AppData if not present
    if not os.path.exists(app_data_path):
        bundled_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "sessions.json")
        if os.path.exists(bundled_path):
            try:
                shutil.copy2(bundled_path, app_data_path)
            except Exception as e:
                print("Failed to copy bundled sessions.json:", e)
                
    return app_data_path

def load_sessions_list() -> list:
    path = get_sessions_json_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("Error reading sessions.json:", e)
    return []

def save_sessions_list(data: list):
    path = get_sessions_json_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print("Error writing sessions.json:", e)

def append_message_to_sessions(session_id, sender, text, msg_id, attachments=None, image=None):
    global session_histories
    if not session_id:
        return
    sessions = load_sessions_list()
    session = next((s for s in sessions if s.get("id") == session_id), None)
    if not session:
        session = {"id": session_id, "name": "Default Session", "messages": []}
        sessions.append(session)
    
    if not any(m.get("id") == msg_id for m in session["messages"]):
        clean_attachments = []
        if attachments:
            for att in attachments:
                clean_attachments.append({
                    "name": att.get("name"),
                    "type": att.get("type"),
                    "data": att.get("data")
                })
        
        # Recover root image from attachments if not provided
        if not image and attachments:
            img_att = next((a for a in attachments if a.get("type") == "image"), None)
            if img_att:
                image = img_att.get("data")

        session["messages"].append({
            "sender": sender,
            "text": text,
            "id": msg_id,
            "image": image,
            "attachments": clean_attachments
        })
        save_sessions_list(sessions)
        
        if session_id not in session_histories:
            session_histories[session_id] = []
        session_histories[session_id].append({
            "role": "user" if sender == "user" else "assistant",
            "content": text
        })
        
        broadcast_event("sessions_updated", {})

def sync_session_history_to_persistence(session_id: str, prune_ui_messages: bool = False):
    global session_histories, duplex_manager
    if not session_id or not duplex_manager:
        return
    with duplex_manager.history_lock:
        history_copy = list(duplex_manager.history)
    
    session_histories[session_id] = history_copy
    
    if prune_ui_messages:
        try:
            sessions = load_sessions_list()
            session = next((s for s in sessions if s.get("id") == session_id), None)
            if session:
                llm_msg_count = sum(1 for m in history_copy if m.get("role") in ("user", "assistant"))
                if len(session["messages"]) > llm_msg_count and llm_msg_count > 0:
                    session["messages"] = session["messages"][-llm_msg_count:]
                    save_sessions_list(sessions)
                    broadcast_event("sessions_updated", {})
        except Exception as e:
            print(f"Error syncing session {session_id} to persistence:", e)


# Load persistent sessions into memory session_histories on boot
try:
    saved_sessions = load_sessions_list()
    for s in saved_sessions:
        s_id = s.get("id")
        if s_id:
            h = []
            for m in s.get("messages", []):
                h.append({
                    "role": "user" if m.get("sender") == "user" else "assistant",
                    "content": m.get("text", "")
                })
            session_histories[s_id] = h
except Exception as e:
    print("Error pre-populating session histories:", e)

setup_lock = threading.Lock()
chat_pipeline_lock = threading.Lock()
is_setting_up = False
is_remote_control_only = False
setup_progress = {"status": "Not started", "progress": 0, "error": None, "cause": None}

voice_loop_thread: Optional[threading.Thread] = None
voice_loop_running = False
voice_loop_stop_event = threading.Event()
voice_input_muted = True
active_session_id = None
current_processing_session_id = None

# SSE event broadcast lists
active_sse_queues: List[asyncio.Queue] = []
main_event_loop: Optional[asyncio.AbstractEventLoop] = None

# Keep a buffer of the logs to send to UI
log_queue = queue.Queue(maxsize=1000)

class SetupPayload(BaseModel):
    main_model: str
    draft_model: Optional[str] = None
    mmproj_model: Optional[str] = None
    main_device: Optional[str] = "gpu"
    draft_device: Optional[str] = "gpu"
    mmproj_device: Optional[str] = "gpu"
    stt_device: Optional[str] = "gpu"
    tts_device: Optional[str] = "gpu"
    stt_enabled: Optional[bool] = True
    tts_enabled: Optional[bool] = True
    stt_model_size: Optional[str] = "medium"
    cache_type_k: Optional[str] = "q4_0"
    cache_type_v: Optional[str] = "q4_0"

class Attachment(BaseModel):
    name: str
    type: str  # "image" or "pdf"
    data: str  # Base64 data URI or raw base64

class ChatPayload(BaseModel):
    message: str
    image: Optional[str] = None # Base64 data URI
    attachments: Optional[List[Attachment]] = []
    speech_enabled: bool = True
    msg_id: Optional[str] = None
    session_id: Optional[str] = None

# Helper to load settings.json from the user profile (APPDATA/Adam/settings.json)
def get_settings_json_path():
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        if not app_data:
            app_data = os.path.expanduser("~\\AppData\\Roaming")
        base_dir = os.path.join(app_data, "Adam")
    elif sys.platform == "darwin":
        base_dir = os.path.expanduser("~/Library/Application Support/Adam")
    else:
        base_dir = os.path.expanduser("~/.config/Adam")
        
    try:
        os.makedirs(base_dir, exist_ok=True)
    except Exception:
        pass
        
    return os.path.join(base_dir, "settings.json")

def load_settings_dict() -> dict:
    path = get_settings_json_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print("Error reading settings.json:", e)
            
    # Fallback to local default template
    if getattr(sys, 'frozen', False):
        default_path = os.path.join(os.path.dirname(sys.executable), "config", "settings.json")
    else:
        default_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "settings.json")
        
    if os.path.exists(default_path):
        try:
            with open(default_path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_settings_dict(data: dict):
    path = get_settings_json_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    existing = json.load(f)
            except Exception:
                pass
        
        # Merge the new config (data) into existing keys, preserving other keys like "sharing"
        for k, v in data.items():
            if isinstance(v, dict) and k in existing and isinstance(existing[k], dict):
                existing[k].update(v)
            else:
                existing[k] = v

        with open(path, "w") as f:
            json.dump(existing, f, indent=4)
    except Exception as e:
        print("Error writing settings.json:", e)

# SSE Broadcast function
def broadcast_event(event_type: str, data: dict):
    global main_event_loop
    payload = {"type": event_type, "data": data, "timestamp": time.time()}
    msg_str = f"data: {json.dumps(payload)}\n\n"
    
    if main_event_loop and main_event_loop.is_running():
        for q in active_sse_queues:
            main_event_loop.call_soon_threadsafe(q.put_nowait, msg_str)
    else:
        # Fallback to get_event_loop
        try:
            loop = asyncio.get_event_loop()
            if loop and loop.is_running():
                for q in active_sse_queues:
                    loop.call_soon_threadsafe(q.put_nowait, msg_str)
        except RuntimeError:
            pass

def broadcast_log(origin: str, line: str):
    log_line = f"[{origin}] {line.strip()}"
    # Add to in-memory queue
    if log_queue.full():
        try:
            log_queue.get_nowait()
        except queue.Empty:
            pass
    log_queue.put(log_line)
    broadcast_event("log", {"line": log_line})

# Stop running components
def stop_all_components():
    global llama_process, duplex_manager, voice_loop_running, voice_loop_stop_event
    
    # 1. Stop voice duplex loop
    if voice_loop_running:
        broadcast_log("SYSTEM", "Stopping voice loop...")
        voice_loop_stop_event.set()
        voice_loop_running = False
        if duplex_manager:
            duplex_manager.stop_requested.set()
            duplex_manager.interrupt()
        # Sleep slightly to let threads release PyAudio
        time.sleep(0.5)
        
    # 2. Stop llama-server.exe
    if llama_process:
        broadcast_log("SYSTEM", "Stopping llama-server.exe process...")
        try:
            llama_process.terminate()
            llama_process.wait(timeout=3)
        except Exception:
            try:
                llama_process.kill()
            except Exception:
                pass
        llama_process = None
        
    # Force taskkill standard binary if lingering
    try:
        subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

# Background tailing for llama_server.log
def tail_llama_log():
    log_path = "llama_server.log"
    if not os.path.exists(log_path):
        open(log_path, "w").close()
    
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(0, os.SEEK_END)
            while True:
                if not llama_process:
                    break
                line = f.readline()
                if line:
                    line_lower = line.lower()
                    # Filter out verbose streamed chunks, parsed messages, and template errors/warnings
                    suppress = [
                        "streamed chunk",
                        "parsed message",
                        "template error",
                        "template warning",
                        "chat template",
                        "chat_template",
                        "jinja"
                    ]
                    if any(s in line_lower for s in suppress):
                        continue
                    broadcast_log("LlamaCPP", line)
                else:
                    time.sleep(0.1)
    except Exception as e:
        print("Error in tailing llama log:", e)

def run_setup_worker(payload: SetupPayload):
    global llama_process, llm_client, stt_engine, tts_engine, duplex_manager, is_setting_up, setup_progress, is_remote_control_only
    
    with setup_lock:
        is_remote_control_only = not payload.main_model
        is_setting_up = True
        setup_progress = {
            "status": "Initializing setup...", 
            "progress": 5, 
            "error": None, 
            "cause": None,
            "stt_enabled": payload.stt_enabled,
            "tts_enabled": payload.tts_enabled
        }
        broadcast_event("setup_progress", setup_progress)
        
        try:
            # 1. Stop everything currently running
            setup_progress.update({"status": "Stopping running models and processes...", "progress": 15})
            broadcast_event("setup_progress", setup_progress)
            stop_all_components()
            
            if not payload.main_model:
                s_dict = load_settings_dict()
                if "model" not in s_dict:
                    s_dict["model"] = {}
                s_dict["model"]["llm_model_name"] = ""
                s_dict["model"]["stt_enabled"] = False
                s_dict["model"]["tts_enabled"] = False
                if "llama" not in s_dict:
                    s_dict["llama"] = {}
                s_dict["llama"]["MAIN_MODEL_FILE"] = ""
                s_dict["llama"]["DRAFT_MODEL_FILE"] = None
                s_dict["llama"]["MMPROJ_MODEL_FILE"] = None
                save_settings_dict(s_dict)
                
                global stt_engine, tts_engine, duplex_manager, llm_client
                stt_engine = None
                tts_engine = None
                duplex_manager = None
                llm_client = None
                
                setup_progress.update({
                    "status": "Remote Control Mode Active", 
                    "progress": 100,
                    "stt_enabled": False,
                    "tts_enabled": False
                })
                broadcast_event("setup_progress", setup_progress)
                broadcast_log("SYSTEM", "Adam speech engine skipped. Remote control mode online.")
                return
            
            # 2. Update config files with these selected models and devices
            s_dict = load_settings_dict()
            if "model" not in s_dict:
                s_dict["model"] = {}
            s_dict["model"]["llm_model_name"] = payload.main_model
            # Also set the batch files files if any
            if "llama" not in s_dict:
                s_dict["llama"] = {}
            s_dict["llama"]["MAIN_MODEL_FILE"] = payload.main_model
            s_dict["llama"]["DRAFT_MODEL_FILE"] = payload.draft_model
            s_dict["llama"]["MMPROJ_MODEL_FILE"] = payload.mmproj_model
            
            # Map devices
            main_ngl = 99 if payload.main_device == "gpu" else 0
            draft_ngl = 99 if payload.draft_device == "gpu" else 0
            s_dict["llama"]["ngl"] = main_ngl
            s_dict["llama"]["draft_ngl"] = draft_ngl
            s_dict["llama"]["main_device"] = payload.main_device or "gpu"
            s_dict["llama"]["draft_device"] = payload.draft_device or "gpu"
            s_dict["llama"]["mmproj_device"] = payload.mmproj_device or "gpu"
            s_dict["llama"]["cache_type_k"] = payload.cache_type_k or "q4_0"
            s_dict["llama"]["cache_type_v"] = payload.cache_type_v or "q4_0"
            
            # Map STT/TTS devices and enablement
            stt_dev = "cuda" if payload.stt_device == "gpu" else "cpu"
            tts_dev = "cuda" if payload.tts_device == "gpu" else "cpu"
            s_dict["model"]["stt_device"] = stt_dev
            s_dict["model"]["tts_device"] = tts_dev
            s_dict["model"]["stt_model_size"] = payload.stt_model_size or "medium"
            s_dict["model"]["stt_enabled"] = payload.stt_enabled
            s_dict["model"]["tts_enabled"] = payload.tts_enabled
            
            save_settings_dict(s_dict)
            
            # 3. Reload settings (by forcing setting.py re-parsing, or we loaded it dynamically)
            from config.settings import model_cfg, audio_cfg
            model_cfg.llm_model_name = payload.main_model
            model_cfg.stt_device = stt_dev
            model_cfg.tts_device = tts_dev
            model_cfg.stt_model_size = payload.stt_model_size or "medium"
            
            # 4. Spawning llama-server
            setup_progress.update({"status": "Configuring model paths and launching llama-server.exe...", "progress": 30})
            broadcast_event("setup_progress", setup_progress)
            
            main_model_path = os.path.join("models", payload.main_model)
            mmproj_path = os.path.join("models", "mmproj", payload.mmproj_model) if payload.mmproj_model else None
            draft_model_path = os.path.join("models", "drafters", payload.draft_model) if payload.draft_model else None
            
            if not os.path.exists(main_model_path):
                raise FileNotFoundError(f"Main model file '{main_model_path}' not found in models/ folder.")
            
            if getattr(sys, 'frozen', False):
                beside_llama = os.path.join(os.path.dirname(sys.executable), "llama-server.exe")
                if os.path.exists(beside_llama):
                    llama_bin = beside_llama
                else:
                    llama_bin = shutil.which("llama-server") or shutil.which("llama-server.exe") or "llama-server.exe"
            else:
                llama_bin = shutil.which("llama-server") or shutil.which("llama-server.exe") or "llama-server.exe"
            
            # Llama configurations from settings.json or defaults
            llama_opts = s_dict.get("llama", {})
            port = int(llama_opts.get("SERVER_PORT", model_cfg.server_port))
            host = llama_opts.get("SERVER_HOST", model_cfg.server_host)
            ctx_size = int(llama_opts.get("context_size", 30000))
            ngl = main_ngl
            flash_attn = llama_opts.get("flash_attn", "on")
            cache_k = llama_opts.get("cache_type_k", "q4_0")
            cache_v = llama_opts.get("cache_type_v", "q4_0")
            
            # Determine optimal threads targeting physical CPU cores for maximum speed/low overhead
            cpu_threads = psutil.cpu_count(logical=False) or 4
            
            cmd = [
                llama_bin,
                "-m", main_model_path,
                "--host", host,
                "--port", str(port),
                "-c", str(ctx_size),
                "-t", str(cpu_threads),
                "-ngl", str(ngl),
                "--flash-attn", flash_attn,
                "--cache-type-k", cache_k,
                "--cache-type-v", cache_v,
                "--log-colors", "auto"
            ]
            if "qwen" in payload.main_model.lower():
                cmd.extend(["--jinja", "--chat-template-file", "config/qwen_fixed.jinja"])
            if mmproj_path:
                cmd.extend(["--mmproj", mmproj_path])
            if draft_model_path:
                cmd.extend([
                    "-md", draft_model_path,
                    "--spec-draft-n-max", str(llama_opts.get("spec_draft_n_max", 16)),
                    "-ngld", str(draft_ngl)
                ])
            broadcast_log("SYSTEM", f"Spawning command: {' '.join(cmd)}")
            
            log_f = open("llama_server.log", "w", encoding="utf-8")
            llama_process = subprocess.Popen(
                cmd, 
                stdout=log_f, 
                stderr=log_f, 
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            
            # Start logs tailing in a background thread
            threading.Thread(target=tail_llama_log, daemon=True).start()
            
            # 5. Polling health check
            setup_progress.update({"status": "Waiting for llama-server.exe to load model weights...", "progress": 45})
            broadcast_event("setup_progress", setup_progress)
            
            health_url = f"http://{host}:{port}/health"
            server_online = False
            timeout_sec = int(llama_opts.get("SERVER_TIMEOUT", 60))
            
            for s in range(timeout_sec):
                if llama_process.poll() is not None:
                    # Llama server crashed
                    log_err = ""
                    try:
                        with open("llama_server.log", "r", encoding="utf-8", errors="ignore") as lf:
                            lines = lf.readlines()
                            log_err = "\n".join(lines[-15:])
                    except:
                        pass
                    raise RuntimeError(f"llama-server.exe crashed on launch. Error log tail:\n{log_err}")
                
                try:
                    req = urllib.request.Request(health_url, method="GET")
                    with urllib.request.urlopen(req, timeout=1.0) as res:
                        if res.status == 200:
                            server_online = True
                            break
                except Exception:
                    pass
                time.sleep(1)
                
            if not server_online:
                raise TimeoutError("llama-server.exe did not become healthy within the configured timeout period.")
                
            broadcast_log("SYSTEM", "llama-server.exe is online!")
            
            # 6. Load LLM client
            from src.llm.llama_engine import LlamaServerClient
            llm_client = LlamaServerClient(host=host, port=port, timeout=model_cfg.server_timeout)
            
            # 7. Load STT
            if payload.stt_enabled:
                setup_progress.update({"status": "Loading WhisperX Speech-to-Text engine...", "progress": 65})
                broadcast_event("setup_progress", setup_progress)
                from src.stt.whisperx_engine import load_stt_engine
                stt_engine = load_stt_engine()
                broadcast_log("SYSTEM", "WhisperX STT engine loaded successfully.")
            else:
                stt_engine = None
                broadcast_log("SYSTEM", "WhisperX STT engine loading skipped.")
            
            # Import warmup function unconditionally to avoid UnboundLocalError when tts is disabled
            from src.tts.qwen_tts import warmup_and_generate_chime

            # 8. Load TTS
            if payload.tts_enabled:
                setup_progress.update({"status": "Loading Qwen Text-to-Speech engine (GPU)...", "progress": 80})
                broadcast_event("setup_progress", setup_progress)
                from src.tts.qwen_tts import load_tts_engine
                tts_engine = load_tts_engine()
                broadcast_log("SYSTEM", "TTS engine loaded successfully.")
            else:
                tts_engine = None
                broadcast_log("SYSTEM", "TTS engine loading skipped.")
            
            # 9. Warmup
            if payload.tts_enabled or llm_client:
                setup_progress.update({"status": "Warming up model endpoints and generating chimes...", "progress": 90})
                broadcast_event("setup_progress", setup_progress)
                warmup_and_generate_chime(tts_engine, llm_client)
                broadcast_log("SYSTEM", "Warmup complete.")
            
            # 10. Instantiate Duplex Manager
            from src.orchestration.duplex_manager import FullDuplexManager
            duplex_manager = FullDuplexManager(llm_model=llm_client, tts_model=tts_engine)
            
            def on_playback_status(active: bool):
                broadcast_event("playback_status", {"active": active})
            duplex_manager.on_playback_status = on_playback_status
            
            # 11. Start duplex voice loop in background
            if payload.stt_enabled:
                setup_progress.update({"status": "Configuring microphone and activating duplex voice engine...", "progress": 95})
                broadcast_event("setup_progress", setup_progress)
                start_duplex_loop()
            else:
                broadcast_log("SYSTEM", "Speech activation loop skipped since STT is disabled.")
            
            # 12. Complete!
            setup_progress.update({"status": "Setup completed successfully!", "progress": 100})
            broadcast_event("setup_progress", setup_progress)
            broadcast_log("SYSTEM", "Adam speech engine is now ONLINE and ready!")
            
        except Exception as e:
            import traceback
            cause_msg = str(e)
            print("Setup failed:", cause_msg)
            traceback.print_exc()
            setup_progress.update({
                "status": "Failed",
                "progress": 0,
                "error": type(e).__name__,
                "cause": cause_msg
            })
            broadcast_event("setup_progress", setup_progress)
            broadcast_log("ERROR", f"Setup failed: {cause_msg}")
            stop_all_components()
        finally:
            is_setting_up = False

def start_duplex_loop():
    global voice_loop_thread, voice_loop_running, voice_loop_stop_event
    if voice_loop_running:
        return
    voice_loop_stop_event.clear()
    voice_loop_running = True
    voice_loop_thread = threading.Thread(target=voice_loop_worker, daemon=True)
    voice_loop_thread.start()
    broadcast_log("SYSTEM", "Duplex voice activation loop online.")

def voice_loop_worker():
    global duplex_manager, stt_engine, voice_loop_running, voice_loop_stop_event, voice_input_muted
    
    import webrtcvad
    import pyaudio
    from src.audio.dsp import preprocess_audio
    
    vad = webrtcvad.Vad(audio_cfg.vad_aggressiveness)
    
    try:
        default_input_index = SHARED_AUDIO.get_default_input_device_info()["index"]
    except Exception as e:
        broadcast_log("ERROR", f"Audio device error: {e}. Voice loop cannot run.")
        voice_loop_running = False
        return
        
    try:
        stream = SHARED_AUDIO.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=audio_cfg.sample_rate,
            input=True,
            input_device_index=default_input_index,
            frames_per_buffer=audio_cfg.frame_size,
        )
    except Exception as e:
        broadcast_log("ERROR", f"Failed to open PyAudio input stream: {e}.")
        voice_loop_running = False
        return
        
    triggered = False
    voiced_frames = []
    ring_buffer = []
    
    broadcast_log("SYSTEM", "Microphone pipeline listening... Say 'Adam' to start talking.")
    
    try:
        while not voice_loop_stop_event.is_set():
            if voice_input_muted:
                time.sleep(0.1)
                continue
                
            try:
                frame = stream.read(audio_cfg.frame_size, exception_on_overflow=False)
            except Exception:
                time.sleep(0.01)
                continue
                
            if not frame:
                continue
                
            is_speech = vad.is_speech(frame, audio_cfg.sample_rate)
            
            # Simple UI broadcast of speech level (optional but neat)
            if is_speech:
                broadcast_event("mic_activity", {"active": True})
                
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
                current_duration = (len(voiced_frames) * audio_cfg.frame_duration_ms) / 1000.0
                
                if num_unvoiced > 0.8 * len(ring_buffer) or current_duration >= audio_cfg.max_speech_duration:
                    if current_duration >= audio_cfg.min_speech_duration:
                        raw_chunk = b"".join(voiced_frames)
                        clean_audio_array = preprocess_audio(raw_chunk)
                        
                        broadcast_log("STT", "Processing user voice input...")
                        broadcast_event("voice_status", {"status": "transcribing"})
                        
                        try:
                            result = stt_engine.transcribe(clean_audio_array, batch_size=model_cfg.stt_batch_size)
                            segments = result.get("segments", [])
                            transcription = " ".join([s.get("text", "").strip() for s in segments]).strip()
                        except Exception as stt_err:
                            broadcast_log("ERROR", f"STT Transcription error: {stt_err}")
                            transcription = ""
                        finally:
                            pass
                            
                        if transcription:
                            broadcast_log("STT", f"Transcribed text: \"{transcription}\"")
                            broadcast_event("voice_status", {"status": "idle", "transcription": transcription})
                            
                            # Trigger response if 'adam' is named
                            if "adam" in transcription.lower():
                                if duplex_manager.is_speaking:
                                    duplex_manager.interrupt()
                                    broadcast_log("SYSTEM", "User interrupted playback!")
                                    
                                # Post message to UI chat
                                broadcast_event("chat_message", {
                                    "sender": "user", 
                                    "text": transcription, 
                                    "type": "voice",
                                    "id": f"msg_{int(time.time()*1000)}"
                                })
                                
                                # Launch async response process
                                threading.Thread(
                                    target=run_chat_pipeline_helper,
                                    args=(transcription, None, True),
                                    daemon=True
                                ).start()
                        else:
                            broadcast_event("voice_status", {"status": "idle"})
                            
                    triggered = False
                    ring_buffer.clear()
                    voiced_frames.clear()
    except Exception as e:
        broadcast_log("ERROR", f"Voice loop thread runtime error: {e}")
    finally:
        try:
            stream.stop_stream()
            stream.close()
        except:
            pass

def run_chat_pipeline_helper(prompt: str, image_input: Optional[str] = None, speech_enabled: bool = True, session_id: Optional[str] = None, attachments: Optional[List[dict]] = None):
    global duplex_manager, session_histories, active_session_id, current_processing_session_id
    if not duplex_manager:
        broadcast_log("ERROR", "Duplex manager not ready. Initialize setup first.")
        return
        
    target_session_id = session_id or active_session_id
    
    # Only interrupt if the user sent a prompt in the SAME session that is currently processing!
    # Or if we want to interrupt speech synthesis.
    if duplex_manager:
        if target_session_id == current_processing_session_id or duplex_manager.is_speaking:
            duplex_manager.interrupt()
        
    with chat_pipeline_lock:
        current_processing_session_id = target_session_id
        if target_session_id:
            if target_session_id not in session_histories:
                session_histories[target_session_id] = []
            duplex_manager.history = session_histories[target_session_id]
            
        current_response_text = ""
        msg_id = f"msg_{int(time.time()*1000)}_asst"
        
        # Broadcast start
        broadcast_event("chat_status", {"status": "typing", "msg_id": msg_id, "session_id": target_session_id})
        
        def pipeline_callback(event_type, data):
            nonlocal current_response_text
            if event_type == "text":
                current_response_text += data
                broadcast_event("chat_chunk", {"msg_id": msg_id, "text": data, "session_id": target_session_id})
            elif event_type == "tool_start":
                broadcast_log("TOOL", f"Starting tool {data.get('name')} with arguments {data.get('arguments')}")
                broadcast_event("chat_tool", {"status": "start", "msg_id": msg_id, "tool": data, "session_id": target_session_id})
            elif event_type == "tool_end":
                broadcast_log("TOOL", f"Tool {data.get('name')} returned output of length {len(str(data.get('output')))}")
                broadcast_event("chat_tool", {"status": "end", "msg_id": msg_id, "tool": data, "session_id": target_session_id})

        try:
            # Import tools dynamically
            from src.llm.tools.math_tools import MATH_TOOLS_MAP, MATH_TOOL_SCHEMAS
            from src.llm.tools.websearch_tool import WEBSEARCH_TOOL_MAP, WEBSEARCH_TOOL_SCHEMAS
            from src.llm.tools.ytmusic_tools import YTMUSIC_TOOL_MAP, YTMUSIC_TOOL_SCHEMAS
            from src.llm.tools.url_opener_tool import BROWSER_TOOL_MAP, BROWSER_TOOL_SCHEMAS
            from src.llm.tools.system_tools import SYSTEM_TOOLS_MAP, SYSTEM_TOOLS_SCHEMAS

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

            # Filter schemas and maps based on settings.json
            s_dict = load_settings_dict()
            enabled_tools = s_dict.get("enabled_tools", {})

            def is_tool_enabled(name):
                # If enabled_tools is not configured or empty, default to True
                if not enabled_tools:
                    return True
                return enabled_tools.get(name, True)

            active_tools = []
            for t in tools:
                name = t.get("function", {}).get("name")
                if is_tool_enabled(name):
                    # Force model to analyze the given image instead of screenshotting the desktop
                    if image_input and name in ["take_screenshot", "scan_screen_elements"]:
                        continue
                    active_tools.append(t)

            active_tool_maps = {}
            for name, func in tool_maps.items():
                if is_tool_enabled(name):
                    if image_input and name in ["take_screenshot", "scan_screen_elements"]:
                        continue
                    active_tool_maps[name] = func

            duplex_manager.process_pipeline(
                prompt,
                image_input=image_input,
                attachments=attachments,
                tools=active_tools if active_tools else None,
                available_functions=active_tool_maps,
                speech_enabled=speech_enabled,
                callback=pipeline_callback
            )
            
            # Broadcast full done message
            broadcast_event("chat_message", {
                "sender": "assistant", 
                "text": current_response_text, 
                "type": "text", 
                "id": msg_id,
                "session_id": target_session_id
            })
            append_message_to_sessions(target_session_id, "assistant", current_response_text, msg_id)
        except Exception as err:
            broadcast_log("ERROR", f"LLM Chat pipeline execution error: {err}")
            broadcast_event("chat_error", {"msg_id": msg_id, "error": str(err), "session_id": target_session_id})
        finally:
            if target_session_id and duplex_manager:
                sync_session_history_to_persistence(target_session_id)

            current_processing_session_id = None
            import gc
            import torch
            if torch.cuda.is_available():
                try:
                    torch.cuda.empty_cache()
                except:
                    pass
            gc.collect()

# --- API ENDPOINTS ---

# --- DOWNLOAD MANAGER FOR INCORPORATED MODELS ---
class ModelDownloadPayload(BaseModel):
    model_name: str
    restart: Optional[bool] = False


download_statuses = {}
cancelled_downloads = set()
download_lock = threading.Lock()


DOWNLOAD_URLS = {
    "Qwen3.5-4B-Q4_K_M.gguf": {
        "url": "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf",
        "path": os.path.join("models", "Qwen3.5-4B-Q4_K_M.gguf")
    },
    "Qwen3VL-2B-Instruct-Q4_K_M.gguf": {
        "url": "https://huggingface.co/unsloth/Qwen3-VL-2B-Instruct-GGUF/resolve/main/Qwen3-VL-2B-Instruct-Q4_K_M.gguf",
        "path": os.path.join("models", "Qwen3VL-2B-Instruct-Q4_K_M.gguf")
    },
    "Qwen3.5-0.8B-Q4_K_M.gguf": {
        "url": "https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/resolve/main/Qwen3.5-0.8B-Q4_K_M.gguf",
        "path": os.path.join("models", "drafters", "Qwen3.5-0.8B-Q4_K_M.gguf")
    },
    "mmproj-Qwen3.5-4B-BF16.gguf": {
        "url": "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/mmproj-BF16.gguf",
        "path": os.path.join("models", "mmproj", "mmproj-Qwen3.5-4B-BF16.gguf")
    },
    "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf": {
        "url": "https://huggingface.co/unsloth/Qwen3-VL-2B-Instruct-GGUF/resolve/main/mmproj-BF16.gguf",
        "path": os.path.join("models", "mmproj", "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf")
    }
}

def download_gguf_single_threaded(url, dest_path, temp_path, model_name):
    global download_statuses, cancelled_downloads
    
    downloaded = 0
    if os.path.exists(temp_path):
        try:
            downloaded = os.path.getsize(temp_path)
        except:
            downloaded = 0
            
    with download_lock:
        download_statuses[model_name] = {
            "status": "downloading",
            "progress": 0.0,
            "downloaded_bytes": downloaded,
            "total_bytes": 0,
            "speed_mbps": 0.0,
            "model_name": model_name,
            "error": None
        }
        
    print(f"[Downloader] Starting/resuming GGUF single-threaded download from {url} at offset {downloaded}")
    req = urllib.request.Request(
        url, 
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    if downloaded > 0:
        req.add_header("Range", f"bytes={downloaded}-")
        
    try:
        response = urllib.request.urlopen(req)
        status_code = response.status
    except urllib.error.HTTPError as he:
        if he.code == 416:
            downloaded = 0
            req = urllib.request.Request(
                url, 
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            response = urllib.request.urlopen(req)
            status_code = response.status
        else:
            raise he

    if status_code == 206:
        content_range = response.headers.get('Content-Range')
        if content_range:
            total_size = int(content_range.split('/')[-1])
        else:
            total_size = downloaded + int(response.headers.get('content-length', 0))
    else:
        downloaded = 0
        total_size = int(response.headers.get('content-length', 0))
        
    with download_lock:
        if model_name in download_statuses:
            download_statuses[model_name]["total_bytes"] = total_size
            download_statuses[model_name]["downloaded_bytes"] = downloaded
            
    block_size = 1024 * 1024
    start_time = time.time()
    last_report_time = start_time
    last_report_downloaded = downloaded
    
    mode = 'ab' if downloaded > 0 else 'wb'
    with open(temp_path, mode) as out_file:
        while True:
            with download_lock:
                if model_name in cancelled_downloads:
                    break
            buffer = response.read(block_size)
            if not buffer:
                break
            out_file.write(buffer)
            downloaded += len(buffer)
            
            current_time = time.time()
            if current_time - last_report_time >= 0.5:
                duration = current_time - last_report_time
                bytes_sent = downloaded - last_report_downloaded
                speed_mbps = round((bytes_sent * 8) / (1024 * 1024 * duration), 2)
                progress = round((downloaded / total_size) * 100, 2) if total_size > 0 else 0.0
                
                with download_lock:
                    if model_name in download_statuses:
                        download_statuses[model_name].update({
                            "progress": progress,
                            "downloaded_bytes": downloaded,
                            "speed_mbps": speed_mbps
                        })
                    
                broadcast_event("download_progress", {
                    "model_name": model_name,
                    "progress": progress,
                    "speed_mbps": speed_mbps,
                    "downloaded_bytes": downloaded,
                    "total_bytes": total_size
                })
                
                last_report_time = current_time
                last_report_downloaded = downloaded
                
    with download_lock:
        is_cancelled = model_name in cancelled_downloads
        
    if is_cancelled:
        with download_lock:
            cancelled_downloads.discard(model_name)
            if model_name in download_statuses:
                download_statuses[model_name].update({
                    "status": "cancelled",
                    "error": None
                })
        broadcast_event("download_progress", {
            "model_name": model_name,
            "status": "cancelled",
            "progress": round((downloaded / total_size) * 100, 2) if total_size > 0 else 0.0
        })
        print(f"[Downloader] Cancelled download of {model_name} (saved partial file).")
        return

    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except:
            pass
    os.rename(temp_path, dest_path)
    
    with download_lock:
        if model_name in download_statuses:
            download_statuses[model_name].update({
                "status": "completed",
                "progress": 100.0,
                "downloaded_bytes": total_size,
                "speed_mbps": 0.0
            })
            
    broadcast_event("download_progress", {
        "model_name": model_name,
        "progress": 100.0,
        "speed_mbps": 0.0,
        "downloaded_bytes": total_size,
        "total_bytes": total_size,
        "status": "completed"
    })
    print(f"[Downloader] Completed GGUF single-threaded download of {model_name}")


def download_gguf_parallel(url, dest_path, temp_path, model_name, num_connections=8):
    global download_statuses, cancelled_downloads
    
    req = urllib.request.Request(url, method='HEAD', headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req) as resp:
            total_size = int(resp.headers.get('content-length', 0))
            supports_ranges = total_size > 0
    except Exception as e:
        print(f"[Downloader] HEAD request failed for {url}: {e}")
        supports_ranges = False
        total_size = 0

    if not supports_ranges or total_size < 5 * 1024 * 1024:
        return download_gguf_single_threaded(url, dest_path, temp_path, model_name)

    with download_lock:
        download_statuses[model_name] = {
            "status": "downloading",
            "progress": 0.0,
            "downloaded_bytes": 0,
            "total_bytes": total_size,
            "speed_mbps": 0.0,
            "model_name": model_name,
            "error": None
        }

    downloaded_offset = 0
    if os.path.exists(temp_path):
        try:
            downloaded_offset = os.path.getsize(temp_path)
            if downloaded_offset >= total_size:
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                os.rename(temp_path, dest_path)
                with download_lock:
                    download_statuses[model_name].update({
                        "status": "completed",
                        "progress": 100.0,
                        "downloaded_bytes": total_size
                    })
                return
        except:
            downloaded_offset = 0

    if downloaded_offset == 0:
        try:
            with open(temp_path, "wb") as f:
                f.truncate(total_size)
        except Exception as e:
            raise Exception(f"Failed to pre-allocate temp file: {e}")
    else:
        try:
            with open(temp_path, "r+b") as f:
                f.truncate(total_size)
        except Exception as e:
            print(f"Failed to truncate temp file on resume: {e}")

    remaining_bytes = total_size - downloaded_offset
    chunk_size = remaining_bytes // num_connections
    
    chunks = []
    for i in range(num_connections):
        start = downloaded_offset + i * chunk_size
        end = downloaded_offset + (i + 1) * chunk_size - 1
        if i == num_connections - 1:
            end = total_size - 1
        chunks.append((start, end))

    progress_lock = threading.Lock()
    chunk_downloaded = [0] * num_connections
    thread_exceptions = []
    
    def download_chunk(chunk_idx, start_byte, end_byte):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Range": f"bytes={start_byte}-{end_byte}"
                }
            )
            
            with urllib.request.urlopen(req) as response:
                if response.status not in [200, 206]:
                    raise Exception(f"HTTP Status Code {response.status}")
                
                with open(temp_path, "r+b") as out_file:
                    out_file.seek(start_byte)
                    
                    block_size = 256 * 1024
                    bytes_written = 0
                    total_to_write = end_byte - start_byte + 1
                    
                    while bytes_written < total_to_write:
                        with download_lock:
                            if model_name in cancelled_downloads:
                                return
                        
                        to_read = min(block_size, total_to_write - bytes_written)
                        buffer = response.read(to_read)
                        if not buffer:
                            break
                        
                        out_file.write(buffer)
                        bytes_written += len(buffer)
                        
                        with progress_lock:
                            chunk_downloaded[chunk_idx] = bytes_written
        except Exception as exc:
            print(f"[Downloader] Chunk {chunk_idx} failed: {exc}")
            thread_exceptions.append(exc)

    threads = []
    for idx, (start, end) in enumerate(chunks):
        t = threading.Thread(target=download_chunk, args=(idx, start, end), daemon=True)
        t.start()
        threads.append(t)

    start_time = time.time()
    last_report_time = start_time
    last_total_downloaded = downloaded_offset
    current_downloaded = downloaded_offset
    
    while any(t.is_alive() for t in threads):
        time.sleep(0.5)
        
        with download_lock:
            if model_name in cancelled_downloads:
                break
        
        with progress_lock:
            current_downloaded = downloaded_offset + sum(chunk_downloaded)
            
        current_time = time.time()
        duration = current_time - last_report_time
        if duration >= 0.5:
            bytes_sent = current_downloaded - last_total_downloaded
            speed_mbps = round((bytes_sent * 8) / (1024 * 1024 * duration), 2)
            progress = round((current_downloaded / total_size) * 100, 2) if total_size > 0 else 0.0
            
            with download_lock:
                if model_name in download_statuses:
                    download_statuses[model_name].update({
                        "progress": progress,
                        "downloaded_bytes": current_downloaded,
                        "speed_mbps": speed_mbps
                    })
            
            broadcast_event("download_progress", {
                "model_name": model_name,
                "progress": progress,
                "speed_mbps": speed_mbps,
                "downloaded_bytes": current_downloaded,
                "total_bytes": total_size
            })
            
            last_report_time = current_time
            last_total_downloaded = current_downloaded

    for t in threads:
        t.join()

    with download_lock:
        is_cancelled = model_name in cancelled_downloads

    if is_cancelled:
        with download_lock:
            cancelled_downloads.discard(model_name)
            if model_name in download_statuses:
                download_statuses[model_name].update({
                    "status": "cancelled",
                    "error": None
                })
        broadcast_event("download_progress", {
            "model_name": model_name,
            "status": "cancelled",
            "progress": round((current_downloaded / total_size) * 100, 2) if total_size > 0 else 0.0
        })
        print(f"[Downloader] Cancelled download of {model_name} (saved partial file).")
        return

    if thread_exceptions:
        raise Exception(f"Download threads failed: {thread_exceptions[0]}")

    final_size = os.path.getsize(temp_path)
    if final_size != total_size:
        raise Exception(f"File size mismatch: got {final_size} bytes, expected {total_size} bytes")

    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except:
            pass
    os.rename(temp_path, dest_path)
    
    with download_lock:
        if model_name in download_statuses:
            download_statuses[model_name].update({
                "status": "completed",
                "progress": 100.0,
                "downloaded_bytes": total_size,
                "speed_mbps": 0.0
            })
            
    broadcast_event("download_progress", {
        "model_name": model_name,
        "progress": 100.0,
        "speed_mbps": 0.0,
        "downloaded_bytes": total_size,
        "total_bytes": total_size,
        "status": "completed"
    })
    print(f"[Downloader] Completed parallel download of {model_name}")


def run_download_thread(model_name: str):
    global download_statuses
    
    hf_repos = {
        "whisperx:tiny": "Systran/faster-whisper-tiny",
        "whisperx:base": "Systran/faster-whisper-base",
        "whisperx:small": "Systran/faster-whisper-small",
        "whisperx:medium": "Systran/faster-whisper-medium",
        "whisperx:large-v3": "Systran/faster-whisper-large-v3",
        "tts:qwen": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    }

    if model_name in hf_repos:
        repo_id = hf_repos[model_name]
        try:
            with download_lock:
                download_statuses[model_name] = {
                    "status": "downloading",
                    "progress": 0.0,
                    "downloaded_bytes": 0,
                    "total_bytes": 0,
                    "speed_mbps": 0.0,
                    "model_name": model_name,
                    "error": None
                }
            
            print(f"[Downloader] Starting HF download for {repo_id}")
            
            from huggingface_hub import HfApi
            api = HfApi()
            repo_info = api.model_info(repo_id)
            commit_hash = repo_info.sha
            
            files = api.list_repo_tree(repo_id, recursive=True)
            hf_total_bytes = sum(getattr(f, "size", 0) or 0 for f in files if getattr(f, "size", None) is not None)
            
            cache_dir = os.path.expanduser(os.path.join("~", ".cache", "huggingface", "hub"))
            repo_folder = "models--" + repo_id.replace("/", "--")
            local_dir_path = os.path.join(cache_dir, repo_folder, "snapshots", commit_hash)
            os.makedirs(local_dir_path, exist_ok=True)
            
            with download_lock:
                download_statuses[model_name]["total_bytes"] = hf_total_bytes
                
            import sys
            import huggingface_hub.utils
            import huggingface_hub.utils.tqdm
            
            tqdm_module = sys.modules['huggingface_hub.utils.tqdm']
            original_tqdm = tqdm_module.tqdm
            
            hf_download_bytes = 0
            hf_start_time = time.time()
            
            class ProgressTqdm(original_tqdm):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    
                def update(self, n=1):
                    with download_lock:
                        if model_name in cancelled_downloads:
                            raise Exception("Download cancelled by user")
                    super().update(n)
                    nonlocal hf_download_bytes
                    hf_download_bytes += n
                    
                    progress = round((hf_download_bytes / hf_total_bytes) * 100, 2) if hf_total_bytes > 0 else 0.0
                    current_time = time.time()
                    duration = current_time - hf_start_time
                    speed_mbps = round((hf_download_bytes * 8) / (1024 * 1024 * duration), 2) if duration > 0 else 0.0
                    
                    with download_lock:
                        if model_name in download_statuses:
                            download_statuses[model_name].update({
                                "progress": progress,
                                "downloaded_bytes": hf_download_bytes,
                                "speed_mbps": speed_mbps
                            })
                        
                    broadcast_event("download_progress", {
                        "model_name": model_name,
                        "progress": progress,
                        "speed_mbps": speed_mbps,
                        "downloaded_bytes": hf_download_bytes,
                        "total_bytes": hf_total_bytes
                    })
            
            tqdm_module.tqdm = ProgressTqdm
            if hasattr(huggingface_hub.utils, 'tqdm'):
                huggingface_hub.utils.tqdm = ProgressTqdm
            
            from huggingface_hub import snapshot_download
            snapshot_download(
                repo_id=repo_id,
                local_dir=local_dir_path,
                local_dir_use_symlinks=False,
                max_workers=8
            )
            
            tqdm_module.tqdm = original_tqdm
            if hasattr(huggingface_hub.utils, 'tqdm'):
                huggingface_hub.utils.tqdm = original_tqdm
            
            complete_marker = os.path.join(local_dir_path, "download_complete.json")
            try:
                with open(complete_marker, "w") as f:
                    json.dump({"completed_at": time.time(), "total_bytes": hf_total_bytes}, f)
            except Exception as marker_err:
                print(f"[Downloader] Error writing marker file: {marker_err}")

            with download_lock:
                if model_name in download_statuses:
                    download_statuses[model_name].update({
                        "status": "completed",
                        "progress": 100.0,
                        "downloaded_bytes": hf_total_bytes,
                        "speed_mbps": 0.0
                    })
                
            broadcast_event("download_progress", {
                "model_name": model_name,
                "progress": 100.0,
                "speed_mbps": 0.0,
                "downloaded_bytes": hf_total_bytes,
                "total_bytes": hf_total_bytes,
                "status": "completed"
            })
            print(f"[Downloader] Completed HF download of {model_name}")
            return
            
        except Exception as e:
            try:
                tqdm_module.tqdm = original_tqdm
                if hasattr(huggingface_hub.utils, 'tqdm'):
                    huggingface_hub.utils.tqdm = original_tqdm
            except:
                pass
                
            with download_lock:
                is_cancelled = model_name in cancelled_downloads
                
            if is_cancelled:
                with download_lock:
                    cancelled_downloads.discard(model_name)
                    if model_name in download_statuses:
                        download_statuses[model_name].update({
                            "status": "cancelled",
                            "error": None
                        })
                broadcast_event("download_progress", {
                    "model_name": model_name,
                    "status": "cancelled"
                })
                print(f"[Downloader] HF Download cancelled (saved partial files) for {model_name}")
                return
                
            print(f"[Downloader] Error downloading HF model {model_name}: {e}")
            with download_lock:
                if model_name in download_statuses:
                    download_statuses[model_name].update({
                        "status": "error",
                        "error": str(e)
                    })
            broadcast_event("download_progress", {
                "model_name": model_name,
                "status": "error",
                "error": str(e)
            })
            return

    if model_name not in DOWNLOAD_URLS:
        with download_lock:
            download_statuses[model_name] = {
                "status": "error",
                "error": f"Model {model_name} is not one of the incorporated models.",
                "progress": 0.0,
                "downloaded_bytes": 0,
                "total_bytes": 0,
                "speed_mbps": 0.0,
                "model_name": model_name
            }
        return

    info = DOWNLOAD_URLS[model_name]
    url = info["url"]
    dest_path = info["path"]
    
    dest_dir = os.path.dirname(dest_path)
    if dest_dir and not os.path.exists(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)
        
    temp_path = dest_path + ".download"
    
    try:
        download_gguf_parallel(url, dest_path, temp_path, model_name, num_connections=8)
    except Exception as e:
        print(f"[Downloader] Error downloading {model_name}: {e}")
        with download_lock:
            if model_name in download_statuses:
                download_statuses[model_name].update({
                    "status": "error",
                    "error": str(e)
                })
        broadcast_event("download_progress", {
            "model_name": model_name,
            "status": "error",
            "error": str(e)
        })



@app.post("/api/models/download")
def start_model_download(payload: ModelDownloadPayload, background_tasks: BackgroundTasks):
    model_name = payload.model_name
    restart = payload.restart
    with download_lock:
        if model_name in download_statuses and download_statuses[model_name]["status"] == "downloading":
            raise HTTPException(status_code=400, detail=f"Download for {model_name} is already in progress.")
        
        # If restart is requested, delete any partial download files or folders first
        if restart:
            if model_name in DOWNLOAD_URLS:
                info = DOWNLOAD_URLS[model_name]
                temp_path = info["path"] + ".download"
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                        print(f"[Downloader] Removed partial file for restart: {temp_path}")
                    except Exception as e:
                        print(f"Failed to remove partial download file: {e}")
            hf_repos = {
                "whisperx:tiny": "Systran/faster-whisper-tiny",
                "whisperx:base": "Systran/faster-whisper-base",
                "whisperx:small": "Systran/faster-whisper-small",
                "whisperx:medium": "Systran/faster-whisper-medium",
                "whisperx:large-v3": "Systran/faster-whisper-large-v3",
                "tts:qwen": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
            }
            if model_name in hf_repos:
                repo_id = hf_repos[model_name]
                cache_dir = os.path.expanduser(os.path.join("~", ".cache", "huggingface", "hub"))
                repo_folder = "models--" + repo_id.replace("/", "--")
                repo_path = os.path.join(cache_dir, repo_folder)
                if os.path.exists(repo_path):
                    import shutil
                    try:
                        shutil.rmtree(repo_path)
                        print(f"[Downloader] Removed partial HF folder for restart: {repo_path}")
                    except Exception as e:
                        print(f"Failed to remove HF partial download folder: {e}")
                        
        # Initialize status for this model so that it immediately registers as downloading
        download_statuses[model_name] = {
            "status": "downloading",
            "progress": 0.0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed_mbps": 0.0,
            "model_name": model_name,
            "error": None
        }
    background_tasks.add_task(run_download_thread, model_name)
    return {"status": "started"}

@app.get("/api/models/download/status")
def get_model_download_status():
    global download_statuses
    with download_lock:
        return download_statuses

@app.post("/api/models/download/cancel")
def cancel_model_download(payload: ModelDownloadPayload):
    model_name = payload.model_name
    global cancelled_downloads, download_statuses
    with download_lock:
        if model_name in download_statuses and download_statuses[model_name]["status"] == "downloading":
            cancelled_downloads.add(model_name)
            download_statuses[model_name]["status"] = "cancelled"
            return {"status": "cancelling"}
        else:
            return {"status": "not_downloading"}


_hf_download_cache = {}
_hf_cache_time = 0.0

def get_hf_repo_status(repo_id: str) -> dict:
    global _hf_cache_time
    now = time.time()
    
    cache_key = f"status_{repo_id}"
    if cache_key in _hf_download_cache and (now - _hf_cache_time) < 2.0:
        return _hf_download_cache[cache_key]
        
    try:
        import os
        cache_dir = os.path.expanduser(os.path.join("~", ".cache", "huggingface", "hub"))
        repo_folder = "models--" + repo_id.replace("/", "--")
        repo_path = os.path.join(cache_dir, repo_folder)
        
        if not os.path.exists(repo_path):
            res = {"downloaded": False, "partial": False}
            _hf_download_cache[cache_key] = res
            _hf_cache_time = now
            return res
            
        snapshots_path = os.path.join(repo_path, "snapshots")
        if not os.path.exists(snapshots_path) or not os.listdir(snapshots_path):
            res = {"downloaded": False, "partial": False}
            _hf_download_cache[cache_key] = res
            _hf_cache_time = now
            return res
            
        for snap in os.listdir(snapshots_path):
            snap_dir = os.path.join(snapshots_path, snap)
            if os.path.isdir(snap_dir):
                marker = os.path.join(snap_dir, "download_complete.json")
                if os.path.exists(marker):
                    res = {"downloaded": True, "partial": False}
                    _hf_download_cache[cache_key] = res
                    _hf_cache_time = now
                    return res
                    
        has_incomplete = False
        has_weights = False
        total_size = 0
        for root, dirs, files in os.walk(repo_path):
            for file in files:
                if file.endswith(".incomplete"):
                    has_incomplete = True
                if file in ["model.bin", "model.safetensors"]:
                    has_weights = True
                total_size += os.path.getsize(os.path.join(root, file))
        
        if not has_incomplete and has_weights and total_size > 50 * 1024 * 1024:
            for snap in os.listdir(snapshots_path):
                snap_dir = os.path.join(snapshots_path, snap)
                if os.path.isdir(snap_dir):
                    marker = os.path.join(snap_dir, "download_complete.json")
                    try:
                        with open(marker, "w") as f:
                            json.dump({"completed_at": time.time(), "total_bytes": total_size}, f)
                    except:
                        pass
                    break
            res = {"downloaded": True, "partial": False}
        else:
            has_files = any(any(not f.endswith(".lock") for f in files) for root, dirs, files in os.walk(repo_path))
            res = {"downloaded": False, "partial": has_files}
            
        _hf_download_cache[cache_key] = res
        _hf_cache_time = now
        return res
    except Exception:
        pass
    return {"downloaded": False, "partial": False}

def is_hf_repo_downloaded(repo_id: str) -> bool:
    return get_hf_repo_status(repo_id)["downloaded"]

@app.get("/api/models")
def get_models():
    models_dir = "models"
    drafters_dir = os.path.join(models_dir, "drafters")
    mmproj_dir = os.path.join(models_dir, "mmproj")
    
    def get_existing_files(directory):
        files = {}
        if os.path.exists(directory):
            for f in os.listdir(directory):
                filepath = os.path.join(directory, f)
                if os.path.isfile(filepath):
                    if f.endswith(".gguf"):
                        try:
                            size_gb = round(os.path.getsize(filepath) / (1024**3), 2)
                        except:
                            size_gb = 0.0
                        files[f] = {"name": f, "size_gb": size_gb, "downloaded": True, "partial": False}
                    elif f.endswith(".gguf.download"):
                        orig_name = f[:-9]
                        try:
                            size_bytes = os.path.getsize(filepath)
                            size_gb = round(size_bytes / (1024**3), 2)
                        except:
                            size_bytes = 0
                            size_gb = 0.0
                        files[orig_name] = {"name": orig_name, "size_gb": size_gb, "downloaded": False, "partial": True}
        return files

    existing_main = get_existing_files(models_dir)
    existing_drafters = get_existing_files(drafters_dir)
    existing_mmproj = get_existing_files(mmproj_dir)
    
    incorporated = {
        "main": [
            {"name": "Qwen3.5-4B-Q4_K_M.gguf", "size_gb": 2.55, "downloaded": False, "partial": False},
            {"name": "Qwen3VL-2B-Instruct-Q4_K_M.gguf", "size_gb": 1.03, "downloaded": False, "partial": False}
        ],
        "drafters": [
            {"name": "Qwen3.5-0.8B-Q4_K_M.gguf", "size_gb": 0.50, "downloaded": False, "partial": False}
        ],
        "mmproj": [
            {"name": "mmproj-Qwen3.5-4B-BF16.gguf", "size_gb": 0.63, "downloaded": False, "partial": False},
            {"name": "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf", "size_gb": 0.41, "downloaded": False, "partial": False}
        ]
    }
    
    final_main = []
    final_drafters = []
    final_mmproj = []
    
    for model in incorporated["main"]:
        if model["name"] in existing_main:
            model["downloaded"] = existing_main[model["name"]]["downloaded"]
            model["partial"] = existing_main[model["name"]].get("partial", False)
            model["size_gb"] = existing_main[model["name"]]["size_gb"]
            del existing_main[model["name"]]
        final_main.append(model)
    for model_name, model_info in existing_main.items():
        final_main.append(model_info)
        
    for model in incorporated["drafters"]:
        if model["name"] in existing_drafters:
            model["downloaded"] = existing_drafters[model["name"]]["downloaded"]
            model["partial"] = existing_drafters[model["name"]].get("partial", False)
            model["size_gb"] = existing_drafters[model["name"]]["size_gb"]
            del existing_drafters[model["name"]]
        final_drafters.append(model)
    for model_name, model_info in existing_drafters.items():
        final_drafters.append(model_info)
        
    for model in incorporated["mmproj"]:
        if model["name"] in existing_mmproj:
            model["downloaded"] = existing_mmproj[model["name"]]["downloaded"]
            model["partial"] = existing_mmproj[model["name"]].get("partial", False)
            model["size_gb"] = existing_mmproj[model["name"]]["size_gb"]
            del existing_mmproj[model["name"]]
        final_mmproj.append(model)
    for model_name, model_info in existing_mmproj.items():
        final_mmproj.append(model_info)
        
    def get_hf_model_info(name, repo_id, expected_gb):
        status = get_hf_repo_status(repo_id)
        return {
            "name": name,
            "size_gb": expected_gb,
            "downloaded": status["downloaded"],
            "partial": status["partial"]
        }

    stt_models = [
        get_hf_model_info("whisperx:tiny", "Systran/faster-whisper-tiny", 0.1),
        get_hf_model_info("whisperx:base", "Systran/faster-whisper-base", 0.25),
        get_hf_model_info("whisperx:small", "Systran/faster-whisper-small", 0.50),
        get_hf_model_info("whisperx:medium", "Systran/faster-whisper-medium", 1.5),
        get_hf_model_info("whisperx:large-v3", "Systran/faster-whisper-large-v3", 3.0)
    ]
    
    tts_models = [
        get_hf_model_info("tts:qwen", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice", 1.2)
    ]
    
    s_dict = load_settings_dict()
    llama_opts = s_dict.get("llama", {})
    
    current_main = llama_opts.get("MAIN_MODEL_FILE", "Qwen3.5-4B-Q4_K_M.gguf")
    current_draft = llama_opts.get("DRAFT_MODEL_FILE", "Qwen3.5-0.8B-Q4_K_M.gguf")
    current_mmproj = llama_opts.get("MMPROJ_MODEL_FILE", "mmproj-Qwen3.5-4B-BF16.gguf")
    
    return {
        "models": {
            "main": final_main,
            "drafters": final_drafters,
            "mmproj": final_mmproj,
            "stt": stt_models,
            "tts": tts_models
        },
        "selected": {
            "main_model": current_main,
            "draft_model": current_draft,
            "mmproj_model": current_mmproj
        }
    }


@app.post("/api/setup")
def start_setup(payload: SetupPayload, background_tasks: BackgroundTasks):
    global is_setting_up
    if is_setting_up:
        raise HTTPException(status_code=400, detail="Setup already in progress.")
    background_tasks.add_task(run_setup_worker, payload)
    return {"status": "setup_started"}

@app.get("/api/setup/status")
def get_setup_status():
    global setup_progress
    return setup_progress

@app.post("/api/chat")
def post_chat(payload: ChatPayload, background_tasks: BackgroundTasks):
    global duplex_manager, active_session_id
    if not duplex_manager:
        raise HTTPException(status_code=400, detail="Duplex Manager not loaded. Please complete model setup first.")
    
    target_session_id = payload.session_id or active_session_id
    if not target_session_id:
        sessions = load_sessions_list()
        if sessions:
            target_session_id = sessions[0].get("id")
        else:
            target_session_id = f"session_{int(time.time()*1000)}"
            
    # Broadcast user's message to UI chat sessions
    msg_id = payload.msg_id or f"msg_{int(time.time()*1000)}"
    
    attachments_dict = []
    if payload.attachments:
        attachments_dict = [att.dict() for att in payload.attachments]
    elif payload.image:
        attachments_dict = [{"name": "image.png", "type": "image", "data": payload.image}]
        
    # Strip heavy file payloads before broadcasting over SSE to prevent UI freezes
    broadcast_attachments = []
    for att in attachments_dict:
        broadcast_attachments.append({
            "name": att.get("name"),
            "type": att.get("type"),
            "data": None
        })

    broadcast_event("chat_message", {
        "sender": "user", 
        "text": payload.message, 
        "image": payload.image,
        "attachments": broadcast_attachments,
        "type": "text", 
        "id": msg_id,
        "session_id": target_session_id
    })
    
    append_message_to_sessions(target_session_id, "user", payload.message, msg_id, attachments_dict)
    
    # Run pipeline in background thread
    background_tasks.add_task(
        run_chat_pipeline_helper, 
        payload.message, 
        payload.image, 
        payload.speech_enabled,
        target_session_id,
        attachments_dict
    )
    return {"status": "message_received", "msg_id": msg_id}

@app.post("/api/chat/interrupt")
def post_interrupt():
    global duplex_manager
    if duplex_manager:
        duplex_manager.interrupt()
        broadcast_log("SYSTEM", "User triggered audio playback interruption.")
        broadcast_event("playback_interrupted", {})
        return {"status": "interrupted"}
    return {"status": "no_duplex_manager"}

@app.get("/api/resources")
def get_resources():
    global stt_engine, tts_engine, duplex_manager, is_remote_control_only
    if cached_resources.get("vram", {}).get("total", 0.0) == 0.0:
        try:
            update_resource_stats_once()
        except:
            pass

    context_turns = 0
    if duplex_manager:
        with duplex_manager.history_lock:
            context_turns = sum(1 for m in duplex_manager.history if m.get("role") == "user")
            
    res = dict(cached_resources)
    res["context_turns"] = context_turns
    res["stt_loaded"] = stt_engine is not None
    res["tts_loaded"] = tts_engine is not None
    res["models_loaded"] = (duplex_manager is not None) or is_remote_control_only
    return res

@app.get("/api/config")
def get_config():
    s_dict = load_settings_dict()
    
    # Pack up config settings with defaults
    return {
        "audio": {
            "sample_rate": s_dict.get("audio", {}).get("sample_rate", audio_cfg.sample_rate),
            "frame_duration_ms": s_dict.get("audio", {}).get("frame_duration_ms", audio_cfg.frame_duration_ms),
            "vad_aggressiveness": s_dict.get("audio", {}).get("vad_aggressiveness", audio_cfg.vad_aggressiveness),
            "min_speech_duration": s_dict.get("audio", {}).get("min_speech_duration", audio_cfg.min_speech_duration),
            "max_speech_duration": s_dict.get("audio", {}).get("max_speech_duration", audio_cfg.max_speech_duration),
        },
        "model": {
            "stt_model_size": s_dict.get("model", {}).get("stt_model_size", model_cfg.stt_model_size),
            "stt_device": s_dict.get("model", {}).get("stt_device", model_cfg.stt_device),
            "stt_compute_type": s_dict.get("model", {}).get("stt_compute_type", model_cfg.stt_compute_type),
            "stt_batch_size": s_dict.get("model", {}).get("stt_batch_size", model_cfg.stt_batch_size),
            "align_words": s_dict.get("model", {}).get("align_words", model_cfg.align_words),
            "max_history_len": s_dict.get("model", {}).get("max_history_len", model_cfg.max_history_len),
            "max_tool_output_len": s_dict.get("model", {}).get("max_tool_output_len", model_cfg.max_tool_output_len),
            "max_estimated_tokens": s_dict.get("model", {}).get("max_estimated_tokens", model_cfg.max_estimated_tokens),
            "max_output_tokens": s_dict.get("model", {}).get("max_output_tokens", model_cfg.max_output_tokens),
            "tts_repo_id": s_dict.get("model", {}).get("tts_repo_id", model_cfg.tts_repo_id),
            "tts_device": s_dict.get("model", {}).get("tts_device", model_cfg.tts_device),
        },
        "llama": {
            "SERVER_HOST": s_dict.get("llama", {}).get("SERVER_HOST", "127.0.0.1"),
            "SERVER_PORT": s_dict.get("llama", {}).get("SERVER_PORT", 8080),
            "SERVER_TIMEOUT": s_dict.get("llama", {}).get("SERVER_TIMEOUT", 60),
            "context_size": s_dict.get("llama", {}).get("context_size", 50000),
            "ngl": s_dict.get("llama", {}).get("ngl", -1),
            "flash_attn": s_dict.get("llama", {}).get("flash_attn", "on"),
            "cache_type_k": s_dict.get("llama", {}).get("cache_type_k", "q4_0"),
            "cache_type_v": s_dict.get("llama", {}).get("cache_type_v", "q4_0"),
            "spec_draft_n_max": s_dict.get("llama", {}).get("spec_draft_n_max", 16),
        }
    }

@app.post("/api/config")
def save_config(new_config: dict):
    # Determine if reload is required
    old_config = get_config()
    reload_reasons = []
    
    # Check llama changes
    for k, v in new_config.get("llama", {}).items():
        if old_config.get("llama", {}).get(k) != v:
            reload_reasons.append(f"Llama Server Parameter: {k}")
            
    # Check key models
    for k in ["tts_repo_id", "tts_device", "stt_model_size", "stt_device", "stt_compute_type"]:
        if new_config.get("model", {}).get(k) != old_config.get("model", {}).get(k):
            reload_reasons.append(f"Model Parameter: {k}")
            
    # Check audio parameters
    for k in ["sample_rate", "frame_duration_ms", "vad_aggressiveness"]:
        if new_config.get("audio", {}).get(k) != old_config.get("audio", {}).get(k):
            reload_reasons.append(f"Audio Stream Parameter: {k}")
            
    # Save settings to file
    save_settings_dict(new_config)
    
    # Reload in memory configuration attributes (for settings that don't need process restart)
    from config.settings import model_cfg, audio_cfg
    for k, v in new_config.get("model", {}).items():
        if hasattr(model_cfg, k):
            setattr(model_cfg, k, v)
    for k, v in new_config.get("audio", {}).items():
        if hasattr(audio_cfg, k):
            setattr(audio_cfg, k, v)
            
    return {
        "status": "config_saved",
        "reload_required": len(reload_reasons) > 0,
        "reload_reasons": reload_reasons
    }

@app.get("/api/logs/all")
def get_all_logs():
    return list(log_queue.queue)

def run_unload_worker():
    stop_all_components()
    global stt_engine, tts_engine, duplex_manager, llm_client, setup_progress, is_remote_control_only
    stt_engine = None
    tts_engine = None
    duplex_manager = None
    llm_client = None
    setup_progress = {"status": "Not started", "progress": 0, "error": None, "cause": None}
    is_remote_control_only = False
    import gc
    import torch
    if torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
        except:
            pass
    gc.collect()
    broadcast_log("SYSTEM", "All models unloaded successfully.")

@app.post("/api/unload")
def unload_models():
    run_unload_worker()
    return {"status": "unloaded"}

@app.post("/api/chat/compress")
def post_compress():
    global duplex_manager
    if not duplex_manager:
        raise HTTPException(status_code=400, detail="Duplex Manager not loaded.")
    
    with duplex_manager.history_lock:
        # Compress tool outputs in history
        for msg in duplex_manager.history:
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                if len(msg["content"]) > 100:
                    msg["content"] = msg["content"][:100] + "\n...[Content compressed]"
            elif msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                pass
        
        # Keep only the last 4 turns if history is too long
        if len(duplex_manager.history) > 8:
            duplex_manager.history = duplex_manager.history[-8:]
            
    if active_session_id:
        sync_session_history_to_persistence(active_session_id, prune_ui_messages=True)
            
    import gc
    import torch
    if torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
        except:
            pass
    gc.collect()

    broadcast_log("SYSTEM", "Context compression executed successfully.")
    context_turns = sum(1 for m in duplex_manager.history if m.get("role") == "user")
    return {"status": "compressed", "context_turns": context_turns}


@app.post("/api/voice")
def set_voice(payload: dict):
    speaker = payload.get("speaker", "Aiden")
    s_dict = load_settings_dict()
    if "model" not in s_dict:
        s_dict["model"] = {}
    s_dict["model"]["tts_speaker"] = speaker
    save_settings_dict(s_dict)
    
    # Update in memory config
    from config.settings import model_cfg
    model_cfg.tts_speaker = speaker
    broadcast_log("SYSTEM", f"Text-to-Speech voice speaker changed to: {speaker}")
    return {"status": "voice_changed"}

@app.post("/api/voice/mute")
def post_voice_mute(payload: dict):
    global voice_input_muted
    voice_input_muted = payload.get("muted", False)
    broadcast_log("SYSTEM", f"Voice loop muted: {voice_input_muted}")
    return {"status": "success", "muted": voice_input_muted}

class SpeakPayload(BaseModel):
    text: str

@app.post("/api/voice/speak")
def post_voice_speak(payload: SpeakPayload, background_tasks: BackgroundTasks):
    global duplex_manager
    if duplex_manager and duplex_manager.tts is not None:
        def speak_task():
            try:
                # Interrupt current speech
                duplex_manager.interrupt()
                time.sleep(0.05)
                
                import uuid
                req_id = str(uuid.uuid4())
                duplex_manager.current_request_id = req_id
                duplex_manager.interrupt_event.clear()
                
                from config.settings import model_cfg
                speaker = getattr(model_cfg, "tts_speaker", "Aiden")
                language = "English"
                if speaker in ["Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric"]:
                    language = "Chinese"
                elif speaker == "Ono_Anna":
                    language = "Japanese"
                elif speaker == "Sohee":
                    language = "Korean"
                
                from src.llm.prompts import BUTLER_INSTRUCTION
                wavs, sr = duplex_manager.tts.generate_custom_voice(
                    text=payload.text,
                    language=language,
                    speaker=speaker,
                    instruct=BUTLER_INSTRUCTION
                )
                duplex_manager.audio_queue.put((wavs[0], sr, 0, req_id))
            except Exception as e:
                print(f"[On-Demand TTS Error]: {e}")
                
        background_tasks.add_task(speak_task)
        return {"status": "speaking"}
    return {"status": "no_tts"}

class SessionSwitchPayload(BaseModel):
    session_id: str

class SessionClearPayload(BaseModel):
    session_id: str

@app.get("/api/sessions")
def get_sessions(client: str = "remote"):
    sessions = load_sessions_list()
    global active_session_id
    if sessions and not active_session_id:
        active_session_id = sessions[0].get("id")
    return sessions

@app.post("/api/sessions")
def save_sessions(payload: List[dict]):
    global session_histories, active_session_id
    with chat_pipeline_lock:
        save_sessions_list(payload)
        
        # Clean and rebuild session_histories from payload to prevent leaks and corruption
        new_histories = {}
        for s in payload:
            s_id = s.get("id")
            if s_id:
                h = []
                for m in s.get("messages", []):
                    h.append({
                        "role": "user" if m.get("sender") == "user" else "assistant",
                        "content": m.get("text", "")
                    })
                new_histories[s_id] = h
        session_histories = new_histories
        
        # Synchronize active_session_id only if it is not currently set
        if payload and not active_session_id:
            active_session_id = payload[0].get("id")
            
        # Re-sync duplex history if active
        if active_session_id and duplex_manager:
            duplex_manager.history = session_histories.get(active_session_id, [])
            
    broadcast_event("sessions_updated", {})
    return {"status": "sessions_saved"}

@app.post("/api/session/switch")
def post_session_switch(payload: SessionSwitchPayload):
    global active_session_id, duplex_manager, session_histories
    active_session_id = payload.session_id
    if duplex_manager:
        with duplex_manager.history_lock:
            duplex_manager.history = session_histories.get(active_session_id, [])
    broadcast_log("SYSTEM", f"Switched active session reference to: {active_session_id}")
    broadcast_event("session_switch", {"session_id": active_session_id})
    return {"status": "switched", "session_id": active_session_id}


@app.post("/api/session/clear")
def post_session_clear(payload: SessionClearPayload):
    global duplex_manager, session_histories
    session_id = payload.session_id
    with chat_pipeline_lock:
        session_histories[session_id] = []
        if duplex_manager and duplex_manager.history is session_histories.get(session_id):
            duplex_manager.history = []
    broadcast_log("SYSTEM", f"Cleared backend context for session: {session_id}")
    broadcast_event("session_clear", {"session_id": session_id})
    return {"status": "cleared", "session_id": session_id}

@app.post("/api/tools")
def save_enabled_tools(payload: dict):
    enabled_tools = payload.get("enabled_tools", {})
    s_dict = load_settings_dict()
    s_dict["enabled_tools"] = enabled_tools
    save_settings_dict(s_dict)
    broadcast_log("SYSTEM", "AI Agent tools visibility configuration updated.")
    return {"status": "tools_saved"}

@app.get("/api/tools")
def get_enabled_tools():
    s_dict = load_settings_dict()
    return {"enabled_tools": s_dict.get("enabled_tools", {})}

class EmailPayload(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    recipient: str
    subject: str
    body: str

@app.post("/api/share/email")
def send_share_email(payload: EmailPayload):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    try:
        msg = MIMEMultipart()
        msg['From'] = payload.smtp_user
        msg['To'] = payload.recipient
        msg['Subject'] = payload.subject
        msg.attach(MIMEText(payload.body, 'html'))
        
        if payload.smtp_port == 465:
            server = smtplib.SMTP_SSL(payload.smtp_host, payload.smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(payload.smtp_host, payload.smtp_port, timeout=10)
            server.starttls()
            
        server.login(payload.smtp_user, payload.smtp_pass)
        server.sendmail(payload.smtp_user, payload.recipient, msg.as_string())
        server.quit()
        
        return {"status": "email_sent"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events")
async def events_endpoint(request: Request):
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()
    
    async def event_generator():
        q = asyncio.Queue()
        active_sse_queues.append(q)
        
        # Stream historical logs on connect
        logs = list(log_queue.queue)
        for log_line in logs:
            payload = {"type": "log", "data": {"line": log_line}, "timestamp": time.time()}
            yield f"data: {json.dumps(payload)}\n\n"
            
        try:
            while True:
                # Keepalive ping
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield data
                except asyncio.TimeoutError:
                    yield "data: {\"type\":\"ping\"}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            active_sse_queues.remove(q)
            
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)

# --- REMOTE CONTROL ENDPOINTS ---

from src.utils import remote_control

def check_remote_control_allowed(request: Optional[Request] = None):
    if request:
        host = request.client.host if request.client else None
        host_header = request.headers.get("host", "")
        origin_header = request.headers.get("origin", "")
        referer_header = request.headers.get("referer", "")
        
        is_local = (
            not host
            or host in ["127.0.0.1", "localhost", "::1"]
            or "127.0.0.1" in host_header
            or "localhost" in host_header
            or "127.0.0.1" in origin_header
            or "localhost" in origin_header
            or "127.0.0.1" in referer_header
            or "localhost" in referer_header
        )
        if is_local:
            return
    s_dict = load_settings_dict()
    if not s_dict.get("sharing", {}).get("remote_control_enabled", False):
        raise HTTPException(status_code=403, detail="Remote control is disabled by the administrator.")

class RemoteDownloadPayload(BaseModel):
    paths: List[str]


class ScreenActionPayload(BaseModel):
    action: str  # click, double_click, right_click, drag, type, press_key, move
    x: Optional[float] = 0.0
    y: Optional[float] = 0.0
    drag_to_x: Optional[float] = None
    drag_to_y: Optional[float] = None
    text: Optional[str] = None
    key: Optional[str] = None

@app.get("/api/remote-control/files/list")
def api_list_files(request: Request, path: Optional[str] = None):
    check_remote_control_allowed(request)
    try:
        decoded_path = path
        if path:
            import urllib.parse
            decoded_path = urllib.parse.unquote(path)
        return remote_control.list_directory(decoded_path)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except FileNotFoundError as fnfe:
        raise HTTPException(status_code=404, detail=str(fnfe))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/remote-control/files/desktop")
def api_get_desktop_path(request: Request):
    check_remote_control_allowed(request)
    try:
        desktop = None
        if sys.platform == "win32":
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
                val, _ = winreg.QueryValueEx(key, "Desktop")
                desktop = os.path.expandvars(val)
            except Exception:
                pass
        
        if not desktop or not os.path.exists(desktop):
            onedrive_desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
            if os.path.exists(onedrive_desktop):
                desktop = onedrive_desktop
            else:
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                
        if not os.path.exists(desktop):
            desktop = os.path.expanduser("~")
            
        return {"desktop_path": os.path.abspath(desktop)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/remote-control/files/download")
def api_download_files(request: Request, payload: RemoteDownloadPayload, background_tasks: BackgroundTasks):

    check_remote_control_allowed(request)
    if not payload.paths:
        raise HTTPException(status_code=400, detail="No files selected for download.")
    
    if len(payload.paths) == 1:
        single_path = os.path.abspath(payload.paths[0])
        if os.path.exists(single_path):
            if os.path.isfile(single_path):
                filename = os.path.basename(single_path)
                return FileResponse(
                    single_path, 
                    filename=filename, 
                    media_type="application/octet-stream"
                )
            elif os.path.isdir(single_path):
                pass
            else:
                raise HTTPException(status_code=400, detail="Path is not a regular file or directory.")
        else:
            raise HTTPException(status_code=404, detail=f"File not found: {payload.paths[0]}")
            
    try:
        zip_path = remote_control.create_zip_archive(payload.paths)
        if not os.path.exists(zip_path):
            raise HTTPException(status_code=500, detail="Failed to create zip archive.")
            
        background_tasks.add_task(os.remove, zip_path)
        
        filename = f"adam_transfer_{int(time.time())}.zip"
        return FileResponse(
            zip_path, 
            filename=filename, 
            media_type="application/zip"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Archive generation error: {str(e)}")

@app.get("/api/remote-control/screen/screenshot")
def api_screenshot(request: Request, quality: int = 75):
    check_remote_control_allowed(request)
    try:
        import io
        img_bytes = remote_control.capture_screenshot(quality=quality)
        return StreamingResponse(io.BytesIO(img_bytes), media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/remote-control/screen/action")
def api_screen_action(request: Request, payload: ScreenActionPayload):
    check_remote_control_allowed(request)
    try:
        success = False
        if payload.action in ["click", "double_click", "right_click", "drag", "move"]:
            success = remote_control.execute_mouse_action(
                payload.action,
                payload.x,
                payload.y,
                payload.drag_to_x,
                payload.drag_to_y
            )
        elif payload.action == "type":
            # Always left click first on the chosen spot
            if payload.x is not None and payload.y is not None:
                remote_control.execute_mouse_action("left_click", payload.x, payload.y)
                time.sleep(0.15)
            success = remote_control.execute_keyboard_action(
                payload.action,
                payload.text,
                payload.key
            )
        elif payload.action == "press_key":
            success = remote_control.execute_keyboard_action(
                payload.action,
                payload.text,
                payload.key
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported action: {payload.action}")
            
        if success:
            return {"status": "success"}
        else:
            return {"status": "error", "message": "Action execution failed."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/{file_path:path}")
def serve_static(file_path: str):
    # Resolve the path to renderer folder
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
    renderer_dir = os.path.join(base_dir, "renderer")
    if not os.path.exists(renderer_dir):
        # Fallback to dev mode path
        renderer_dir = os.path.abspath(os.path.join(base_dir, "..", "electron", "renderer"))
    
    # If the file path is empty (root route `/`), serve main.html
    if not file_path:
        file_path = "main.html"
        
    full_path = os.path.join(renderer_dir, file_path)
    
    # Normalize path and check directory boundary to prevent directory traversal vulnerability
    normalized_path = os.path.abspath(full_path)
    if not normalized_path.startswith(os.path.abspath(renderer_dir)):
        raise HTTPException(status_code=403, detail="Forbidden")
        
    if os.path.exists(normalized_path) and os.path.isfile(normalized_path):
        # Determine media type for CSS/JS/HTML files
        media_type = None
        if file_path.endswith(".css"):
            media_type = "text/css"
        elif file_path.endswith(".js"):
            media_type = "application/javascript"
        elif file_path.endswith(".html"):
            media_type = "text/html"
        return FileResponse(normalized_path, media_type=media_type)
        
    raise HTTPException(status_code=404, detail="File not found")

# Startup initialization
@app.on_event("startup")
def startup_event():
    import threading
    monitor_thread = threading.Thread(target=resource_monitor_thread_fn, daemon=True)
    monitor_thread.start()

# Shutdown cleanup
@app.on_event("shutdown")
def shutdown_event():
    stop_all_components()

if __name__ == "__main__":
    import uvicorn
    # Start on port 8000
    uvicorn.run(app, host="127.0.0.1", port=8000)
