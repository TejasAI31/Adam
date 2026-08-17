# Adam

Adam is a high-performance desktop application integrating local Large Language Model (LLM) inference, real-time Speech-to-Text (STT) transcription, and Text-to-Speech (TTS) vocalization. Built with a premium, low-latency design, the application supports full-duplex voice interactions, background tool execution, and remote workspace orchestration.

---

## Architectural Topology

Adam uses a decoupled frontend-backend architecture to guarantee GUI responsiveness and isolated heavy-computation processing.

```
               +-------------------------------------------------------+
               |                   ELECTRON CLIENT                     |
               |  - HTML5/JS Interface & Neon-Cyan Styling             |
               |  - Main Process Control Daemon                        |
               |  - Server-Sent Events (SSE) Listener                  |
               |  - IPC Main/Renderer Bridge                           |
               +--------------------------+----------------------------+
                                          |
                               HTTP / SSE Requests
                                          |
               +--------------------------v----------------------------+
               |                   FASTAPI BACKEND                     |
               |  - Uvicorn Server (http://127.0.0.1:8000)             |
               |  - Full-Duplex Dialogue & State Orchestrator          |
               |  - System Resource & Process Monitor                  |
               |  - Disk/Cache Garbage Collector                       |
               +----+---------------------+-----------------------+----+
                    |                     |                       |
               +----v----+           +----v----+             +----v----+
               |  LLaMA  |           | Whisper |             |  Qwen   |
               | SERVER  |           |   STT   |             |   TTS   |
               +---------+           +---------+             +---------+
```

### Core Subsystems

* **Frontend Client (`electron/`)**: Built on Electron. Handles window routing (`selection.html`, `setup.html`, `main.html`), hardware configurations storage, and SSH tunneling scripts.
* **FastAPI Server (`backend/src/api_server.py`)**: Runs on Uvicorn. Orchestrates session states, exposes process diagnostics, and controls the audio playback queue.
* **LLaMA Server Daemon**: Spawns the `llama-server.exe` binary in the background to serve local GGUF models with hardware graphics acceleration (CUDA/CPU).
* **STT Transcription**: Employs the `WhisperX` engine to transcribe system-level microphone inputs into structured text.
* **TTS Synthesizer**: Utilizes the `Qwen-TTS` pipeline to generate natural vocal responses streamed directly to the system speakers.

---

## Core Capabilities and Optimizations

### 1. Hardware Allocation & Concurrent Model Downloader
* **Hardware Detection**: Automatically audits physical CPU cores, system RAM, GPU adapters, and VRAM to recommend optimal graphics layer offloading configurations.
* **Concurrent Downloads**: Supports multi-threaded downloading of Hugging Face repositories directly within the UI, with separate progress bars, speeds, and status logs for individual assets.
* **Bypass Symlink Limits**: Writes assets directly to snapshot paths, resolving the standard Windows administrative privilege requirements for creating symlinks.

![Model Configuration Workspace](images/model_configuration.png)

---

### 2. Dialogue & Orchestration Pipeline
* **Real-time Streaming**: Streams text responses token-by-token directly to the frontend chat UI in all execution rounds (including final answers generated after executing tools like `web_search`), removing visual latency.
* **Search Execution Cap**: Integrates Brave as the primary search engine with DDGS fallbacks. Limits the model to a maximum of 2 web searches per turn to prevent recursive tool-calling loops, forcing the LLM to synthesize final answers from the retrieved context.
* **Log Silence**: Suppresses intermediate reasoning outputs (such as `<think>` blocks) and redundant log prints to maintain clean logs and terminal output.

![Main Conversational Workspace](images/chat_screen.png)

---

### 3. Background Tool Action Logging
* **Expanded Toolbelt**: Exposes mathematical evaluation engines, system controllers, browser URL launchers, and accessibility hooks to the model.
* **Diagnostic Timeline**: Maintains a detailed execution timeline, input parameters, and output results for all background processes in a dedicated tool-logging panel.

![Tool Action Logging](images/tool_screen.png)

---

### 4. Interactive Remote Workspace
* **Robust Screen Grabbing**: Captures the host's primary desktop session using a DPI-aware Pillow screen grabber. Requests originating from loopback connections (`127.0.0.1`, `localhost`, or `::1`) automatically bypass remote access security overrides, enabling local desktop use.
* **Smooth Mouse Actions**: Simulates mouse dragging actions using absolute coordinates with incremental movements, pauses, and releases to ensure draggable items reach targets.
* **Focused Key Entry**: Click events are fired on target coordinates prior to sending text inputs, ensuring input controls are focused.
* **Dual-Mode File Explorer**: Tree nodes toggle their children list with single clicks, while double-clicking a folder opens the directory flatly at the root level of the file explorer panel.

![Sharing Configuration](images/settings_screen.png)

![Tunnel Administration](images/web_sharing.png)

![Remote Screen Capture and File Explorer](images/remote_sharing.png)

---

### 5. Core System Acceleration
* **Instant Startup**: Spawns Python backend processes immediately using environment `PATH` traversal instead of blocking shell lookup calls, reducing boot times by 4-6 seconds.
* **Non-blocking Disk Caching**: Caches Hugging Face repository queries in memory for 10 seconds to prevent file-locking conflicts on folders synchronized with OneDrive.

---

## System Specifications

### Default Pipeline Models

| Pipeline Stage | Model Name | Default Repository | Size | Device Support |
|---|---|---|---|---|
| Main LLM | `Qwen3.5-4B-Q4_K_M.gguf` | `Qwen/Qwen3.5-4B-Instruct-GGUF` | 2.55 GB | CPU / CUDA GPU |
| Vision LLM | `Qwen3VL-2B-Instruct-Q4_K_M.gguf` | `Qwen/Qwen3-VL-2B-Instruct-GGUF` | 1.03 GB | CPU / CUDA GPU |
| Drafter LLM | `Qwen3.5-0.8B-Q4_K_M.gguf` | `Qwen/Qwen3.5-0.8B-Instruct-GGUF` | 0.50 GB | CPU / CUDA GPU |
| Multi-Modal | `mmproj-Qwen3.5-4B-BF16.gguf` | `Qwen/Qwen3.5-4B-Instruct-GGUF` | 0.63 GB | CPU / CUDA GPU |
| Speech-to-Text | `whisperx:medium` | `Systran/faster-whisper-medium` | 1.50 GB | CPU / CUDA GPU |
| Text-to-Speech | `tts:qwen` | `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` | 1.20 GB | CPU / CUDA GPU |

### Resource Requirements

| Hardware Component | Minimum Specification | Recommended Specification |
|---|---|---|
| Processor | 4-Core CPU | 8-Core Intel Core i7 / AMD Ryzen 7 |
| Memory (RAM) | 16 GB | 32 GB |
| Graphics Card | 6 GB VRAM (CUDA-compatible) | 12 GB+ VRAM (NVIDIA RTX Series) |

---

## Installation & Developer Guide

### Development Setup (Source Code Execution)

#### 1. Setup Backend Environment
Initialize the Python virtual environment and install dependencies:
```cmd
cd backend
python -m venv env
call env\Scripts\activate
pip install -r requirements.txt
```

#### 2. Setup Frontend Environment
Install Node package dependencies:
```cmd
cd electron
npm install
```

#### 3. Run the App
Start the Electron GUI:
```cmd
cd electron
npm run dev
```

---

### Packaging Rebuild
To compile the standalone distribution executables:
```cmd
cd build
build.bat
```
This script compiles the Python backend using PyInstaller, packages the `ffmpeg-shared` binaries, copies required settings profiles, and compiles the final NSIS Web installer.
