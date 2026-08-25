"""Application settings and hyperparameter management."""

import os
import dataclasses
@dataclasses.dataclass
class AudioConfig:
    sample_rate: int = 16000
    frame_duration_ms: int = 30
    frame_size: int = int(sample_rate * (frame_duration_ms / 1000.0))
    vad_aggressiveness: int = 2
    padding_frames: int = int(500 / frame_duration_ms)
    min_speech_duration: float = 0.8
    max_speech_duration: float = 12.0
    _sos_filter: object = dataclasses.field(default=None, init=False, repr=False)

    @property
    def sos_filter(self):
        if self._sos_filter is None:
            from scipy.signal import butter
            self._sos_filter = butter(
                N=4, Wn=[80, 7500], btype="bandpass", fs=16000, output="sos"
            )
        return self._sos_filter



@dataclasses.dataclass
class ModelConfig:
    stt_model_size: str = "medium"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    stt_batch_size: int = 1
    align_words: bool = False

    server_host: str = "127.0.0.1"  # Replace with machine IP if hosted remotely
    server_port: int = 8080
    server_timeout: float = 60.0

    # Memory & Context Optimization Settings
    max_history_len: int = 6           # Max standard history turns (6 turns = 12 user/assistant messages)
    max_tool_output_len: int = 1500    # Hard limit on raw tool output strings before truncation
    max_estimated_tokens: int = 15000  # Token threshold to trigger aggressive context compression

    tts_repo_id: str = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    tts_device: str = "cuda"
    tts_speaker: str = "Aiden"

    max_output_tokens: int = 10000


audio_cfg = AudioConfig()
model_cfg = ModelConfig()

# Load settings from JSON if exists to allow user configurations
import sys

def get_user_data_dir():
    # Resolve the OS-specific application data folder matching Electron's app.getPath('userData')
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
        
    return base_dir

def get_user_settings_path():
    return os.path.join(get_user_data_dir(), "settings.json")

SETTINGS_JSON_PATH = get_user_settings_path()
if os.path.exists(SETTINGS_JSON_PATH):
    import json
    try:
        with open(SETTINGS_JSON_PATH, "r") as f:
            data = json.load(f)
            
            # Map audio configuration
            if "audio" in data:
                for k, v in data["audio"].items():
                    if hasattr(audio_cfg, k):
                        setattr(audio_cfg, k, v)
                # Recalculate frame_size and padding_frames if relevant settings changed
                audio_cfg.frame_size = int(audio_cfg.sample_rate * (audio_cfg.frame_duration_ms / 1000.0))
                audio_cfg.padding_frames = int(500 / audio_cfg.frame_duration_ms)
                
            # Map model configuration
            if "model" in data:
                for k, v in data["model"].items():
                    if hasattr(model_cfg, k):
                        setattr(model_cfg, k, v)
    except Exception as e:
        print(f"[SETTINGS] Error loading settings.json: {e}")

# Output directory setup
if getattr(sys, 'frozen', False):
    OUTPUTS_DIR = os.path.join(os.path.dirname(sys.executable), "outputs")
else:
    OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)
CHIME_PATH = os.path.join(OUTPUTS_DIR, "chime.wav")