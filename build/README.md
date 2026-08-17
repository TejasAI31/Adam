# Adam Packaging & Installer Build Documentation

This folder contains the build pipeline scripts to package the entire Adam application—both the Electron-based desktop frontend and the PyTorch-based speech backend—into a single, zero-dependency, offline Windows installer program (`.exe`).

---

## What the Build Pipeline Does

1. **Locates and Bundles System Executables**: 
   Scans the host system (PATH, AppData, WinGet packages, and local directories) to find `llama-server.exe` and packages it directly with the backend so that LLM support works completely out-of-the-box on client machines.
2. **Compiles the Python Backend**:
   - **Compiled Mode (Default)**: Uses PyInstaller to bundle the FastAPI API server, PyTorch, faster-whisper, and speech synthesis dependencies into a compiled executable directory (`backend/dist/api_server`).
   - **Fallback Mode**: If PyInstaller is missing or compilation fails, it copies and stages the existing virtual environment (`backend/env`), ensuring that the installer build is robust and always succeeds.
3. **Stages Backend Components**: 
   Creates a temporary staged backend containing only production assets. It automatically filters out heavy developer assets like model weights (`.gguf`/`.bin` files), git history, temp screenshots, outputs, and pip download caches to minimize installer size.
4. **Integrates with Electron-Builder**:
   Injects build parameters dynamically into the Electron configurations, setting shortcut targets, desktop shortcuts, and packaging the staged backend as an `extraResource` resource.
5. **Generates NSIS Windows Installer**:
   Triggers `electron-builder` to bundle the assets, generating a single, standalone installation program (`dist/Adam Setup 1.0.0.exe`).

---

## How to Run the Build

You can run the build using the provided batch file or directly in Python. Run commands from the `build` folder.

### 1. Default Build (PyInstaller Compiled Backend + Electron Installer)
Compiles the Python server to an executable directory (using `api_server.spec`) and packages it as a zero-dependency standalone application (no Python installation required on client machines):
```cmd
build.bat
```
*or via Python:*
```bash
python build.py
```

### 2. Fast Build / Fallback (Packages Virtual Environment + Electron Installer)
Skips PyInstaller compilation and directly packages the staged virtual environment (useful for development testing):
```cmd
build.bat --skip-compile
```
*or via Python:*
```bash
python build.py --skip-compile
```

### 3. Test Build (Generates Unpackaged Directory)
Builds the directory layout of the final application under `dist/win-unpacked` for local validation without compiling the final installer:
```cmd
build.bat --test
```
*or via Python:*
```bash
python build.py --test
```
