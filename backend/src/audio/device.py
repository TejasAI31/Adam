"""Thread-safe PyAudio hardware instantiation."""

import pyaudio

_SHARED_AUDIO = None

def get_shared_audio():
    global _SHARED_AUDIO
    if _SHARED_AUDIO is None:
        _SHARED_AUDIO = pyaudio.PyAudio()
    return _SHARED_AUDIO

class SharedAudioProxy:
    def __getattr__(self, name):
        return getattr(get_shared_audio(), name)

# Global shared PyAudio interface instance (lazily loaded)
SHARED_AUDIO = SharedAudioProxy()