# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import warnings

# Silence torchcodec / FFmpeg warnings during PyInstaller analysis
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Add virtual environment site-packages to sys.path so that PyInstaller (running under system Python)
# can successfully locate and collect metadata/binaries for all virtualenv dependencies.
venv_site_packages = os.path.join(SPECPATH, "env", "Lib", "site-packages")
if os.path.exists(venv_site_packages):
    sys.path.insert(0, venv_site_packages)
    
    # Crucial: Register the pywin32 DLL path so PyInstaller can successfully import pywin32 modules (win32api, pythoncom, etc.)
    # during the analysis/hook phase without throwing ModuleNotFoundError: No module named 'pywintypes'.
    pywin32_dlls = os.path.join(venv_site_packages, "pywin32_system32")
    if os.path.exists(pywin32_dlls):
        try:
            os.add_dll_directory(pywin32_dlls)
        except AttributeError:
            pass
        os.environ["PATH"] = pywin32_dlls + os.pathsep + os.environ.get("PATH", "")

from PyInstaller.utils.hooks import collect_all, copy_metadata

# Setup DLL directory for PyInstaller build process to successfully import torchcodec/pyannote
ffmpeg_bin = os.path.abspath(os.path.join(SPECPATH, 'ffmpeg-shared', 'ffmpeg-7.1-full_build-shared', 'bin'))
if os.path.exists(ffmpeg_bin):
    try:
        os.add_dll_directory(ffmpeg_bin)
    except AttributeError:
        os.environ["PATH"] = ffmpeg_bin + os.pathsep + os.environ.get("PATH", "")

datas = []
binaries = []

# Package FFmpeg DLLs into the executable
if os.path.exists(ffmpeg_bin):
    for f in os.listdir(ffmpeg_bin):
        if f.endswith('.dll'):
            binaries.append((os.path.join(ffmpeg_bin, f), '.'))

hiddenimports = [
    'uvicorn', 'fastapi', 'jinja2', 'torch',
    'pywintypes',
    'pythoncom'
]

# Helper to dynamically walk and collect all submodules to bypass lazy-loading import issues
def collect_submodules(package_name):
    try:
        import importlib
        pkg = importlib.import_module(package_name)
        pkg_path = os.path.dirname(pkg.__file__)
        pkg_dir = os.path.dirname(pkg_path)
        
        submods = []
        for root, dirs, files in os.walk(pkg_path):
            for file in files:
                if file.endswith('.py'):
                    full_file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_file_path, pkg_dir)
                    mod_name = os.path.splitext(rel_path)[0].replace(os.path.sep, '.')
                    if mod_name.endswith('.__init__'):
                        mod_name = mod_name[:-9]
                    submods.append(mod_name)
        return submods
    except Exception as e:
        return []

dynamic_packages = [
    'transformers',
    'pyannote',
    'whisperx',
    'faster_whisper',
    'faster_qwen3_tts',
    'qwen_tts',
    'huggingface_hub'
]

for pkg in dynamic_packages:
    hiddenimports += collect_submodules(pkg)

# List of core packages to collect all resources and metadata for
core_packages = [
    'torch',
    'whisperx',
    'faster_whisper',
    'ctranslate2',
    'pyannote',
    'pyannote.audio',
    'pyannote.core',
    'pyannote.database',
    'pyannote.metrics',
    'pyannote.pipeline',
    'transformers',
    'huggingface_hub',
    'ytmusicapi',
    'faster_qwen3_tts',
    'qwen_tts',
    'librosa'
]

for pkg in core_packages:
    # Collect all submodules, data files, and binaries
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]
    
    # Collect package metadata
    try:
        datas += copy_metadata(pkg)
    except Exception as e:
        pass

# Copy metadata for other essential dependencies
for dep in ['torch', 'tqdm', 'regex', 'tokenizers']:
    try:
        datas += copy_metadata(dep)
    except Exception as e:
        pass


a = Analysis(
    ['src/api_server.py'],
    pathex=[venv_site_packages],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tensorboard', 'torch.utils.tensorboard', 'nltk', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='api_server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='api_server',
)
