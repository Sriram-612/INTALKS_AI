import os, requests
from dotenv import load_dotenv

load_dotenv()

SARVAM_TTS_URL = os.getenv("SARVAM_TTS_URL")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
LANG_CODE = os.getenv("LANG_CODE", "en-IN")
VOICE_NAME = os.getenv("VOICE_NAME", "female_generic")
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "16000"))

class SarvamSynthesizer:
    """
    Minimal Vocode-compatible synthesizer shim.
    synthesize(text) -> WAV bytes (or stream this in chunks if your TTS supports it).
    """
    def __init__(self, lang_code: str=None, voice_name: str=None):
        self.lang_code = lang_code or LANG_CODE
        self.voice_name = voice_name or VOICE_NAME

    def synthesize(self, text: str) -> bytes:
        headers = {
            "Authorization": f"Bearer {SARVAM_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "audio/wav",
        }
        payload = {
            "text": text,
            "language": self.lang_code,
            "voice": self.voice_name,
            "sample_rate": SAMPLE_RATE,
            "format": "wav",
        }
        r = requests.post(SARVAM_TTS_URL, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        return r.content
