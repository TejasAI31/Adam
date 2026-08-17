"""Thread-safe PyAudio hardware instantiation."""

import pyaudio

# Global shared PyAudio interface instance
SHARED_AUDIO = pyaudio.PyAudio()