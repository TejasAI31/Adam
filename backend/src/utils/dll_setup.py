import os
import sys

def setup_dll_directories():
    """Register FFmpeg shared DLLs for Windows to avoid torchcodec import failures."""
    if sys.platform == "win32":
        if getattr(sys, 'frozen', False):
            # Running inside a PyInstaller packaged executable
            base_dir = getattr(sys, '_MEIPASS', None)
            if base_dir and os.path.exists(base_dir):
                try:
                    os.add_dll_directory(base_dir)
                    # Prepend base_dir to PATH
                    os.environ["PATH"] = base_dir + os.pathsep + os.environ.get("PATH", "")
                    
                    # Also register torch/lib DLL directory to allow ctranslate2/faster-whisper
                    # and torch submodules to locate PyTorch's bundled CUDA libraries
                    torch_lib = os.path.join(base_dir, "torch", "lib")
                    if os.path.exists(torch_lib):
                        os.add_dll_directory(torch_lib)
                        os.environ["PATH"] = torch_lib + os.pathsep + os.environ.get("PATH", "")
                except Exception as e:
                    print(f"[DLL SETUP] Error adding _MEIPASS directory: {e}")
        else:
            # Running as normal python script / development environment
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            ffmpeg_bin = os.path.join(base_dir, "ffmpeg-shared", "ffmpeg-7.1-full_build-shared", "bin")
            if os.path.exists(ffmpeg_bin):
                try:
                    os.add_dll_directory(ffmpeg_bin)
                    # Prepend to PATH for child processes
                    os.environ["PATH"] = ffmpeg_bin + os.pathsep + os.environ.get("PATH", "")
                except AttributeError:
                    os.environ["PATH"] = ffmpeg_bin + os.pathsep + os.environ.get("PATH", "")
            else:
                # Local bin fallback
                local_bin = os.path.join(base_dir, "ffmpeg-shared", "bin")
                if os.path.exists(local_bin):
                    try:
                        os.add_dll_directory(local_bin)
                        os.environ["PATH"] = local_bin + os.pathsep + os.environ.get("PATH", "")
                    except AttributeError:
                        os.environ["PATH"] = local_bin + os.pathsep + os.environ.get("PATH", "")

            # Register pywin32_system32 DLL folder if running in virtualenv on Windows
            pywin32_sys32 = os.path.join(base_dir, "env", "Lib", "site-packages", "pywin32_system32")
            if os.path.exists(pywin32_sys32):
                try:
                    os.add_dll_directory(pywin32_sys32)
                    os.environ["PATH"] = pywin32_sys32 + os.pathsep + os.environ.get("PATH", "")
                except Exception as e:
                    print(f"[DLL SETUP] Error adding pywin32_system32: {e}")

# Run immediately on module load
setup_dll_directories()
