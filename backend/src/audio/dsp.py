"""Digital Signal Processing (DSP) and Noise Reduction utilities."""

import noisereduce as nr
import numpy as np
from scipy.signal import sosfilt
from config.settings import audio_cfg


def preprocess_audio(raw_pcm_bytes: bytes) -> np.ndarray:
    """Applies DSP bandpass filtering and spectral noise reduction to PCM audio bytes."""
    if not raw_pcm_bytes:
        return np.array([], dtype=np.float32)

    audio_int16 = np.frombuffer(raw_pcm_bytes, dtype=np.int16)
    audio_float = audio_int16.astype(np.float32) / 32768.0
    filtered_audio = sosfilt(audio_cfg.sos_filter, audio_float)

    try:
        denoised_audio = nr.reduce_noise(
            y=filtered_audio,
            sr=audio_cfg.sample_rate,
            stationary=True,
            prop_decrease=0.75,
        )
    except Exception:
        denoised_audio = filtered_audio

    return np.clip(denoised_audio, -1.0, 1.0).astype(np.float32)