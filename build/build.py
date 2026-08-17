#!/usr/bin/env python3
"""
Adam Build & Packaging Pipeline
Compiles and bundles the Electron frontend and Python backend, including llama-server.exe,
into a single, zero-dependency Windows installation program (.exe).
"""

import os
import sys
import shutil
import json
import subprocess
import argparse
import time

# Define absolute paths
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
ELECTRON_DIR = os.path.join(ROOT_DIR, "electron")
BUILD_DIR = os.path.join(ROOT_DIR, "build")
TEMP_BACKEND_STAGE = os.path.join(BUILD_DIR, "temp_backend")
OUTPUT_DIST_DIR = os.path.join(ROOT_DIR, "dist")

def log(msg, level="INFO"):
    print(f"[{level}] {msg}")

def check_os():
    if sys.platform != "win32":
        log("This installer build script is designed for Windows environments only.", "ERROR")
        sys.exit(1)

def locate_llama_server():
    log("Locating llama-server.exe...")
    # 1. Check system path
    which_path = shutil.which("llama-server.exe") or shutil.which("llama-server")
    if which_path:
        log(f"Found llama-server.exe in system PATH: {which_path}")
        return which_path

    # 2. Check WinGet Packages location
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        winget_packages = os.path.join(local_appdata, "Microsoft", "WinGet", "Packages")
        if os.path.exists(winget_packages):
            for root, dirs, files in os.walk(winget_packages):
                if "llama-server.exe" in files:
                    found_path = os.path.join(root, "llama-server.exe")
                    log(f"Found llama-server.exe in WinGet Packages: {found_path}")
                    return found_path

    # 3. Check common development locations
    common_paths = [
        os.path.join(BACKEND_DIR, "llama-server.exe"),
        os.path.join(ROOT_DIR, "llama-server.exe")
    ]
    for p in common_paths:
        if os.path.exists(p):
            log(f"Found llama-server.exe in common location: {p}")
            return p

    log("llama-server.exe could not be found! Ensure it is installed and in your PATH.", "WARNING")
    return None

def install_node_deps():
    log("Installing Node.js packaging dependencies in Electron directory...")
    # Check if npm is ready
    try:
        subprocess.run(["npm", "--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)
    except Exception:
        log("npm command not found. Please install Node.js and try again.", "ERROR")
        sys.exit(1)

    # Install electron-builder locally in electron dir
    subprocess.run(["npm", "install", "--save-dev", "electron-builder"], cwd=ELECTRON_DIR, check=True, shell=True)
    log("Node.js packaging dependencies ready.")

def compile_python_backend(use_pyinstaller=True):
    """
    Compiles the Python backend using PyInstaller, or falls back to copy a pruned virtual environment.
    """
    if use_pyinstaller:
        log("Checking for PyInstaller...")
        python_exe = os.path.join(BACKEND_DIR, "env", "Scripts", "python.exe")
        if not os.path.exists(python_exe):
            python_exe = sys.executable

        # Install pyinstaller inside the virtual environment if missing
        pyinstaller_installed = False
        try:
            subprocess.run([python_exe, "-m", "PyInstaller", "--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pyinstaller_installed = True
            log("PyInstaller is already installed in the virtual environment.")
        except Exception:
            pass

        if not pyinstaller_installed:
            log("PyInstaller not found in the virtual environment. Installing via pip...")
            subprocess.run([python_exe, "-m", "pip", "install", "pyinstaller"], check=True)

        build_cmd = [
            python_exe,
            "-m", "PyInstaller",
            "api_server.spec",
            "--clean",
            "--noconfirm"
        ]
        
        try:
            log("Compiling Python backend with PyInstaller (this might take a few minutes)...")
            
            # Start process with stdout/stderr piped
            process = subprocess.Popen(
                build_cmd,
                cwd=BACKEND_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # Reconfigure stdout to use UTF-8 if supported (to prevent UnicodeEncodeError under CP1252)
            if hasattr(sys.stdout, 'reconfigure'):
                try:
                    sys.stdout.reconfigure(encoding='utf-8')
                except Exception:
                    pass

            # Determine safe progress bar characters based on encoding compatibility
            fill_char = "█"
            empty_char = "░"
            try:
                # Test encoding compatibility
                fill_char.encode(sys.stdout.encoding or "utf-8")
                empty_char.encode(sys.stdout.encoding or "utf-8")
            except (UnicodeEncodeError, TypeError):
                # Fallback to standard ASCII characters if CP1252 or other incompatible encoding is active
                fill_char = "="
                empty_char = "-"

            start_time = time.time()
            full_output = []
            
            # Color codes
            CYAN = "\033[96m"
            GREEN = "\033[92m"
            YELLOW = "\033[93m"
            MAGENTA = "\033[95m"
            RESET = "\033[0m"
            
            current_milestone = "Initializing compiler"
            current_pct = 2
            
            # Keep track of line count to increment percentage smoothly
            line_count = 0
            
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    full_output.append(line)
                    line_str = line.strip()
                    line_count += 1
                    
                    # Detect milestones
                    new_milestone = None
                    if "Analyzing modules" in line_str or "Analyzing C:\\" in line_str:
                        new_milestone = "Analyzing module dependencies"
                        base_pct = 10
                    elif "Building Analysis" in line_str:
                        new_milestone = "Building dependency tree"
                        base_pct = 60
                    elif "Building PKG" in line_str:
                        new_milestone = "Assembling Python package"
                        base_pct = 75
                    elif "Building EXE" in line_str:
                        new_milestone = "Generating executable wrapper"
                        base_pct = 85
                    elif "Building COLLECT" in line_str:
                        new_milestone = "Collecting dynamic libraries and resources"
                        base_pct = 92
                    else:
                        base_pct = None
                        
                    if new_milestone:
                        current_milestone = new_milestone
                        current_pct = base_pct
                    else:
                        # Smooth increment within milestone ranges based on processed line volume
                        if current_pct < 60:  # Analyzing
                            current_pct = min(59, 10 + int(line_count / 15))
                        elif current_pct < 75:  # Tree building
                            current_pct = min(74, 60 + int(line_count / 25))
                        elif current_pct < 85:  # PKG
                            current_pct = min(84, 75 + int(line_count / 35))
                        elif current_pct < 92:  # EXE
                            current_pct = min(91, 85 + int(line_count / 45))
                        elif current_pct < 98:  # COLLECT
                            current_pct = min(97, 92 + int(line_count / 65))
                            
                    # Build progress bar
                    bar_length = 25
                    filled_length = int(bar_length * current_pct // 100)
                    bar = fill_char * filled_length + empty_char * (bar_length - filled_length)
                    
                    # Output dashboard line (without ETA)
                    status_text = f"\r{CYAN}[Compiling]{RESET} {GREEN}[{bar}]{RESET} {YELLOW}{current_pct:3d}%{RESET} | {CYAN}{current_milestone}{RESET}"
                    sys.stdout.write(status_text.ljust(85))
                    sys.stdout.flush()
                    time.sleep(0.002)
            
            # Compilation finished
            current_pct = 100
            bar = fill_char * 25
            status_text = f"\r{GREEN}[Finished]{RESET} {GREEN}[{bar}]{RESET} {YELLOW}100%{RESET} | Elapsed: {MAGENTA}{int(time.time() - start_time)}s{RESET} | {GREEN}Compilation successful{RESET}"
            sys.stdout.write(status_text.ljust(85) + "\n")
            sys.stdout.flush()
            
            # Write build log file
            build_log_path = os.path.join(BUILD_DIR, "build.log")
            try:
                os.makedirs(BUILD_DIR, exist_ok=True)
                with open(build_log_path, "w", encoding="utf-8") as f:
                    f.write("".join(full_output))
            except Exception as e:
                log(f"Failed to write build.log: {e}", "WARNING")
            
            rc = process.poll()
            if rc != 0:
                log(f"PyInstaller compilation failed with exit code {rc}. Full build log:", "ERROR")
                print("".join(full_output))
                return False
                
            return True
        except Exception as e:
            log(f"PyInstaller compilation failed: {e}. Falling back to virtual environment packaging...", "WARNING")
            return False
    return False

def stage_backend(compiled=False, llama_path=None):
    """
    Creates a clean temp_backend staging directory to be copied as an extra resource.
    Excludes model checkpoints, cache folders, and temp screenshots to minimize installer size.
    """
    log("Staging backend files for packaging...")
    if os.path.exists(TEMP_BACKEND_STAGE):
        shutil.rmtree(TEMP_BACKEND_STAGE)
    os.makedirs(TEMP_BACKEND_STAGE, exist_ok=True)

    # 1. Copy llama-server.exe and associated dynamic link libraries (DLLs)
    if llama_path and os.path.exists(llama_path):
        shutil.copy2(llama_path, os.path.join(TEMP_BACKEND_STAGE, "llama-server.exe"))
        llama_dir = os.path.dirname(llama_path)
        for item in os.listdir(llama_dir):
            if item.lower().endswith(".dll"):
                shutil.copy2(os.path.join(llama_dir, item), os.path.join(TEMP_BACKEND_STAGE, item))
        log("Bundled llama-server.exe and associated dynamic link libraries (DLLs) inside staging directory.")

    # 2. Copy compiled binary or full source environment
    if compiled:
        compiled_dir = os.path.join(BACKEND_DIR, "dist", "api_server")
        if os.path.exists(compiled_dir):
            log("Copying PyInstaller compiled binary files...")
            # Copy all files from dist/api_server to temp_backend/
            for item in os.listdir(compiled_dir):
                s = os.path.join(compiled_dir, item)
                d = os.path.join(TEMP_BACKEND_STAGE, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)
            
            # Copy critical resource folders to ensure startup and execution are successful
            for folder in ["config", "voices", "models"]:
                src_folder = os.path.join(BACKEND_DIR, folder)
                dest_folder = os.path.join(TEMP_BACKEND_STAGE, folder)
                if os.path.exists(src_folder):
                    # Filter out model weights to avoid installer bloat
                    def ignore_gguf(path, names):
                        return [n for n in names if n.endswith(".gguf") or n.endswith(".bin")]
                    shutil.copytree(src_folder, dest_folder, ignore=ignore_gguf if folder == "models" else None)
            
            # Copy ffmpeg-shared folder if it exists to ensure DLLs are bundled in resources fallback
            ffmpeg_src = os.path.join(BACKEND_DIR, "ffmpeg-shared")
            if os.path.exists(ffmpeg_src):
                log("Bundling ffmpeg-shared directory into compiled staging directory...")
                shutil.copytree(ffmpeg_src, os.path.join(TEMP_BACKEND_STAGE, "ffmpeg-shared"))

            # Copy renderer folder from electron to temp_backend/renderer to support compiled remote control
            renderer_src = os.path.join(ELECTRON_DIR, "renderer")
            if os.path.exists(renderer_src):
                log("Bundling renderer directory into compiled staging directory...")
                shutil.copytree(renderer_src, os.path.join(TEMP_BACKEND_STAGE, "renderer"))
            return

    # Fallback/Default: Copy source files and virtual env, excluding weight/logs/cache files
    log("Copying backend source files and virtual environment (Fallback Mode)...")
    
    # Custom filter function for copytree to ignore heavy/developer files
    def ignore_patterns(path, names):
        ignored = []
        for name in names:
            full_path = os.path.join(path, name)
            # Exclude large weights/checkpoints/snapshots (only outside virtual environment)
            if ("env" not in path) and (name.endswith(".gguf") or name.endswith(".bin")):
                ignored.append(name)
            elif name in ["__pycache__", ".git", ".idea", ".vscode"]:
                ignored.append(name)
            # Exclude large pip caching blocks
            elif name in ["pip-cache", "pip", "cache", "logs", "screenshots", "outputs"] and "env" in path:
                ignored.append(name)
        return ignored

    # Copy src, config, env directories and config files
    for folder in ["src", "config", "env"]:
        src_folder = os.path.join(BACKEND_DIR, folder)
        dest_folder = os.path.join(TEMP_BACKEND_STAGE, folder)
        if os.path.exists(src_folder):
            shutil.copytree(src_folder, dest_folder, ignore=ignore_patterns)

    # Copy root settings files if any
    for file in ["requirements.txt"]:
        src_file = os.path.join(BACKEND_DIR, file)
        if os.path.exists(src_file):
            shutil.copy2(src_file, TEMP_BACKEND_STAGE)

    # Copy ffmpeg-shared folder if it exists
    ffmpeg_src = os.path.join(BACKEND_DIR, "ffmpeg-shared")
    if os.path.exists(ffmpeg_src):
        log("Bundling ffmpeg-shared directory into fallback staging directory...")
        shutil.copytree(ffmpeg_src, os.path.join(TEMP_BACKEND_STAGE, "ffmpeg-shared"))

    # Copy renderer folder from electron to temp_backend/renderer to support fallback remote control
    renderer_src = os.path.join(ELECTRON_DIR, "renderer")
    if os.path.exists(renderer_src):
        log("Bundling renderer directory into fallback staging directory...")
        shutil.copytree(renderer_src, os.path.join(TEMP_BACKEND_STAGE, "renderer"))

def configure_electron_builder():
    log("Configuring electron-builder targets in packaging manifest...")
    package_json_path = os.path.join(ELECTRON_DIR, "package.json")
    
    with open(package_json_path, "r", encoding="utf-8") as f:
        package_data = json.load(f)

    # Add electron-builder build configurations
    package_data["build"] = {
        "appId": "com.adam.desktop",
        "productName": "Adam",
        "directories": {
            "output": "../dist"
        },
        "files": [
            "**/*"
        ],
        "extraResources": [
            {
                "from": "../build/temp_backend",
                "to": "backend",
                "filter": ["**/*"]
            }
        ],
        "win": {
            "target": [
                "nsis-web"
            ],
            "icon": "icon.png"
        },
        "nsis": {
            "oneClick": False,
            "allowToChangeInstallationDirectory": True,
            "createDesktopShortcut": True,
            "createStartMenuShortcut": True,
            "shortcutName": "Adam"
        },
        "nsisWeb": {
            "appPackageUrl": "http://localhost"
        }
    }

    # Write back updated package.json
    with open(package_json_path, "w", encoding="utf-8") as f:
        json.dump(package_data, f, indent=2)
    log("package.json build configuration updated.")

def run_electron_builder(dir_only=False):
    log("Executing electron-builder packaging script...")
    builder_args = ["npx", "electron-builder", "build", "--win"]
    if dir_only:
        builder_args.append("--dir") # Builds unpackaged directory structure for testing

    subprocess.run(builder_args, cwd=ELECTRON_DIR, check=True, shell=True)
    log(f"electron-builder build completed successfully! Check installer output under: {OUTPUT_DIST_DIR}")

def clean_temp_files():
    log("Cleaning temporary staging files...")
    if os.path.exists(TEMP_BACKEND_STAGE):
        shutil.rmtree(TEMP_BACKEND_STAGE)
    log("Cleanup complete.")

def main():
    parser = argparse.ArgumentParser(description="Adam Pipeline Build & Packaging Tool")
    parser.add_argument("--skip-compile", action="store_true", help="Skip PyInstaller compilation and package direct virtual environment")
    parser.add_argument("--test", action="store_true", help="Compile an unpackaged directory structure for testing instead of full installer")
    args = parser.parse_args()

    check_os()
    
    # Terminate any running app/backend/llama-server processes to release file handles and prevent EBUSY/lock crashes
    log("Terminating active instances of Adam, python backend, or llama-server to release file locks...")
    for exe in ["Adam.exe", "api_server.exe", "main.exe", "adam-desktop.exe", "llama-server.exe"]:
        subprocess.run(["taskkill", "/f", "/im", exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["taskkill", "/f", "/fi", "WINDOWTITLE eq Uvicorn*"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Use psutil to clean up any orphaned python or weight server processes locking files inside the project dir
    try:
        import psutil
        current_pid = os.getpid()
        killed_count = 0
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                # Terminate any running llama-server.exe (in case it wasn't caught by taskkill)
                if proc.info['name'] and proc.info['name'].lower() == "llama-server.exe":
                    proc.kill()
                    killed_count += 1
                    continue
                # Terminate any other python processes running from within our project root running the API server or uvicorn
                if proc.info['name'] and proc.info['name'].lower() in ["python.exe", "pythonw.exe"]:
                    if proc.info['pid'] == current_pid:
                        continue
                    exe_path = proc.info['exe']
                    if exe_path and (ROOT_DIR.lower() in exe_path.lower()):
                        # Only kill if it's running the API server or uvicorn
                        try:
                            cmdline = proc.cmdline()
                        except Exception:
                            cmdline = []
                        is_api_server = any("api_server.py" in arg.lower() or "uvicorn" in arg.lower() for arg in cmdline)
                        if is_api_server:
                            log(f"Killing python process {proc.info['pid']} running API server in {exe_path}...")
                            proc.kill()
                            killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        if killed_count > 0:
            log(f"Successfully terminated {killed_count} active lock-holding processes.")
    except Exception as e:
        log(f"Advanced process scan skipped or failed: {e}. Standard taskkills completed.")
    
    # Always clean old compilation output folders to ensure a completely clean build
    if not args.skip_compile:
        for folder in ["dist", "build"]:
            p = os.path.join(BACKEND_DIR, folder)
            if os.path.exists(p):
                log(f"Removing old compilation folder to ensure a clean build: {p}...")
                try:
                    shutil.rmtree(p)
                except Exception as e:
                    log(f"Warning: Could not remove {p}: {e}")
    
    # 1. Locate llama-server
    llama_path = locate_llama_server()
    
    # 2. Compile Backend (or reuse existing/fallback)
    backend_compiled = False
    if not args.skip_compile:
        backend_compiled = compile_python_backend(use_pyinstaller=True)
        
    # 3. Stage backend components
    stage_backend(compiled=backend_compiled, llama_path=llama_path)
    
    # 4. Install Node dependencies
    install_node_deps()
    
    # 5. Configure Builder Manifest
    configure_electron_builder()
    
    # 6. Execute Build
    run_electron_builder(dir_only=args.test)
    
    # 7. Clean Staging Area
    clean_temp_files()
    
    log("Adam installation package generated successfully!", "SUCCESS")

if __name__ == "__main__":
    main()
