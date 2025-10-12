# Vocode + Sarvam + Exotel — Voice Agent Starter

This starter shows how to combine **Vocode** (real-time voice agents) with **Sarvam AI** for **STT/TTS** and a **WebSocket gateway** you can adapt for **Exotel** media streaming. Use **Claude/OpenAI** for the conversational layer.

> You previously tested a CLI bot; this is the real-time server version.

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# fill: OPENAI_API_KEY or ANTHROPIC_API_KEY, SARVAM_API_KEY
# set: LANG_CODE (ta-IN/hi-IN/en-IN), VOICE_NAME, SAMPLE_RATE
uvicorn app.main:app --reload --port 8080
```

### What you get
- **Vocode agent** with:
  - custom **SarvamTranscriber** (streaming STT)
  - custom **SarvamSynthesizer** (streaming/segmented TTS)
  - switchable **Claude/OpenAI** LLM for replies
- **FastAPI WebSocket** at `/exotel/media` (skeleton) to bridge your Exotel bidirectional audio stream
- Collections **system prompt** with consent/ID/PII rules

> **Replace placeholders** for Sarvam endpoints and Exotel frame formats with the specs you have.

## High-level flow
Exotel (SIP/PSTN) → your WS `/exotel/media` → Vocode Agent (Sarvam STT ↔ Claude/OpenAI ↔ Sarvam TTS) → WS back to Exotel.

## Notes
- For lowest latency, use streaming STT and chunked TTS. Cut TTS on barge-in (see `exotel_gateway.py` policy hooks).
- If you prefer Twilio or LiveKit, only the gateway layer changes—the agent stays the same.

