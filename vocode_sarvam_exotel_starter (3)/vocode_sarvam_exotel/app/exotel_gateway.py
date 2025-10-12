from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from typing import Optional
import asyncio

from .sarvam_stt import SarvamTranscriber
from .sarvam_tts import SarvamSynthesizer
from .llm_openai import OpenAILLM, AnthropicLLM
from .agent_config import COLLECTIONS_SYSTEM_PROMPT

router = APIRouter()

class SimpleVoiceAgent:
    def __init__(self, llm, stt, tts, lang_code="en-IN"):
        self.llm = llm
        self.stt = stt
        self.tts = tts
        self.lang = lang_code
        self.messages = [{"role":"system","content":COLLECTIONS_SYSTEM_PROMPT.format(lang=self.lang)}]

    async def handle_user_text(self, text: str) -> bytes:
        self.messages.append({"role": "user", "content": text})
        reply = self.llm.complete(self.messages)
        self.messages.append({"role": "assistant", "content": reply})
        audio = self.tts.synthesize(reply)
        return audio

@router.websocket("/exotel/media")
async def exotel_media(ws: WebSocket):
    """
    Skeleton for Exotel bidirectional audio.
    - Accept audio frames from Exotel (define exact payload format per Exotel docs).
    - On barge-in: stop any ongoing TTS playback (client-side) and switch to STT.
    - This example assumes Exotel sends small WAV/PCM chunks over WS.
    """
    await ws.accept()
    stt = SarvamTranscriber()
    tts = SarvamSynthesizer()
    # Choose LLM provider based on env
    import os
    llm = OpenAILLM() if os.getenv("LLM_PROVIDER","openai") == "openai" else AnthropicLLM()
    agent = SimpleVoiceAgent(llm, stt, tts)

    try:
        while True:
            # Expect a JSON header or raw bytes; adapt to Exotel's format.
            msg = await ws.receive_bytes()
            # TODO: parse frame metadata if needed (seq, timestamp).
            text = stt.transcribe_chunk(msg)
            if not text:
                continue
            # Generate reply + TTS
            audio_wav = await asyncio.get_event_loop().run_in_executor(None, agent.handle_user_text, text)
            # Send audio bytes back (wrap in a small envelope if Exotel needs it)
            await ws.send_bytes(audio_wav)
    except WebSocketDisconnect:
        return
    except Exception as e:
        await ws.close(code=1011)
