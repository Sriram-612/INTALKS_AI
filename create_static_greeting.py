import asyncio, os, wave
from utils.production_asr import ProductionSarvamHandler
from dotenv import load_dotenv

load_dotenv()

async def create_static_greeting():
    handler = ProductionSarvamHandler(os.getenv("SARVAM_API_KEY"))
    text = "Hello, this is a Priya calling on behalf of South India Finvest Bank."
    audio_bytes = await handler.synthesize_tts(text, "en-IN")

    os.makedirs("audio_files", exist_ok=True)
    filepath = "audio_files/static_greeting.wav"

    with wave.open(filepath, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(audio_bytes)

    print(f"✅ Static greeting created at {filepath}")

asyncio.run(create_static_greeting())
