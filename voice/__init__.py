"""
Voice Package - TTS (edge-tts) + STT (faster-whisper) integration.
"""
from .tts import EdgeTTS, VoiceConfig, VoiceType, speak
from .stt import FasterWhisperSTT, STTConfig, ModelSize, ComputeType, transcribe_once
from .bridge import VoiceBridge, VoiceSettings, get_voice_bridge

__all__ = [
    # TTS
    'EdgeTTS',
    'VoiceConfig',
    'VoiceType',
    'speak',
    # STT
    'FasterWhisperSTT',
    'STTConfig',
    'ModelSize',
    'ComputeType',
    'transcribe_once',
    # Bridge
    'VoiceBridge',
    'VoiceSettings',
    'get_voice_bridge',
]