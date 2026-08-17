"""STT Engine implementation using faster_whisper to avoid transformers/pyannote dependency issues."""

import logging
import warnings
from config.settings import model_cfg

# Suppress warnings
warnings.filterwarnings("ignore", category=UserWarning)


class FasterWhisperWrapper:
    def __init__(self, model_size, device, compute_type):
        from faster_whisper import WhisperModel
        print(f"Initializing native FasterWhisperModel({model_size}) on {device.upper()}...")
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type
        )

    def transcribe(self, audio, batch_size=None, language="en"):
        # transcribe returns a generator of segments and transcription info
        segments, info = self.model.transcribe(audio, language=language)
        
        # Format the output segments to match WhisperX's expected structure
        segment_list = []
        for s in segments:
            segment_list.append({
                "text": s.text,
                "start": s.start,
                "end": s.end
            })
            
        return {
            "segments": segment_list,
            "language": info.language
        }


def load_stt_engine():
    # Load faster_whisper directly to avoid whisperx/transformers Pipeline errors in compiled mode
    try:
        return FasterWhisperWrapper(
            model_cfg.stt_model_size,
            device=model_cfg.stt_device,
            compute_type=model_cfg.stt_compute_type
        )
    except Exception as e:
        print(f"[STT Load Warning] Failed loading native faster-whisper wrapper: {e}. Trying whisperx fallback...")
        import whisperx
        return whisperx.load_model(
            model_cfg.stt_model_size,
            device=model_cfg.stt_device,
            compute_type=model_cfg.stt_compute_type,
            language="en",
        )