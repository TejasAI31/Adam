"""STT Engine implementation using faster_whisper with robust device and compute-type fallback."""

import logging
import warnings
import numpy as np
import torch
from config.settings import model_cfg

# Suppress warnings
warnings.filterwarnings("ignore", category=UserWarning)


class FasterWhisperWrapper:
    def __init__(self, model_size, device, compute_type):
        from faster_whisper import WhisperModel
        print(f"Initializing FasterWhisperModel({model_size}) on {str(device).upper()} ({compute_type})...")
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type
        )

    def transcribe(self, audio, batch_size=None, language="en"):
        if audio is None:
            return {"segments": [], "language": "en"}

        if isinstance(audio, bytes):
            audio = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        elif not isinstance(audio, np.ndarray):
            audio = np.array(audio, dtype=np.float32)

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        if not audio.flags["C_CONTIGUOUS"]:
            audio = np.ascontiguousarray(audio)

        if len(audio) == 0:
            return {"segments": [], "language": "en"}

        try:
            # transcribe returns a generator of segments and transcription info
            segments, info = self.model.transcribe(
                audio,
                language=language if language else "en",
                beam_size=5,
                condition_on_previous_text=False,
                vad_filter=False,
                temperature=0.0
            )
            
            segment_list = []
            for s in segments:
                if s.text:
                    segment_list.append({
                        "text": s.text,
                        "start": s.start,
                        "end": s.end
                    })
                
            return {
                "segments": segment_list,
                "language": getattr(info, "language", "en") if info else "en"
            }
        except Exception as e:
            print(f"[FasterWhisper Transcribe Error]: {e}")
            return {"segments": [], "language": "en"}


def load_stt_engine():
    device = getattr(model_cfg, "stt_device", "cuda")
    use_cuda = device in ["cuda", "gpu"] and torch.cuda.is_available()
    model_size = getattr(model_cfg, "stt_model_size", "medium")

    if use_cuda:
        try:
            return FasterWhisperWrapper(
                model_size,
                device="cuda",
                compute_type=getattr(model_cfg, "stt_compute_type", "float16")
            )
        except Exception as e:
            print(f"[STT Load Warning] FasterWhisper on CUDA failed ({e}). Falling back to CPU int8...")
            try:
                return FasterWhisperWrapper(
                    model_size,
                    device="cpu",
                    compute_type="int8"
                )
            except Exception as e2:
                print(f"[STT Load Warning] CPU FasterWhisper failed ({e2}). Trying whisperx fallback...")
                import whisperx
                return whisperx.load_model(
                    model_size,
                    device="cpu",
                    compute_type="int8",
                    language="en",
                )
    else:
        try:
            return FasterWhisperWrapper(
                model_size,
                device="cpu",
                compute_type="int8"
            )
        except Exception as e:
            print(f"[STT Load Warning] CPU FasterWhisper failed ({e}). Trying whisperx fallback...")
            import whisperx
            return whisperx.load_model(
                model_size,
                device="cpu",
                compute_type="int8",
                language="en",
            )