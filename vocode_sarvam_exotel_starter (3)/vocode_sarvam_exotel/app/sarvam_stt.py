import os, requests
from dotenv import load_dotenv

load_dotenv()

SARVAM_STT_URL = os.getenv("SARVAM_STT_URL")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
LANG_CODE = os.getenv("LANG_CODE", "en-IN")
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "16000"))

class SarvamTranscriber:
    """
    Minimal Vocode-compatible transcriber shim.
    You'll call transcribe_chunk() repeatedly with raw PCM/WAV bytes.
    """
    def __init__(self, lang_code: str = None):
        self.lang_code = lang_code or LANG_CODE

    def transcribe_chunk(self, wav_bytes: bytes) -> str:
        headers = {"Authorization": f"Bearer {SARVAM_API_KEY}"}
        files = {"audio": ("chunk.wav", wav_bytes, "audio/wav")}
        data = {"language": self.lang_code, "sample_rate": str(SAMPLE_RATE)}
        r = requests.post(SARVAM_STT_URL, headers=headers, files=files, data=data, timeout=30)
        r.raise_for_status()
        js = r.json()
        return js.get("text", "").strip()
