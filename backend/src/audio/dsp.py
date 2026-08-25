"""Digital Signal Processing (DSP) utilities for STT audio preprocessing."""

import numpy as np
from scipy.signal import sosfilt
from config.settings import audio_cfg


def preprocess_audio(raw_pcm_bytes: bytes) -> np.ndarray:
    """Converts raw PCM 16-bit audio bytes to normalized float32 array with bandpass conditioning."""
    if not raw_pcm_bytes:
        return np.array([], dtype=np.float32)

    audio_int16 = np.frombuffer(raw_pcm_bytes, dtype=np.int16)
    audio_float = audio_int16.astype(np.float32) / 32768.0

    try:
        filtered_audio = sosfilt(audio_cfg.sos_filter, audio_float)
    except Exception:
        filtered_audio = audio_float

    return np.ascontiguousarray(np.clip(filtered_audio, -1.0, 1.0), dtype=np.float32)