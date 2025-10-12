import os
import asyncio
import base64
import json
import tempfile
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx
import pandas as pd
import requests
import re
import uvicorn
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from fastapi import (Body, FastAPI, File, HTTPException, Request, UploadFile,
                     WebSocket)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from requests.auth import HTTPBasicAuth
from starlette.websockets import WebSocketDisconnect
from typing import Any, Dict, Optional, List

import boto3

# Load environment variables at the very beginning
load_dotenv()

# Import project-specific modules
from database.schemas import (CallStatus, Customer,
                              db_manager, init_database, update_call_status, get_call_session_by_sid,
                              update_customer_call_status_by_phone, update_customer_call_status)
from services.call_management import call_service
from utils import bedrock_client
from utils.agent_transfer import trigger_exotel_agent_transfer
from utils.logger import setup_application_logging, logger
from utils.production_asr import ProductionSarvamHandler
from utils.redis_session import (init_redis, redis_manager,
                                 generate_websocket_session_id)


# --- Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # Initialize logging system first
    setup_application_logging()
    logger.app.info("🚀 Starting Voice Assistant Application...")
    
    # Initialize database
    if init_database():
        logger.app.info("✅ Database initialized successfully")
        logger.database.info("Database connection established")
    else:
        logger.error.error("❌ Database initialization failed")
        logger.database.error("Failed to establish database connection")
    
    # Initialize Redis
    if init_redis():
        logger.app.info("✅ Redis initialized successfully")
    else:
        logger.app.warning("❌ Redis initialization failed - running without session management")
    
    logger.app.info("🎉 Application startup complete!")
    
    yield
    
    # Shutdown
    logger.app.info("🛑 Shutting down Voice Assistant Application...")

app = FastAPI(
    title="Voice Assistant Call Management System",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Dashboard WebSocket Management ---
dashboard_clients: Dict[str, Dict[str, Any]] = {}
dashboard_clients_lock = asyncio.Lock()


async def register_dashboard_client(session_id: str, websocket: WebSocket) -> asyncio.Queue:
    """Store dashboard websocket reference and return a queue for outbound events."""
    event_queue: asyncio.Queue = asyncio.Queue()
    async with dashboard_clients_lock:
        dashboard_clients[session_id] = {"websocket": websocket, "queue": event_queue}
    return event_queue


async def unregister_dashboard_client(session_id: str) -> None:
    """Remove dashboard websocket reference when disconnected."""
    async with dashboard_clients_lock:
        dashboard_clients.pop(session_id, None)


async def broadcast_dashboard_update(event: Dict[str, Any]) -> None:
    """Queue an event for every connected dashboard client."""
    stale_sessions = []
    async with dashboard_clients_lock:
        clients_snapshot = list(dashboard_clients.items())

    for session_id, client in clients_snapshot:
        queue: asyncio.Queue = client["queue"]
        try:
            queue.put_nowait(event)
        except Exception:
            stale_sessions.append(session_id)

    if stale_sessions:
        async with dashboard_clients_lock:
            for session_id in stale_sessions:
                dashboard_clients.pop(session_id, None)


async def push_status_update(
    call_sid: str,
    status: str,
    message: str = "",
    customer_id: Optional[str] = None,
) -> None:
    """Publish a status update to Redis and live dashboard clients."""

    resolved_customer_id = customer_id
    lookup_session = None

    if call_sid and not resolved_customer_id:
        try:
            lookup_session = db_manager.get_session()
            call_session = get_call_session_by_sid(lookup_session, call_sid)
            if call_session and call_session.customer_id:
                resolved_customer_id = str(call_session.customer_id)
        except Exception as lookup_error:
            logger.websocket.error(
                f"❌ Failed to resolve customer for CallSid={call_sid}: {lookup_error}"
            )
        finally:
            if lookup_session:
                lookup_session.close()

    event: Dict[str, Any] = {
        "type": "status_update",
        "call_sid": call_sid,
        "status": status,
        "message": message,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if resolved_customer_id:
        event["customer_id"] = resolved_customer_id

    redis_manager.publish_event(call_sid, event)
    await broadcast_dashboard_update(event)

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
sarvam_handler = ProductionSarvamHandler(SARVAM_API_KEY)

AWS_REGION = os.getenv("AWS_REGION") or "eu-north-1"
CLAUDE_MODEL_ID = os.getenv("CLAUDE_MODEL_ID") or os.getenv("CLAUDE_INTENT_MODEL_ID")
CLAUDE_SYSTEM_PROMPT = (
    os.getenv("CLAUDE_SYSTEM_PROMPT")
    or (
        "You are Priya, a collections specialist calling from Intalks NGN Bank. "
        "Obtain a concrete repayment commitment for the overdue EMI. "
        "Respond using 1-2 short sentences in plain English. "
        "At the end append a tag in brackets:[escalate]"
        "Do not output JSON or code blocks; speak naturally as a human agent."
        "If the input you get is in any other language, give the response also in the same language."
        "no matter the change of languages, stick to the context strictly. Don't give response irrelevantly."
        "Only append [promise] after the customer clearly confirms repayment in a declarative sentence. Do not attach [promise] to your own questions."
        "Reserve [escalate] for situations where the customer has refused repayment five or more times or explicitly asks for escalation; otherwise continue the conversation with [continue]."
    )
)

claude_runtime_client = None
if CLAUDE_MODEL_ID:
    try:
        claude_runtime_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        logger.app.info("🤖 Claude client configured")
    except Exception as claude_err:
        logger.error.error(f"❌ Failed to configure Claude client: {claude_err}")
        claude_runtime_client = None
else:
    logger.app.warning("⚠️ CLAUDE_MODEL_ID not set; Claude voice handoff disabled")


class ClaudeChatSession:
    def __init__(self, call_sid: str, context: Dict[str, Any]) -> None:
        self.call_sid = call_sid
        self.context = context
        self.messages: List[Dict[str, Any]] = []
        base_prompt = CLAUDE_SYSTEM_PROMPT or ""
        context_prompt = (
            "Caller details: name={name}, loan_id={loan_id}, phone={phone}. "
            "The EMI is overdue; ask about repayment timing."
        ).format(
            name=context.get("name") or "customer",
            loan_id=context.get("loan_id") or "unknown",
            phone=context.get("phone") or "unknown",
        )
        self.system_messages: List[Dict[str, str]] = []
        if base_prompt:
            self.system_messages.append({"text": base_prompt})
        self.system_messages.append({"text": context_prompt})

    def send(self, user_text: str) -> str:
        if not claude_runtime_client or not CLAUDE_MODEL_ID:
            raise RuntimeError("Claude runtime client not configured")

        self.messages.append({
            "role": "user",
            "content": [{"text": user_text}]
        })

        try:
            response = claude_runtime_client.converse(
                modelId=CLAUDE_MODEL_ID,
                messages=self.messages,
                system=self.system_messages,
                inferenceConfig={"temperature": 0.3, "maxTokens": 512, "topP": 0.9},
            )
        except (BotoCoreError, ClientError) as err:
            raise RuntimeError(f"Claude converse error: {err}") from err
        except Exception as err:
            raise RuntimeError(f"Unexpected Claude error: {err}") from err

        try:
            output_message = response["output"]["message"]
            parts = output_message.get("content", [])
            assistant_text = "".join(
                part.get("text", "") for part in parts if isinstance(part, dict)
            )
        except Exception as parse_err:
            raise RuntimeError(
                f"Unexpected Claude response format: {parse_err}; raw={response!r}"
            ) from parse_err

        cleaned = assistant_text.strip()
        self.messages.append({
            "role": "assistant",
            "content": [{"text": cleaned}]
        })
        return cleaned


class ClaudeChatManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, ClaudeChatSession] = {}

    def start_session(self, call_sid: str, context: Dict[str, Any]) -> Optional[ClaudeChatSession]:
        if not claude_runtime_client or not CLAUDE_MODEL_ID:
            return None
        try:
            session = ClaudeChatSession(call_sid, context)
            self.sessions[call_sid] = session
            return session
        except Exception as err:
            logger.error.error(f"❌ Unable to start Claude chat for {call_sid}: {err}")
            return None

    def get_session(self, call_sid: str) -> Optional[ClaudeChatSession]:
        return self.sessions.get(call_sid)

    def end_session(self, call_sid: str) -> None:
        self.sessions.pop(call_sid, None)


claude_chat_manager = ClaudeChatManager()


async def claude_reply(chat: ClaudeChatSession, message: str) -> Optional[str]:
    if not chat or not message:
        return None
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, chat.send, message)
    except Exception as err:
        logger.error.error(f"❌ Claude reply failed: {err}")
        return None


def parse_claude_response(raw: str) -> tuple[str, str]:
    if not raw:
        return "", "continue"
    text = raw.strip()
    bracket_pattern = r"\[(continue|promise|escalate)\]\s*$"
    match = re.search(bracket_pattern, text, re.IGNORECASE)
    if match:
        status = match.group(1).lower()
        response = text[:match.start()].strip()
        return response, status
    try:
        data = json.loads(text)
        resp = data.get("response")
        status = data.get("status", "continue")
        if not isinstance(resp, str):
            resp = text
        if not isinstance(status, str):
            status = "continue"
        status = status.lower()
        if status not in {"continue", "promise", "escalate"}:
            status = "continue"
        return resp.strip(), status
    except json.JSONDecodeError:
        logger.websocket.warning("⚠️ Claude returned text without status tag; defaulting to continue")
        return text, "continue"


base_transcript_dir = Path(os.getenv("VOICEBOT_RUNTIME_DIR") or Path(__file__).resolve().parent)
base_transcript_dir = base_transcript_dir.expanduser()
try:
    base_transcript_dir.mkdir(parents=True, exist_ok=True)
except Exception as transcript_dir_err:
    fallback_dir = Path(tempfile.gettempdir()) / "voicebot_transcripts"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    logger.app.warning(
        f"⚠️ Could not create transcript directory at {base_transcript_dir}: {transcript_dir_err}."
        f" Falling back to {fallback_dir}"
    )
    base_transcript_dir = fallback_dir

transcripts_file_env = os.getenv("TRANSCRIPTS_FILE")
if transcripts_file_env:
    TRANSCRIPTS_FILE_PATH = Path(transcripts_file_env).expanduser()
else:
    TRANSCRIPTS_FILE_PATH = base_transcript_dir / "transcripts.txt"

logger.app.info(f"🗒️ Transcript log file: {TRANSCRIPTS_FILE_PATH}")


class TranscriptLogger:
    """Accumulates customer speech and writes to disk after silence gaps."""

    def __init__(self, file_path: Path, call_sid: str, silence_gap: float = 5.0) -> None:
        self.file_path = file_path
        self.call_sid = call_sid
        self.silence_gap = silence_gap
        self.pending_segments: List[str] = []
        self.last_speech_time: Optional[float] = None
        self.header_written = False
        self.customer_name: Optional[str] = None
        self.customer_phone: Optional[str] = None

    def update_customer(self, name: Optional[str] = None, phone: Optional[str] = None) -> None:
        if name:
            self.customer_name = name
        if phone:
            self.customer_phone = phone

    def add_transcript(self, text: str, timestamp: Optional[float] = None) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self.pending_segments.append(cleaned)
        self.last_speech_time = timestamp or time.time()
        # Write immediately for real-time transcript updates
        self.flush(force=True, current_time=self.last_speech_time)

    def maybe_flush(self, current_time: Optional[float] = None) -> None:
        if not self.pending_segments or not self.last_speech_time:
            return
        current_time = current_time or time.time()
        if current_time - self.last_speech_time >= self.silence_gap:
            self.flush(force=True, current_time=current_time)

    def flush(self, force: bool = False, current_time: Optional[float] = None) -> None:
        if not self.pending_segments:
            return

        current_time = current_time or time.time()
        if not force and self.last_speech_time and (current_time - self.last_speech_time) < self.silence_gap:
            return

        entry_text = " ".join(self.pending_segments).strip()
        if not entry_text:
            self.pending_segments.clear()
            return

        self._ensure_header()
        timestamp = datetime.utcnow().isoformat()
        line = f"{timestamp} | {entry_text}\n"
        self._write_line(line)
        logger.websocket.info(f"📝 Transcript segment saved ({len(entry_text)} chars) for CallSid={self.call_sid}")
        logger.call.info(
            f"[TRANSCRIPT] CallSid={self.call_sid} | {entry_text}",
            extra={"call_sid": self.call_sid}
        )
        self.pending_segments.clear()
        self.last_speech_time = None

    def _ensure_header(self) -> None:
        if self.header_written:
            return

        timestamp = datetime.utcnow().isoformat()
        details = []
        if self.customer_name:
            details.append(f"Customer: {self.customer_name}")
        if self.customer_phone:
            details.append(f"Phone: {self.customer_phone}")

        header_main = f"\n=== Call {self.call_sid} | Started {timestamp}"
        if details:
            header_main += " | " + " | ".join(details)
        header = header_main + " ===\n"
        self._write_line(header)
        self.header_written = True

    def _write_line(self, text: str) -> None:
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with self.file_path.open("a", encoding="utf-8") as file:
                file.write(text)
        except Exception as exc:
            logger.error.error(f"❌ Failed to write transcript log: {exc}")

# --- Constants ---
BUFFER_DURATION_SECONDS = 1.0
AGENT_RESPONSE_BUFFER_DURATION = 5.0  # Wait longer for user to answer agent connect question
MIN_AUDIO_BYTES = 3200  # ~0.2s at 8kHz 16-bit mono; ignore too-short buffers
CONFIRMATION_SILENCE_SECONDS = 1.0
CLAUDE_SILENCE_SECONDS = 3.0
MAX_CLAUDE_TURNS = int(os.getenv("CLAUDE_MAX_TURNS", "6"))
CLAUDE_REFUSAL_THRESHOLD = int(os.getenv("CLAUDE_REFUSAL_THRESHOLD", "5"))
ESCALATION_CLOSING_MESSAGE = "Our senior manager will contact you soon. Thank you."

# --- Multilingual Prompt Templates with SSML and Pauses ---
GREETING_TEMPLATE = {
    "en-IN": "Hello, this is Priya, calling on behalf of South India Finvest Bank. Am I speaking with Mr. {name}?",
    "hi-IN": "नमस्ते, मैं प्रिया हूं, और साउथ इंडिया फिनवेस्ट बैंक की ओर से बात कर रही हूं। क्या मैं श्री/सुश्री {name} से बात कर रही हूं?",
    "ta-IN": "வணக்கம், நான் பிரியா, இது சவுத் இந்தியா ஃபின்வெஸ்ட் வங்கியிலிருந்து அழைப்பு. திரு/திருமதி {name} பேசுகிறீர்களா?",
    "te-IN": "హలో, నేను ప్రియ మాట్లాడుతున్నాను, ఇది సౌత్ ఇండియా ఫిన్‌వెస్ట్ బ్యాంక్ నుండి కాల్. మిస్టర్/మిసెస్ {name} మాట్లాడుతున్నారా?",
    "ml-IN": "നമസ്കാരം, ഞാൻ പ്രിയയാണ്, സൗത്ത് ഇന്ത്യ ഫിൻവെസ്റ്റ് ബാങ്കിന്റെ ഭാഗമായാണ് വിളിച്ചത്. {name} ആണോ സംസാരിക്കുന്നത്?",
    "gu-IN": "નમસ્તે, હું પ્રિયા છું, સાઉથ ઇન્ડિયા ફિનવેસ્ટ બેંક તરફથી બોલી રહી છું. શું હું શ્રી {name} સાથે વાત કરી રહી છું?",
    "mr-IN": "नमस्कार, मी प्रिया बोलत आहे, साउथ इंडिया फिनवेस्ट बँकेकडून. मी श्री {name} शी बोलत आहे का?",
    "bn-IN": "নমস্কার, আমি প্রিয়া, সাউথ ইন্ডিয়া ফিনভেস্ট ব্যাংকের পক্ষ থেকে ফোন করছি। আমি কি {name} এর সাথে কথা বলছি?",
    "kn-IN": "ನಮಸ್ಕಾರ, ನಾನು ಪ್ರಿಯಾ, ಸೌತ್ ಇಂಡಿಯಾ ಫಿನ್‌ವೆಸ್ಟ್ ಬ್ಯಾಂಕ್‌ನಿಂದ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇನೆ. ನಾನು ಶ್ರಿ {name} ಅವರೊಂದಿಗೆ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆವಾ?",
    "pa-IN": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਮੈਂ ਪ੍ਰਿਆ ਹਾਂ, ਸਾਊਥ ਇੰਡੀਆ ਫਿਨਵੈਸਟ ਬੈਂਕ ਵੱਲੋਂ ਗੱਲ ਕਰ ਰਹੀ ਹਾਂ। ਕੀ ਮੈਂ ਸ੍ਰੀ {name} ਨਾਲ ਗੱਲ ਕਰ ਰਹੀ ਹਾਂ?",
    "or-IN": "ନମସ୍କାର, ମୁଁ ପ୍ରିୟା, ସାଉଥ୍ ଇଣ୍ଡିଆ ଫିନଭେଷ୍ଟ ବ୍ୟାଙ୍କରୁ କଥାହୁଁଛି। ମୁଁ {name} ସହିତ କଥାହୁଁଛି କି?",
}

EMI_DETAILS_PART1_TEMPLATE = {
    "en-IN": "Thank you. I am calling about your loan ending in {loan_id}, which has an outstanding EMI of ₹{amount} due on {due_date}. I understand payments can be delayed. I am here to help you avoid any further impact.",
    "hi-IN": "धन्यवाद। मैं आपके लोन (अंतिम चार अंक {loan_id}) के बारे में कॉल कर रही हूँ, जिसकी बकाया ईएमआई ₹{amount} है, जो {due_date} को देय है। मैं समझती हूँ कि भुगतान में देरी हो सकती है। मैं आपकी मदद के लिए यहाँ हूँ ताकि आगे कोई समस्या न हो।",
    "ta-IN": "நன்றி. உங்கள் கடன் (கடைசி நான்கு இலக்கங்கள் {loan_id}) குறித்து அழைக்கிறேன், அதற்கான நிலுவை EMI ₹{amount} {due_date} அன்று செலுத்த வேண்டியது உள்ளது. தாமதம் ஏற்படலாம் என்பதை புரிந்துகொள்கிறேன். மேலும் பாதிப்பு ஏற்படாமல் உதவ நான் இங்கே இருக்கிறேன்.",
    "te-IN": "ధన్యవాదాలు. మీ రుణం ({loan_id} తో ముగిసే) గురించి కాల్ చేస్తున్నాను, దీనికి ₹{amount} EMI {due_date} నాటికి బాకీగా ఉంది. చెల్లింపులు ఆలస్యం కావచ్చు. మరింత ప్రభావం లేకుండా మీకు సహాయం చేయడానికి నేను ఇక్కడ ఉన్నాను.",
    "ml-IN": "നന്ദി. നിങ്ങളുടെ വായ്പ ({loan_id} അവസാനിക്കുന്ന) സംബന്ധിച്ച് വിളിക്കുന്നു, അതിന് ₹{amount} EMI {due_date} ന് ബാക്കി ഉണ്ട്. പണമടയ്ക്കുന്നതിൽ വൈകിപ്പോകാം. കൂടുതൽ പ്രശ്നങ്ങൾ ഒഴിവാക്കാൻ ഞാൻ സഹായിക്കാൻ ഇവിടെ ഉണ്ട്.",
    "gu-IN": "આભાર. હું તમારા લોન ({loan_id}) વિશે કોલ કરી રહી છું, જેમાં ₹{amount} EMI {due_date} સુધી બાકી છે. ચુકવણીમાં વિલંબ થઈ શકે છે. વધુ અસરથી બચવા માટે હું અહીં છું.",
    "mr-IN": "धन्यवाद. मी तुमच्या कर्ज ({loan_id}) विषयी कॉल करत आहे, ज्याची ₹{amount} EMI {due_date} रोजी बाकी आहे. पेमेंटमध्ये उशीर होऊ शकतो. पुढील परिणाम टाळण्यासाठी मी मदतीसाठी येथे आहे.",
    "bn-IN": "ধন্যবাদ. আমি আপনার ঋণ ({loan_id}) সম্পর্কে ফোন করছি, যার ₹{amount} EMI {due_date} তারিখে বাকি আছে। পেমেন্টে দেরি হতে পারে। আরও সমস্যা এড়াতে আমি সাহায্য করতে এখানে আছি।",
    "kn-IN": "ಧನ್ಯವಾದಗಳು. ನಿಮ್ಮ ಸಾಲ ({loan_id}) ಬಗ್ಗೆ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇನೆ, ಇದಕ್ಕೆ ₹{amount} EMI {due_date} ರಂದು ಬಾಕಿ ಇದೆ. ಪಾವತಿಯಲ್ಲಿ ವಿಳಂಬವಾಗಬಹುದು. ಹೆಚ್ಚಿನ ಪರಿಣಾಮ ತಪ್ಪಿಸಲು ನಾನು ಸಹಾಯ ಮಾಡಲು ಇಲ್ಲಿದ್ದೇನೆ.",
    "pa-IN": "ਧੰਨਵਾਦ. ਮੈਂ ਤੁਹਾਡੇ ਲੋਨ ({loan_id}) ਬਾਰੇ ਕਾਲ ਕਰ ਰਹੀ ਹਾਂ, ਜਿਸ ਵਿੱਚ ₹{amount} EMI {due_date} ਤੱਕ ਬਕਾਇਆ ਹੈ। ਭੁਗਤਾਨ ਵਿੱਚ ਦੇਰੀ ਹੋ ਸਕਦੀ ਹੈ. ਹੋਰ ਪ੍ਰਭਾਵ ਤੋਂ ਬਚਣ ਲਈ ਮੈਂ ਇੱਥੇ ਹਾਂ।",
    "or-IN": "ଧନ୍ୟବାଦ. ମୁଁ ଆପଣଙ୍କର ଋଣ ({loan_id}) ବିଷୟରେ କଥାହୁଁଛି, ଯାହାର ₹{amount} EMI {due_date} ରେ ବକାୟା ଅଛି। ଦେୟ ଦେବାରେ ବିଳମ୍ବ ହେବା ସମ୍ଭବ. ଅଧିକ ସମସ୍ୟା ରୋକିବା ପାଇଁ ମୁଁ ଏଠାରେ ଅଛି।"
}

EMI_DETAILS_PART2_TEMPLATE = {
    "en-IN": "Please note. If this EMI remains unpaid, it may be reported to the credit bureau, which can affect your credit score. Continued delay may also classify your account as delinquent, leading to penalty charges or collection notices.",
    "hi-IN": "कृपया ध्यान दें। यदि यह ईएमआई बकाया रहती है, तो इसे क्रेडिट ब्यूरो को रिपोर्ट किया जा सकता है, जिससे आपका क्रेडिट स्कोर प्रभावित हो सकता है। लगातार देरी से आपका खाता डिफॉल्टर घोषित हो सकता है, जिससे पेनल्टी या कलेक्शन नोटिस आ सकते हैं।",
    "ta-IN": "தயவு செய்து கவனிக்கவும். இந்த EMI செலுத்தப்படவில்லை என்றால், அது கிரெடிட் ப்யூரோவுக்கு தெரிவிக்கப்படலாம், இது உங்கள் கிரெடிட் ஸ்கோருக்கு பாதிப்பை ஏற்படுத்தும். தொடர்ந்த தாமதம் உங்கள் கணக்கை குற்றவாளியாக வகைப்படுத்தும், அபராதம் அல்லது வசூல் நோட்டீஸ் வரலாம்.",
    "te-IN": "దయచేసి గమనించండి. ఈ EMI చెల్లించకపోతే, అది క్రెడిట్ బ్యూరోకు నివేదించబడవచ్చు, ఇది మీ క్రెడిట్ స్కోర్‌ను ప్రభావితం చేయవచ్చు. కొనసాగుతున్న ఆలస్యం వల్ల మీ ఖాతా డిఫాల్ట్‌గా పరిగణించబడుతుంది, జరిమానాలు లేదా వసూలు నోటీసులు రావచ్చు.",
    "ml-IN": "ദയവായി ശ്രദ്ധിക്കുക. ഈ EMI അടയ്ക്കപ്പെടാതെ പോയാൽ, അത് ക്രെഡിറ്റ് ബ്യൂറോയ്ക്ക് റിപ്പോർട്ട് ചെയ്യപ്പെടാം, ഇത് നിങ്ങളുടെ ക്രെഡിറ്റ് സ്കോറിനെ ബാധിക്കും. തുടർച്ചയായ വൈകിപ്പിക്കൽ നിങ്ങളുടെ അക്കൗണ്ടിനെ ഡിഫോൾട്ട് ആയി കണക്കാക്കും, പിഴയോ കലക്ഷൻ നോട്ടീസോ വരാം.",
    "gu-IN": "મહેરબાની કરીને નોંધો. જો આ EMI બાકી રહેશે, તો તે ક્રેડિટ બ્યુરોને રિપોર્ટ થઈ શકેછે, જે તમારા ક્રેડિટ સ્કોરને અસર કરી શકેછે. સતત વિલંબથી તમારું ખાતું ડિફોલ્ટ તરીકે ગણાય શકેછે, દંડ અથવા વસૂલાત નોટિસ આવી શકેછે.",
    "mr-IN": "कृपया लक्षात घ्या. ही EMI बकाया राहिल्यास, ती क्रेडिट ब्युरोला रिपोर्ट केली जाऊ शकते, ज्यामुळे तुमचा क्रेडिट स्कोर प्रभावित होऊ शकतो. सततच्या विलंबामुळे तुमचे खाते डिफॉल्टर म्हणून घोषित केले जाऊ शकते, दंड किंवा वसुली नोटीस येऊ शकते.",
    "bn-IN": "দয়া করে লক্ষ্য করুন. এই EMI বকেয়া থাকলে, এটি ক্রেডিট ব্যুরোতে রিপোর্ট করা হতে পারে, যা আপনার ক্রেডিট স্কোরকে প্রভাবিত করতে পারে। ক্রমাগত দেরিতে আপনার অ্যাকাউন্ট ডিফল্ট হিসাবে বিবেচিত হতে পারে, জরিমানা বা সংগ্রহের নোটিশ আসতে পারে।",
    "kn-IN": "ದಯವಿಟ್ಟು ಗಮನಿಸಿ. ಈ EMI ಪಾವತಿಯಾಗದೆ ಇದ್ದರೆ, ಅದು ಕ್ರೆಡಿಟ್ ಬ್ಯೂರೋಗೆ ವರದಿ ಮಾಡಬಹುದು, ಇದು ನಿಮ್ಮ ಕ್ರೆಡಿಟ್ ಸ್ಕೋರ್‌ಗೆ ಪರಿಣಾಮ ಬೀರುತ್ತದೆ. ನಿರಂತರ ವಿಳಂಬದಿಂದ ನಿಮ್ಮ ಖಾತೆಯನ್ನು ಡಿಫಾಲ್ಟ್ ಎಂದು ಪರಿಗಣಿಸಬಹುದು, ದಂಡ ಅಥವಾ ಸಂಗ್ರಹಣಾ ಸೂಚನೆಗಳು ಬರಬಹುದು.",
    "pa-IN": "ਕਿਰਪਾ ਕਰਕੇ ਧਿਆਨ ਦਿਓ. ਜੇ ਇਹ EMI ਬਕਾਇਆ ਰਹੰਦੀ ਹੈ, ਤਾਂ ਇਹਨੂੰ ਕਰੈਡਿਟ ਬਿਊਰੋ ਨੂੰ ਰਿਪੋਰਟ ਕੀਤਾ ਜਾ ਸਕਦਾ ਹੈ, ਜੁਰਮਾਨਾ ਨਾਲ ਤੁਹਾਡਾ ਕਰੈਡਿਟ ਸਕੋਰ ਪ੍ਰਭਾਵਿਤ ਹੋ ਸਕਦਾ ਹੈ। ਲਗਾਤਾਰ ਦੇਰੀ ਨਾਲ ਤੁਹਾਡਾ ਖਾਤਾ ਡਿਫੌਲਟਰ ਘੋਸ਼ਿਤ ਕੀਤਾ ਜਾ ਸਕਦਾ ਹੈ, ਜੁਰਮਾਨਾ ਜਾਂ ਕਲੈਕਸ਼ਨ ਨੋਟਿਸ ਆ ਸਕਦੇ ਹਨ।",
    "or-IN": "ଦୟାକରି ଧ୍ୟାନ ଦିଅନ୍ତୁ. ଏହି EMI ବକାୟା ରହିଲେ, ଏହା କ୍ରେଡିଟ୍ ବ୍ୟୁରୋକୁ ରିପୋର୍ଟ କରାଯାଇପାରେ, ଯାହା ଆପଣଙ୍କର କ୍ରେଡିଟ୍ ସ୍କୋରକୁ ପ୍ରଭାବିତ କରିପାରେ। ଲଗାତାର ବିଳମ୍ବ ଆପଣଙ୍କର ଖାତାକୁ ଡିଫଲ୍ଟ୍ ଭାବରେ ଘୋଷଣା କରିପାରେ, ଜରିମାନା କିମ୍ବା କଲେକ୍ସନ୍ ନୋଟିସ୍ ଆସିପାରେ।"
}

AGENT_CONNECT_TEMPLATE = {
    "en-IN": "If you are facing difficulties, we have options like part payments or revised EMI plans. Would you like me to connect you to one of our agents to assist you better?",
    "hi-IN": "यदि आपको कठिनाई हो रही है, तो हमारे पास आंशिक भुगतान या संशोधित ईएमआई योजनाओं जैसे विकल्प हैं। क्या आप चाहेंगे कि मैं आपको हमारे एजेंट से जोड़ दूं, ताकि वे आपकी मदद कर सकें?",
    "ta-IN": "உங்களுக்கு சிரமம் இருந்தால், பகுதி கட்டணம் அல்லது திருத்தப்பட்ட EMI திட்டங்கள் போன்ற விருப்பங்கள் உள்ளன. உங்களுக்கு உதவ எங்கள் ஏஜெண்டுடன் இணைக்க விரும்புகிறீர்களா?",
    "te-IN": "మీకు ఇబ్బంది ఉంటే, భాగ చెల్లింపులు లేదా సవరించిన EMI ప్లాన్‌లు వంటి ఎంపికలు ఉన్నాయి. మీకు సహాయం చేయడానికి మా ఏజెంట్‌ను కలిపించాలా?",
    "ml-IN": "നിങ്ങൾക്ക് ബുദ്ധിമുട്ട് ഉണ്ടെങ്കിൽ, ഭാഗിക പണമടയ്ക്കൽ അല്ലെങ്കിൽ പുതുക്കിയ EMI പദ്ധതികൾ പോലുള്ള ഓപ്ഷനുകൾ ഞങ്ങൾക്കുണ്ട്. നിങ്ങളെ സഹായിക്കാൻ ഞങ്ങളുടെ ഏജന്റുമായി ബന്ധിപ്പിക്കണോ?",
    "gu-IN": "જો તમને મુશ્કેલી હોય, તો અમારી પાસે ભાગ ચુકવણી અથવા સુધારેલી EMI યોજનાઓ જેવા વિકલ્પો છે. શું હું તમને અમારા એજન્ટ સાથે જોડું?",
    "mr-IN": "तुम्हाला अडचण असल्यास, आमच्याकडे भाग पेमेन्ट किंवा सुधारित EMI योजना आहेत. मी तुम्हाला आमच्या एजंटशी जोडू का?",
    "bn-IN": "আপনার অসুবিধা হলে, আমাদের কাছে আংশিক পেমেন্ট বা সংশোধিত EMI প্ল্যানের মতো বিকল্প রয়েছে। আপনাকে সাহায্য করতে আমাদের এজেন্টের সাথে সংযোগ করব?",
    "kn-IN": "ನಿಮಗೆ ತೊಂದರೆ ಇದ್ದರೆ, ಭಾಗ ಪಾವತಿ ಅಥವಾ ಪರಿಷ್ಕೃತ EMI ಯೋಜನೆಗಳೂ ನಮ್ಮ ಬಳಿ ಇವೆ. ನಿಮಗೆ ಸಹಾಯ ಮಾಡಲು ನಮ್ಮ ಏಜೆಂಟ್‌ಗೆ ಸಂಪರ್ಕ ಮಾಡಬೇಕೆ?",
    "pa-IN": "ਜੇ ਤੁਹਾਨੂੰ ਮੁਸ਼ਕਲ ਆ ਰਹੀ ਹੈ, ਤਾਂ ਸਾਡੇ ਕੋਲ ਹਿੱਸਾ ਭੁਗਤਾਨ ਜਾਂ ਸੋਧੀ EMI ਯੋਜਨਾਵਾਂ ਵਰਗੇ ਵਿਕਲਪ ਹਨ। ਕੀ ਮੈਂ ਤੁਹਾਨੂੰ ਸਾਡੇ ਏਜੰਟ ਨਾਲ ਜੋੜਾਂ?",
    "or-IN": "ଯଦି ଆପଣଙ୍କୁ ସମସ୍ୟା ହେଉଛି, ଆମ ପାଖରେ ଅଂଶିକ ପେମେଣ୍ଟ କିମ୍ବା ସଂଶୋଧିତ EMI ଯୋଜନା ଅଛି। ଆପଣଙ୍କୁ ସହଯୋଗ କରିବା ପାଇଁ ଆମ ଏଜେଣ୍ଟ ସହିତ ଯୋଗାଯୋଗ କରିବି?"
}

GOODBYE_TEMPLATE = {
    "en-IN": "I understand. If you change your mind, please call us back. Thank you. Goodbye.",
    "hi-IN": "मैं समझती हूँ। यदि आप अपना विचार बदलते हैं, तो कृपया हमें वापस कॉल करें। धन्यवाद। अलविदा।",
    "ta-IN": "நான் புரிந்துகொள்கிறேன். நீங்கள் உங்கள் மனதை மாற்றினால், தயவுசெய்து எங்களை மீண்டும் அழைக்கவும். நன்றி. விடைபெறுகிறேன்.",
    "te-IN": "నాకు అర్థమైంది. మీరు మీ అభిప్రాయాన్ని మార్చుకుంటే, దయచేసి మమ్మల్ని తిరిగి కాల్ చేయండి. ధన్యవాదాలు. వీడ్కోలు.",
    "ml-IN": "ഞാൻ മനസ്സിലാക്കുന്നു. നിങ്ങൾ അഭിപ്രായം മാറ്റിയാൽ, ദയവായി ഞങ്ങളെ വീണ്ടും വിളിക്കുക. നന്ദി. വിട.",
    "gu-IN": "હું સમજું છું. જો તમે તમારો મન બદલો, તો કૃપા કરીને અમને પાછા કોલ કરો. આભાર. અલવિદા.",
    "mr-IN": "मी समजते. तुम्ही तुमचा निर्णय बदलल्यास, कृपया आम्हाला पुन्हा कॉल करा. धन्यवाद. गुडबाय.",
    "bn-IN": "আমি বুঝতে পারছি. আপনি যদি মত পরিবর্তন করেন, দয়া করে আমাদের আবার কল করুন। ধন্যবাদ। বিদায়।",
    "kn-IN": "ನಾನು ಅರ್ಥಮಾಡಿಕೊಂಡೆ. ನೀವು ನಿಮ್ಮ ಅಭిಪ్ರಾಯವನ್ನು ಬದಲಾಯಿಸಿದರೆ, ದಯವಿಟ್ಟು ನಮಗೆ ಮತ್ತೆ ಕರೆ ಮಾಡಿ. ಧನ್ಯವಾದಗಳು. ವಿದಾಯ.",
    "pa-IN": "ਧੰਨਵਾਦ. ਮੈਂ ਤੁਹਾਡੇ ਲੋਨ ({loan_id}) ਬਾਰੇ ਕਾਲ ਕਰ ਰਹੀ ਹਾਂ, ਜਿਸ ਵਿੱਚ ₹{amount} EMI {due_date} ਤੱਕ ਬਕਾਇਆ ਹੈ। ਭੁਗਤਾਨ ਵਿੱਚ ਦੇਰੀ ਹੋ ਸਕਦੀ ਹੈ. ਹੋਰ ਪ੍ਰਭਾਵ ਤੋਂ ਬਚਣ ਲਈ ਮੈਂ ਇੱਥੇ ਹਾਂ।",
    "or-IN": "ଧନ୍ୟବାଦ. ମୁଁ ଆପଣଙ୍କର ଋଣ ({loan_id}) ବିଷୟରେ କଥାହୁଁଛି, ଯାହାର ₹{amount} EMI {due_date} ରେ ବକାୟା ଅଛି। ଦେୟ ଦେବାରେ ବିଳମ୍ବ ହେବା ସମ୍ଭବ. ଅଧିକ ସମସ୍ୟା ରୋକିବା ପାଇଁ ମୁଁ ଏଠାରେ ଅଛି।"
}

SPEAK_NOW_PROMPT = {
    "en-IN": "You can speak now.",
    "hi-IN": "अब आप बोल सकते हैं।",
    "ta-IN": "நீங்கள் இப்போது பேசலாம்.",
    "te-IN": "మీరు ఇప్పుడు మాట్లాడవచ్చు.",
    "ml-IN": "നിങ്ങൾക്ക് ഇപ്പോൾ സംസാരിക്കാം.",
    "gu-IN": "તમે હવે બોલી શકો છો.",
    "mr-IN": "आपण आता बोलू शकता.",
    "bn-IN": "আপনি এখন কথা বলতে পারেন।",
    "kn-IN": "ನೀವು ಈಗ ಮಾತನಾಡಬಹುದು.",
    "pa-IN": "ਤੁਸੀਂ ਹੁਣ ਗੱਲ ਕਰ ਸਕਦੇ ਹੋ।",
    "or-IN": "ଆପଣ ଏବେ କହିପାରିବେ।",
}

# --- TTS & Audio Helper Functions ---

async def play_transfer_to_agent(websocket, customer_number: str, call_sid: str, customer_name: str = None):
    """
    Plays a transfer message to the customer, then triggers Exotel agent transfer.
    Updates DB and notifies frontend.
    """
    try:
        logger.websocket.info(f"🤝 Starting agent transfer for CallSid={call_sid}, Customer={customer_number}")

        # 1. Play transfer message via TTS
        transfer_message = "Please wait while I transfer your call to an agent."
        await play_audio_message(websocket, transfer_message, language_code="en-IN")
        await asyncio.sleep(2)  # allow message to play

        # 2. Get agent number from environment
        agent_number = os.getenv("AGENT_PHONE_NUMBER")
        if not agent_number:
            logger.error.error("❌ No AGENT_PHONE_NUMBER set in environment variables")
            return

        # 3. Trigger Exotel transfer
        await trigger_exotel_agent_transfer(customer_number, agent_number)
        logger.websocket.info(f"📞 Exotel agent transfer initiated: {customer_number} → {agent_number}")

        # 4. Update DB with agent transfer status
        session = db_manager.get_session()
        customer_id_event: Optional[str] = None
        try:
            call_session = update_call_status(
                session=session,
                call_sid=call_sid,
                status=CallStatus.AGENT_TRANSFER,
                message=f"Agent transfer initiated for {customer_name or customer_number}",
                extra_data={"agent_number": agent_number}
            )

            if call_session and call_session.customer_id:
                customer_id_event = str(call_session.customer_id)
                update_customer_call_status(
                    session,
                    customer_id_event,
                    CallStatus.AGENT_TRANSFER
                )

            logger.database.info(f"✅ DB updated with AGENT_TRANSFER for CallSid {call_sid}")
        finally:
            session.close()

        # 5. Notify frontend (dashboard) about transfer
        try:
            await push_status_update(
                call_sid,
                "agent_transfer",
                "Agent transfer initiated after answering",
                customer_id=customer_id_event,
            )
            logger.websocket.info("📡 Agent transfer event published to frontend")
        except Exception as e:
            logger.websocket.error(f"❌ Failed to notify frontend about agent transfer: {e}")

    except Exception as e:
        logger.error.error(f"❌ play_transfer_to_agent failed: {e}")


async def stream_audio_to_websocket(websocket, audio_bytes):
    """Send synthesized audio to Exotel/Twilio-style passthru websocket."""
    if not audio_bytes:
        logger.websocket.warning("⚠️ stream_audio_to_websocket called with empty audio payload")
        return

    if websocket.client_state.name not in {"CONNECTED", "CONNECTING"}:
        logger.websocket.warning(
            f"⚠️ WebSocket not connected (state={websocket.client_state.name}); skipping audio stream"
        )
        return

    stream_sid = getattr(websocket, "stream_sid", None) or "default"
    track = getattr(websocket, "stream_track", "outbound")

    chunk_size = 320  # 20ms at 8kHz mono 16-bit PCM
    total_chunks = (len(audio_bytes) + chunk_size - 1) // chunk_size
    logger.websocket.info(
        f"📡 Streaming {len(audio_bytes)} bytes over websocket in {total_chunks} chunks (streamSid={stream_sid})"
    )

    try:
        for index in range(total_chunks):
            offset = index * chunk_size
            chunk = audio_bytes[offset:offset + chunk_size]
            if not chunk:
                continue

            if len(chunk) < chunk_size:
                chunk = chunk + b"\x00" * (chunk_size - len(chunk))

            payload = base64.b64encode(chunk).decode("ascii")
            message = {
                "event": "media",
                "streamSid": stream_sid,
                "media": {
                    "track": track,
                    "chunk": str(index + 1),
                    "timestamp": str(index * 20),  # ms assuming 20ms per chunk
                    "payload": payload,
                },
            }

            try:
                await websocket.send_json(message)
            except WebSocketDisconnect:
                logger.websocket.warning("⚠️ WebSocket disconnected during audio stream; stopping playback")
                return
            except RuntimeError as runtime_err:
                logger.websocket.warning(f"⚠️ WebSocket send failed (runtime error: {runtime_err}); stopping playback")
                return

            # Stop if websocket transitioned to closed states
            if websocket.client_state.name not in {"CONNECTED", "CONNECTING"}:
                logger.websocket.info(f"ℹ️ WebSocket state changed to {websocket.client_state.name}; ending audio stream")
                return

            # Pace the chunks to 20ms (Exotel expects near real-time pacing)
            await asyncio.sleep(0.02)

        buffer_time = min(2.0, (len(audio_bytes) / 16000.0) * 0.1)
        if buffer_time > 0:
            await asyncio.sleep(buffer_time)

        # Signal end-of-audio to the remote media stream so it can reopen the mic
        try:
            mark_message = {
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {"name": "audio_complete"},
            }
            await websocket.send_json(mark_message)
            logger.websocket.debug("📍 Sent audio_complete mark to stream")
        except (WebSocketDisconnect, RuntimeError):
            logger.websocket.debug("ℹ️ Unable to send audio_complete mark; websocket already closed")

        logger.websocket.info("✅ Completed audio stream over websocket")
    except WebSocketDisconnect:
        logger.websocket.warning("⚠️ WebSocket disconnected while streaming; audio truncated")
    except RuntimeError as runtime_err:
        logger.websocket.warning(f"⚠️ RuntimeError while streaming audio: {runtime_err}")
    except Exception as exc:
        logger.error.error(f"❌ Error streaming audio to websocket: {exc}")
        raise


async def stream_audio_to_websocket_not_working(websocket, audio_bytes):
    # Legacy wrapper retained for backward compatibility; delegates to the new implementation.
    await stream_audio_to_websocket(websocket, audio_bytes)

async def greeting_template_play(websocket, customer_info, lang: str):
    """Plays the personalized greeting in the detected language."""
    logger.tts.info("greeting_template_play")
    greeting = GREETING_TEMPLATE.get(lang, GREETING_TEMPLATE["en-IN"]).format(name=customer_info.get('name', 'there'))
    logger.tts.info(f"🔁 Converting personalized greeting: {greeting}")
    
    # Use new TTS method that handles rate limiting and error recovery
    audio_bytes = await sarvam_handler.synthesize_tts(greeting, lang)
    await stream_audio_to_websocket(websocket, audio_bytes)

async def play_did_not_hear_response(websocket, lang: str):
    """Plays a prompt when the initial response is not heard."""
    prompt_text = "I'm sorry, I didn't hear your response. This call is regarding your loan account. If this is a convenient time to talk, please say 'yes'."
    logger.tts.info(f"🔁 Converting 'didn't hear' prompt: {prompt_text}")
    # Use regular TTS with translation since this is English text
    audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
    await stream_audio_to_websocket(websocket, audio_bytes)

async def play_emi_details_part1(websocket, customer_info, lang: str):
    """Plays the first part of EMI details."""
    try:
        prompt_text = EMI_DETAILS_PART1_TEMPLATE.get(
            lang, EMI_DETAILS_PART1_TEMPLATE["en-IN"]
        ).format(
            loan_id=customer_info.get('loan_id', 'XXXX'),
            amount=customer_info.get('amount', 'a certain amount'),
            due_date=customer_info.get('due_date', 'a recent date')
        )
        logger.tts.info(f"🔁 Converting EMI part 1: {prompt_text}")
        audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
        await stream_audio_to_websocket(websocket, audio_bytes)
    except Exception as e:
        logger.tts.error(f"❌ Error in EMI part 1: {e}")
        raise

async def play_emi_details_part2(websocket, customer_info, lang: str):
    """Plays the second part of EMI details."""
    try:
        prompt_text = EMI_DETAILS_PART2_TEMPLATE.get(lang, EMI_DETAILS_PART2_TEMPLATE["en-IN"])
        logger.tts.info(f"🔁 Converting EMI part 2: {prompt_text}")
        audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
        await stream_audio_to_websocket(websocket, audio_bytes)
    except Exception as e:
        logger.tts.error(f"❌ Error in EMI part 2: {e}")
        raise

async def play_agent_connect_question(websocket, lang: str):
    """Asks the user if they want to connect to a live agent."""
    prompt_text = AGENT_CONNECT_TEMPLATE.get(lang, AGENT_CONNECT_TEMPLATE["en-IN"])
    logger.tts.info(f"🔁 Converting agent connect question: {prompt_text}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
    await stream_audio_to_websocket(websocket, audio_bytes)

async def play_goodbye_after_decline(websocket, lang: str):
    """Plays a goodbye message if the user declines agent connection."""
    prompt_text = GOODBYE_TEMPLATE.get(lang, GOODBYE_TEMPLATE["en-IN"])
    logger.tts.info(f"🔁 Converting goodbye after decline: {prompt_text}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
    await stream_audio_to_websocket(websocket, audio_bytes)

async def play_speak_now_prompt(websocket, lang: str) -> None:
    """Tells the caller they can start speaking now."""
    prompt_text = SPEAK_NOW_PROMPT.get(lang, SPEAK_NOW_PROMPT["en-IN"])
    logger.tts.info(f"🔁 Converting speak-now prompt: {prompt_text}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
    if not audio_bytes:
        logger.tts.error("❌ Speak-now prompt synthesis returned no audio")
        return
    await stream_audio_to_websocket(websocket, audio_bytes)


def _loan_suffix(loan_id: Optional[str]) -> str:
    if not loan_id:
        return "unknown"
    digits = "".join(ch for ch in str(loan_id) if ch.isdigit())
    if not digits:
        digits = str(loan_id)
    return digits[-4:] if len(digits) >= 4 else digits


async def play_confirmation_prompt(websocket, customer_info: Dict[str, Any]) -> None:
    name = customer_info.get("name") or "there"
    loan_suffix = _loan_suffix(customer_info.get("loan_id"))
    prompt = (
        f"Hello {name}. I am a voice agent calling from a bank. "
        f"Am I speaking with {name} with the loan ID ending in {loan_suffix}?"
    )
    logger.tts.info(f"🔁 Confirmation prompt: {prompt}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt, "en-IN")
    await stream_audio_to_websocket(websocket, audio_bytes)


async def play_connecting_prompt(websocket) -> None:
    prompt = "Wait a second, I will connect you to our agent."
    logger.tts.info(f"🔁 Connecting prompt: {prompt}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt, "en-IN")
    await stream_audio_to_websocket(websocket, audio_bytes)


async def play_sorry_prompt(websocket) -> None:
    prompt = "Sorry for the mistake. Thank you."
    logger.tts.info(f"🔁 Sorry prompt: {prompt}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt, "en-IN")
    await stream_audio_to_websocket(websocket, audio_bytes)


async def play_repeat_prompt(websocket, customer_info: Dict[str, Any]) -> None:
    name = customer_info.get("name") or "there"
    loan_suffix = _loan_suffix(customer_info.get("loan_id"))
    prompt = (
        f"I am sorry, I did not catch that. Am I speaking with {name} with the loan ID ending in {loan_suffix}?"
    )
    logger.tts.info(f"🔁 Repeat prompt: {prompt}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt, "en-IN")
    await stream_audio_to_websocket(websocket, audio_bytes)

# --- Language and Intent Detection ---
def _is_devanagari(text): return any('\u0900' <= ch <= '\u097F' for ch in text)
def _is_tamil(text): return any('\u0B80' <= ch <= '\u0BFF' for ch in text)
def _is_telugu(text): return any('\u0C00' <= ch <= '\u0C7F' for ch in text)
def _is_kannada(text): return any('\u0C80' <= ch <= '\u0CFF' for ch in text)
def _is_malayalam(text): return any('\u0D00' <= ch <= '\u0D7F' for ch in text)
def _is_gujarati(text): return any('\u0A80' <= ch <= '\u0AFF' for ch in text)
def _is_marathi(text): return any('\u0900' <= ch <= '\u097F' for ch in text)
def _is_bengali(text): return any('\u0980' <= ch <= '\u09FF' for ch in text)
def _is_punjabi(text): return any('\u0A00' <= ch <= '\u0A7F' for ch in text)
def _is_oriya(text): return any('\u0B00' <= ch <= '\u0B7F' for ch in text)

def _is_gurmukhi(text):
    """Checks if the text contains any Gurmukhi characters (for Punjabi)."""
    return any('\u0A00' <= char <= '\u0A7F' for char in text)

def detect_language(text):
    text = text.strip().lower()
    
    # Enhanced English detection - check for common English words first
    english_words = [
        "yes", "yeah", "yep", "sure", "okay", "ok", "alright", "right", 
        "no", "nah", "nope", "not", "never",
        "hello", "hi", "hey", "good", "morning", "afternoon", "evening",
        "please", "thank", "thanks", "welcome", "sorry", "excuse",
        "what", "where", "when", "why", "how", "who", "which",
        "can", "could", "would", "should", "will", "shall", "may", "might",
        "i", "me", "my", "you", "your", "we", "our", "they", "their",
        "speak", "talk", "call", "phone", "agent", "person", "someone",
        "help", "support", "assistance", "service", "transfer", "connect"
    ]
    
    # Check if text contains primarily English words
    words = text.split()
    english_word_count = sum(1 for word in words if word in english_words)
    
    # If majority of words are English, return English
    if words and english_word_count >= len(words) * 0.5:  # At least 50% English words
        return "en-IN"
    
    # Check for specific language indicators
    if any(word in text for word in ["नमस्ते", "हां", "नहीं", "हाँ", "जी", "अच्छा"]) or _is_devanagari(text): 
        return "hi-IN"
    if any(word in text for word in ["வணக்கம்", "ஆம்", "இல்லை"]) or _is_tamil(text): 
        return "ta-IN"
    if any(word in text for word in ["హాయ్", "అవును", "కాదు"]) or _is_telugu(text): 
        return "te-IN"
    if any(word in text for word in ["ಹೆಲೋ", "ಹೌದು", "ಇಲ್ಲ"]) or _is_kannada(text): 
        return "kn-IN"
    if any(word in text for word in ["നമസ്കാരം", "അതെ", "ഇല്ല"]) or _is_malayalam(text): 
        return "ml-IN"
    if any(word in text for word in ["નમસ્તે", "હા", "ના"]) or _is_gujarati(text): 
        return "gu-IN"
    if any(word in text for word in ["नमस्कार", "होय", "नाही"]) or _is_marathi(text): 
        return "mr-IN"
    if any(word in text for word in ["নমস্কার", "হ্যাঁ", "না"]) or _is_bengali(text): 
        return "bn-IN"
    if any(word in text for word in ["ਸਤ ਸ੍ਰੀ ਅਕਾਲ", "ਹਾਂ", "ਨਹੀਂ"]) or _is_punjabi(text): 
        return "pa-IN"
    if any(word in text for word in ["ନମସ୍କାର", "ହଁ", "ନା"]) or _is_oriya(text): 
        return "or-IN"
    
    # Default to English if no specific language detected
    return "en-IN"

def detect_intent_with_claude(transcript: str, lang: str) -> str:
    """Detect intent for agent handoff using Claude via Bedrock. Returns 'affirmative'|'negative'|'unclear'."""
    logger.websocket.info(f"Getting intent for: '{transcript}'")
    try:
        # Build a precise, deterministic prompt for agent-handoff classification
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are classifying a user's short reply to this question: "
                            "'Would you like me to connect you to one of our agents to assist you better?'\n\n"
                            f"User reply (language={lang}): '{transcript}'\n\n"
                            "Classify strictly into one of: affirmative, negative, unclear.\n"
                            "- affirmative: yes/okay/sure/हाँ/ஆம்/etc (wants connection)\n"
                            "- negative: no/not now/नहीं/இல்லை/etc (does not want)\n"
                            "- unclear: ambiguous filler or unrelated\n\n"
                            "Respond with only one word: affirmative | negative | unclear"
                        ),
                    }
                ],
            }
        ]

        # bedrock_client.invoke_claude_model returns a plain string
        response_text = bedrock_client.invoke_claude_model(messages)
        intent = (response_text or "").strip().lower()

        # Normalize and validate
        if intent in ("affirmative", "negative", "unclear"):
            logger.websocket.info(f"Detected intent: {intent}")
            return intent
        # Try to infer if Claude returned a phrase
        if "affirmative" in intent:
            logger.websocket.info("Detected intent (normalized): affirmative")
            return "affirmative"
        if "negative" in intent:
            logger.websocket.info("Detected intent (normalized): negative")
            return "negative"
        logger.websocket.warning(f"Claude returned unexpected text: {intent}; defaulting to 'unclear'")
        return "unclear"
    except Exception as e:
        logger.websocket.error(f"❌ Error detecting intent with Claude: {e}")
        return "unclear"

def detect_intent_fur(text: str, lang: str) -> str:
    """A fallback intent detection function (a more descriptive name for the original detect_intent)."""
    return detect_intent(text)


def detect_intent(text):
    text = text.lower()
    if any(word in text for word in ["agent", "live agent", "speak to someone", "transfer", "help desk"]): return "agent_transfer"
    if any(word in text for word in ["yes", "yeah", "sure", "okay", "haan", "ஆம்", "அவுனு", "हॉं", "ಹೌದು", "please"]): return "affirmative"
    if any(word in text for word in ["no", "not now", "later", "nah", "nahi", "இல்லை", "காது", "ನಹಿ"]): return "negative"
    if any(word in text for word in ["what", "who", "why", "repeat", "pardon"]): return "confused"
    return "unknown"

# --- State to Language Mapping ---
STATE_TO_LANGUAGE = {
    'andhra pradesh': 'te-IN',
    'arunachal pradesh': 'hi-IN',
    'assam': 'hi-IN',
    'bihar': 'hi-IN',
    'chhattisgarh': 'hi-IN',
    'goa': 'hi-IN',
    'gujarat': 'gu-IN',
    'haryana': 'hi-IN',
    'himachal pradesh': 'hi-IN',
    'jharkhand': 'hi-IN',
    'karnataka': 'kn-IN',
    'kerala': 'ml-IN',
    'madhya pradesh': 'hi-IN',
    'maharashtra': 'mr-IN',
    'manipur': 'hi-IN',
    'meghalaya': 'hi-IN',
    'mizoram': 'hi-IN',
    'nagaland': 'hi-IN',
    'odisha': 'or-IN',
    'punjab': 'pa-IN',
    'rajasthan': 'hi-IN',
    'sikkim': 'hi-IN',
    'tamil nadu': 'ta-IN',
    'telangana': 'te-IN',
    'tripura': 'hi-IN',
    'uttar pradesh': 'hi-IN',
    'uttarakhand': 'hi-IN',
    'west bengal': 'bn-IN',
    'delhi': 'hi-IN',
    'puducherry': 'ta-IN',
    'chandigarh': 'hi-IN',
    'andaman and nicobar islands': 'hi-IN',
    'dadra and nagar haveli and daman and diu': 'hi-IN',
    'jammu and kashmir': 'hi-IN',
    'ladakh': 'hi-IN',
    'lakshadweep': 'ml-IN',
}

def get_initial_language_from_state(state: str) -> str:
    """Get the initial language based on customer's state."""
    if not state:
        return 'en-IN'
    return STATE_TO_LANGUAGE.get(state.strip().lower(), 'en-IN')


# --- Static Files and Templates ---
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="static")

# --- HTML Endpoints ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """
    Serves the improved dashboard HTML file at the root URL.
    """
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/original", response_class=HTMLResponse)
async def get_original_dashboard(request: Request):
    """
    Serves the original dashboard HTML file for backward compatibility.
    """
    return templates.TemplateResponse("index.html", {"request": request})

# --- WebSocket URL Generator for Exotel Flow ---
@app.get("/ws-url", response_class=PlainTextResponse)
async def generate_websocket_url(request: Request):
    """
    Generates the correct WebSocket URL for Exotel flow to connect to.
    This endpoint is called by Exotel flow to get the WebSocket URL dynamically.
    """
    logger.websocket.info("🔗 /ws-url endpoint hit")
    
    params = request.query_params
    call_sid = params.get("CallSid")
    custom_field = params.get("CustomField")
    from_number = params.get("From")
    
    logger.websocket.info(f"🔗 WebSocket URL request - CallSid: {call_sid}")
    logger.websocket.info(f"🔗 WebSocket URL request - CustomField: {custom_field}")
    logger.websocket.info(f"🔗 WebSocket URL request - From: {from_number}")
    
    # Parse temp_call_id from CustomField
    temp_call_id = None
    if custom_field:
        try:
            pairs = custom_field.split('|')
            for pair in pairs:
                if '=' in pair and pair.startswith('temp_call_id='):
                    temp_call_id = pair.split('=', 1)[1]
                    break
        except Exception as e:
            logger.error.error(f"🔗 Failed to parse temp_call_id from CustomField: {e}")
    
    # Use CallSid as session_id if available, otherwise use temp_call_id
    session_id = call_sid or temp_call_id or generate_websocket_session_id()
    
    # Get the base URL (ngrok URL)
    base_url = os.getenv('BASE_URL', 'http://localhost:8000')
    # Convert http to ws
    ws_base_url = base_url.replace('http://', 'ws://').replace('https://', 'wss://')
    
    # Generate the WebSocket URL with query parameters
    websocket_url = f"{ws_base_url}/ws/voicebot/{session_id}"
    
    # Add query parameters
    query_params = []
    if temp_call_id:
        query_params.append(f"temp_call_id={temp_call_id}")
    if call_sid:
        query_params.append(f"call_sid={call_sid}")
    if from_number:
        query_params.append(f"phone={from_number}")
    
    if query_params:
        websocket_url += "?" + "&".join(query_params)
    
    logger.websocket.info(f"🔗 Generated WebSocket URL: {websocket_url}")
    
    # Return the WebSocket URL as plain text for Exotel to use
    return websocket_url

# --- Exotel Passthru Handler ---
@app.get("/passthru-handler", response_class=PlainTextResponse)
async def handle_passthru(request: Request):
    """
    Handles Exotel's Passthru applet request.
    When Exotel notifies us that a call has started, we:
      1. Cache call session in Redis
      2. Update DB
      3. Immediately trigger agent transfer (customer → agent)
      4. Notify frontend
    """
    logger.websocket.info("✅ /passthru-handler hit")

    params = request.query_params
    call_sid = params.get("CallSid")
    custom_field = params.get("CustomField")
    from_number = params.get("From")   # Customer number

    if not call_sid:
        logger.error.error("❌ Passthru handler called without a CallSid.")
        return "OK"  # Always return OK so Exotel flow isn’t broken

    logger.websocket.info(f"📞 Passthru: CallSid received: {call_sid}")
    logger.websocket.info(f"📦 Passthru: CustomField received: {custom_field}")

    # --- Parse custom fields ---
    customer_data = {}
    if custom_field:
        try:
            pairs = custom_field.split('|')
            for pair in pairs:
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    customer_data[key.strip()] = value.strip()
            logger.websocket.info(f"📊 Passthru: Parsed Custom Fields: {customer_data}")
        except Exception as e:
            logger.error.error(f"❌ Passthru: Failed to parse CustomField: {e}")

    # temp_call_id linking
    temp_call_id = customer_data.get("temp_call_id")
    if temp_call_id:
        redis_manager.link_session_to_sid(temp_call_id, call_sid)
    else:
        redis_manager.create_call_session(call_sid, customer_data)

    # --- Database: mark call as IN_PROGRESS ---
    try:
        session = db_manager.get_session()
        try:
            update_call_status(
                session=session,
                call_sid=call_sid,
                status=CallStatus.IN_PROGRESS,
                message=f"Call flow started - temp_call_id: {temp_call_id}"
            )
            session.commit()
            logger.database.info(f"✅ Passthru: DB updated to IN_PROGRESS for CallSid {call_sid}")
        finally:
            session.close()
    except Exception as e:
        logger.error.error(f"❌ Passthru: Database update failed for CallSid {call_sid}: {e}")

    logger.websocket.info("🤝 Agent transfer disabled for this flow; proceeding with bot only")
    logger.websocket.info("✅ Passthru: Responding 'OK' to Exotel.")
    return "OK"


async def play_audio_message(websocket, text: str, language_code: str = "en-IN"):
    """
    Convert text to speech and send it to Exotel passthru stream.
    """
    try:
        logger.websocket.info(f"🗣️ Playing audio message: {text}")

        # Generate speech (replace with your actual TTS call)
        audio_data = await synthesize_speech(text, language_code)

        if not audio_data:
            logger.error.error("❌ TTS synthesis failed, no audio generated")
            return

        # Send audio chunks to Exotel via websocket
        await websocket.send_bytes(audio_data)
        logger.websocket.info("✅ Audio message sent to Exotel stream")

    except Exception as e:
        logger.error.error(f"❌ Failed to play audio message: {e}")



# --- WebSocket Endpoint for Voicebot ---
async def handle_voicebot_websocket(websocket: WebSocket, session_id: str, temp_call_id: str = None, call_sid: str = None, phone: str = None):
    await run_voice_session(
        websocket=websocket,
        session_id=session_id,
        temp_call_id=temp_call_id,
        call_sid=call_sid,
        phone=phone,
        compat_mode=False,
    )

async def run_voice_session(
    websocket: WebSocket,
    session_id: str,
    temp_call_id: Optional[str],
    call_sid: Optional[str],
    phone: Optional[str],
    compat_mode: bool = False,
) -> None:
    logger.websocket.info(f"✅ Connected to Exotel Voicebot for session: {session_id}")
    if not call_sid:
        call_sid = session_id

    transcript_logger = TranscriptLogger(TRANSCRIPTS_FILE_PATH, call_sid)

    conversation_stage = "AWAIT_START"  # AWAIT_START → WAITING_CONFIRMATION → CLAUDE_CHAT/GOODBYE_SENT/WAITING_DISCONNECT
    audio_buffer = bytearray()
    last_transcription_time = time.time()
    customer_info: Optional[Dict[str, Any]] = None
    confirmation_attempts = 0
    claude_chat = None
    claude_turns = 0
    refusal_count = 0
    interaction_complete = False

    async def speak_text(text: str) -> None:
        if not text:
            return
        audio_bytes = await sarvam_handler.synthesize_tts(text, "en-IN")
        if audio_bytes:
            await stream_audio_to_websocket(websocket, audio_bytes)

    def sanitize_phone(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        return ''.join(ch for ch in raw if ch.isdigit())

    def parse_custom_field(value: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for part in value.split('|'):
            if '=' in part:
                key, val = part.split('=', 1)
                result[key.strip()] = val.strip()
        return result

    def ensure_customer_info(info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not info:
            return None
        if not info.get('name'):
            return None
        if not info.get('loan_id'):
            info['loan_id'] = 'unknown'
        if not info.get('amount'):
            info['amount'] = 'the outstanding amount'
        if not info.get('due_date'):
            info['due_date'] = 'the due date'
        return info

    def format_amount(value: Optional[str]) -> str:
        if not value:
            return "the outstanding amount"
        cleaned = ''.join(ch for ch in str(value) if ch.isdigit())
        if not cleaned:
            return str(value)
        try:
            num = int(cleaned)
            return f"₹{num:,}"
        except ValueError:
            return str(value)

    strong_refusal_phrases = [
        "can't pay", "cannot pay", "won't pay", "will not pay", "not able to pay",
        "unable to pay", "not going to pay", "no money to pay", "zero balance to pay",
        "can't make the payment", "cannot make the payment", "don't have money", "don't have the money",
        "can't settle now", "cannot settle now", "can't right now", "cannot right now",
        "pay later", "make the payment later", "next month", "two months", "after two months",
        "mudiyaathu", "mudiyaadhu", "mudiyathu", " முடியாது", "illai", "illa", "வேண்டாம்", "vendam",
        "nahi kar paunga", "nahi kar sakta", "nahin kar paunga", "nahin kar sakta", "paisa nahi", "paise nahi",
        "nahi dunga", "nahin dunga", "nahi doonga", "nahin doonga",
        "cheyalenu", "చేయలేను", "కాదు", "నాకు డబ్బు లేదు",
        "maadu aagala", "ಮಾಡಲಾಗುವುದಿಲ್ಲ", "ಬೇಡ"
    ]
    basic_negatives = [
        "can't", "cannot", "won't", "will not", "not able", "unable", "no", "nah",
        "later", "delay", "postpone", "maybe later", "not now", "another time",
        "nahi", "nahin", "mat", "illai", "vendam", "mudiya", "cheyanu", "ledu", "illa"
    ]
    payment_terms = [
        "pay", "payment", "amount", "money", "emi", "due", "settle", "installment", "loan", "balance",
        "paisa", "paise", "panam", "selavu", "kattan", "rakam", "dabbu"
    ]

    def is_refusal_statement(text: str) -> bool:
        if not text:
            return False
        normalized = text.lower()
        if any(phrase in normalized for phrase in strong_refusal_phrases):
            return True
        if any(term in normalized for term in payment_terms) and any(neg in normalized for neg in basic_negatives):
            return True
        return False

    async def resolve_customer_from_db(raw_phone: Optional[str]) -> Optional[Dict[str, Any]]:
        if not raw_phone:
            return None
        try:
            from database.schemas import get_customer_by_phone
            session = db_manager.get_session()
            try:
                candidates = set()
                digits = sanitize_phone(raw_phone)
                if digits:
                    candidates.update({digits, digits[-10:]})
                    candidates.add(f"91{digits[-10:]}")
                    candidates.add(f"+91{digits[-10:]}")
                candidates.add(raw_phone)
                for candidate in candidates:
                    customer = get_customer_by_phone(session, candidate)
                    if customer:
                        return {
                            'name': customer.name,
                            'loan_id': customer.loan_id,
                            'amount': customer.amount,
                            'due_date': customer.due_date,
                            'lang': customer.language_code or 'en-IN',
                            'phone': customer.phone_number,
                            'state': customer.state or '',
                        }
            finally:
                session.close()
        except Exception as err:
            logger.database.error(f"❌ Error resolving customer by phone: {err}")
        return None

    async def handle_start_event(msg: Dict[str, Any]) -> bool:
        nonlocal call_sid, customer_info, conversation_stage, last_transcription_time, claude_chat

        stream_sid = (
            msg.get("streamSid")
            or (msg.get("start") or {}).get("streamSid")
            or (msg.get("start") or {}).get("stream_sid")
        )
        if stream_sid:
            websocket.stream_sid = stream_sid
            logger.websocket.info(f"🔗 streamSid set to {stream_sid}")
        websocket.stream_track = ((msg.get("start") or {}).get("tracks") or ["outbound"])[0]
        logger.websocket.info(f"🎧 Using track {websocket.stream_track}")

        candidate_sid = (
            (msg.get("start") or {}).get("call_sid")
            or (msg.get("start") or {}).get("callSid")
            or msg.get("callSid")
            or msg.get("CallSid")
            or msg.get("call_sid")
            or call_sid
        )
        if candidate_sid:
            call_sid = candidate_sid
            transcript_logger.call_sid = call_sid
            logger.websocket.info(f"🎯 Resolved CallSid: {call_sid}")

        info: Optional[Dict[str, Any]] = None
        if temp_call_id:
            session_data = redis_manager.get_call_session(temp_call_id)
            if session_data:
                info = session_data.get('customer_data') or session_data
        if not info and call_sid:
            session_data = redis_manager.get_call_session(call_sid)
            if session_data:
                info = session_data.get('customer_data') or session_data

        custom_field = (msg.get('customField')
                        or (msg.get('start') or {}).get('customField')
                        or (msg.get('start') or {}).get('custom_field'))
        if not info and custom_field:
            parsed = parse_custom_field(custom_field)
            if parsed:
                info = {
                    'name': parsed.get('name') or parsed.get('customer_name'),
                    'loan_id': parsed.get('loan_id'),
                    'amount': parsed.get('amount'),
                    'due_date': parsed.get('due_date'),
                    'lang': parsed.get('language_code', 'en-IN'),
                    'phone': parsed.get('phone_number') or parsed.get('phone'),
                    'state': parsed.get('state', ''),
                }

        if not info and phone:
            info = await resolve_customer_from_db(phone)

        info = ensure_customer_info(info)
        if not info:
            logger.websocket.error("❌ Customer data missing; cannot continue")
            await websocket.send_text(json.dumps({
                "event": "error",
                "message": "Customer data not found. Please ensure call is triggered properly."
            }))
            return False

        customer_info = info
        transcript_logger.update_customer(
            customer_info.get('name'),
            customer_info.get('phone') or customer_info.get('phone_number')
        )

        logger.websocket.info(
            f"📋 Customer: {customer_info['name']} | Loan: {customer_info.get('loan_id')}"
        )

        await play_confirmation_prompt(websocket, customer_info)
        conversation_stage = "WAITING_CONFIRMATION"
        last_transcription_time = time.time()
        return True

    async def handle_confirmation_response(transcript: str) -> Optional[str]:
        nonlocal conversation_stage, confirmation_attempts, claude_chat

        normalized = transcript.lower()
        affirmative = {"yes", "yeah", "yep", "haan", "ha", "correct", "sure", "yup"}
        negative = {"no", "nah", "nope", "nahi", "na"}

        is_affirmative = any(word in normalized for word in affirmative)
        is_negative = any(word in normalized for word in negative)

        if is_affirmative:
            logger.websocket.info("✅ Customer confirmed identity")
            await play_connecting_prompt(websocket)
            conversation_stage = "CLAUDE_CHAT"
            confirmation_attempts = 0
            claude_chat = claude_chat_manager.start_session(call_sid, customer_info)
            if claude_chat:
                intro_prompt = (
                    "The caller is now on the line. Introduce yourself as Priya from Intalks NGN Bank, "
                    "briefly remind them about the overdue EMI amount of {amount}, and immediately ask "
                    "for a concrete repayment date. Keep it under two short sentences and append a "
                    "status tag [continue] at the end."
                ).format(amount=format_amount(customer_info.get('amount')))
                intro = await claude_reply(claude_chat, intro_prompt)
                if intro:
                    intro_text, _ = parse_claude_response(intro)
                    if transcript_logger and intro_text:
                        transcript_logger.add_transcript(f"[Claude] {intro_text}", time.time())
                    await speak_text(intro_text)
                logger.websocket.info("🤖 Claude session established")
            else:
                await speak_text("Our specialist is here. How can I assist you today?")
                logger.websocket.warning("⚠️ Claude unavailable; using fallback persona")
            return "affirmative"
        if is_negative:
            logger.websocket.info("ℹ️ Customer declined identity")
            await play_sorry_prompt(websocket)
            conversation_stage = "GOODBYE_SENT"
            return "negative"

        confirmation_attempts += 1
        if confirmation_attempts >= 3:
            await play_sorry_prompt(websocket)
            conversation_stage = "GOODBYE_SENT"
            return "negative"
        await play_repeat_prompt(websocket, customer_info)
        return None

    async def handle_claude_exchange(transcript: str) -> str:
        nonlocal claude_turns, conversation_stage, interaction_complete, refusal_count
        if not transcript:
            return "continue"
        if not claude_chat:
            await speak_text("Thank you for explaining. I'll connect you to our agent now.")
            conversation_stage = "WAITING_DISCONNECT"
            interaction_complete = True
            return "end"

        if is_refusal_statement(transcript):
            refusal_count += 1
            logger.websocket.info(f"🚫 Customer refusal detected (count={refusal_count})")

        claude_turns += 1
        raw_reply = await claude_reply(claude_chat, transcript)
        if not raw_reply:
            await speak_text("I didn't catch that. Could you please repeat?")
            return "continue"

        agent_text, status = parse_claude_response(raw_reply)
        cleaned_agent_text = (agent_text or "").strip()
        if status == "promise" and cleaned_agent_text.endswith("?"):
            logger.websocket.info("ℹ️ Ignoring [promise] tag because assistant response is a question")
            status = "continue"

        allowed_to_escalate = refusal_count >= CLAUDE_REFUSAL_THRESHOLD
        if allowed_to_escalate and status == "continue":
            logger.websocket.info(
                f"ℹ️ Auto-escalating after repeated refusals (count={refusal_count})"
            )
            status = "escalate"
        elif status == "escalate" and not allowed_to_escalate:
            logger.websocket.info(
                f"ℹ️ Escalation deferred (refusal_count={refusal_count} < {CLAUDE_REFUSAL_THRESHOLD}); continuing conversation"
            )
            status = "continue"

        if transcript_logger:
            transcript_logger.add_transcript(f"[Claude_raw] {raw_reply}", time.time())

        final_agent_text = cleaned_agent_text or agent_text or ""
        if status == "escalate":
            final_agent_text = ESCALATION_CLOSING_MESSAGE

        if transcript_logger and final_agent_text:
            transcript_logger.add_transcript(f"[Claude] {final_agent_text}", time.time())
        if final_agent_text:
            await speak_text(final_agent_text)

        if status == "promise":
            conversation_stage = "WAITING_DISCONNECT"
            interaction_complete = True
            return "end"

        if status == "escalate":
            conversation_stage = "WAITING_DISCONNECT"
            interaction_complete = True
            return "end"

        if claude_turns >= MAX_CLAUDE_TURNS:
            if allowed_to_escalate:
                await speak_text("I understand. I'll transfer you to our agent for further assistance.")
                conversation_stage = "WAITING_DISCONNECT"
                interaction_complete = True
                return "end"
            logger.websocket.info(
                f"ℹ️ Max Claude turns reached but refusal threshold not met (count={refusal_count}); continuing"
            )
            claude_turns = MAX_CLAUDE_TURNS - 1
            return "continue"

        return "continue"

    try:
        while True:
            try:
                message_text = await websocket.receive_text()
            except WebSocketDisconnect:
                logger.websocket.warning("⚠️ WebSocket disconnected")
                break

            msg = json.loads(message_text)
            event = msg.get("event")
            logger.websocket.info(f"📨 Event received: {event}")
            logger.log_websocket_message(event or "unknown", msg)
            if event == "start":
                if not await handle_start_event(msg):
                    interaction_complete = True
                    break
                continue

            if event == "stop":
                logger.websocket.info("🛑 Received stop event from Exotel")
                interaction_complete = True
                break

            if event != "media":
                continue

            payload_b64 = msg["media"].get("payload")
            raw_audio = base64.b64decode(payload_b64)

            if interaction_complete:
                continue
            if raw_audio and any(b != 0 for b in raw_audio):
                audio_buffer.extend(raw_audio)

            now = time.time()
            if transcript_logger:
                transcript_logger.maybe_flush(now)

            if conversation_stage == "WAITING_CONFIRMATION":
                timeout = CONFIRMATION_SILENCE_SECONDS
            elif conversation_stage == "CLAUDE_CHAT":
                timeout = CLAUDE_SILENCE_SECONDS
            else:
                timeout = BUFFER_DURATION_SECONDS

            if now - last_transcription_time < timeout:
                continue

            if len(audio_buffer) < MIN_AUDIO_BYTES:
                audio_buffer.clear()
                last_transcription_time = now
                continue

            try:
                transcript = await sarvam_handler.transcribe_from_payload(audio_buffer)
                if isinstance(transcript, tuple):
                    transcript = transcript[0]
                elif not isinstance(transcript, str):
                    transcript = ""
            except Exception as err:
                logger.websocket.error(f"❌ Error transcribing audio: {err}")
                audio_buffer.clear()
                last_transcription_time = now
                continue

            audio_buffer.clear()
            last_transcription_time = time.time()

            transcript = (transcript or "").strip()
            if transcript_logger and transcript:
                transcript_logger.add_transcript(transcript, last_transcription_time)

            if not transcript:
                continue

            logger.websocket.info(f"📝 Transcript ({conversation_stage}): {transcript}")

            if conversation_stage == "WAITING_CONFIRMATION":
                result = await handle_confirmation_response(transcript)
                if result == "negative":
                    interaction_complete = True
                    await asyncio.sleep(2)
                    break
            elif conversation_stage == "CLAUDE_CHAT":
                outcome = await handle_claude_exchange(transcript)
                if outcome == "end":
                    await asyncio.sleep(2)
                    break

    except Exception as err:
        logger.error.error(f"WebSocket error: {err}")
        logger.log_call_event("WEBSOCKET_ERROR", call_sid or 'unknown', customer_info['name'] if customer_info else 'Unknown', {"error": str(err)})
    finally:
        claude_chat_manager.end_session(call_sid)
        if transcript_logger:
            transcript_logger.flush(force=True)
        try:
            if not interaction_complete:
                await asyncio.sleep(1)
            if websocket.client_state.name not in ['DISCONNECTED']:
                await websocket.close()
                logger.websocket.info("🔒 WebSocket connection closed gracefully")
        except Exception as close_err:
            logger.error.error(f"Error closing WebSocket: {close_err}")

        logger.log_call_event(
            "WEBSOCKET_CLOSED_GRACEFUL",
            call_sid or 'unknown',
            customer_info['name'] if customer_info else 'Unknown'
        )

        # Update final status
        try:
            session = db_manager.get_session()
            completed_session = update_call_status(
                session=session,
                call_sid=call_sid,
                status=CallStatus.COMPLETED,
                message="Conversation ended"
            )
            session.commit()
            customer_id_event = (
                str(completed_session.customer_id)
                if completed_session and completed_session.customer_id
                else None
            )
            await push_status_update(
                call_sid,
                CallStatus.COMPLETED,
                "Conversation ended",
                customer_id=customer_id_event,
            )
        except Exception as db_error:
            logger.database.error(f"❌ Error updating final call status for CallSid={call_sid}: {db_error}")
        finally:
            session.close()

# --- WebSocket Endpoint for Voicebot ---
@app.websocket("/ws/voicebot/{session_id}")
async def websocket_voicebot_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    # Initialize variables from query parameters
    query_params = dict(websocket.query_params)
    temp_call_id = query_params.get('temp_call_id')
    call_sid = query_params.get('call_sid', session_id) # Use session_id as a fallback for call_sid
    phone = query_params.get('phone')

    # Use the shared handler
    await handle_voicebot_websocket(websocket, session_id, temp_call_id, call_sid, phone)

# --- WebSocket Endpoint for Dashboard ---
@app.websocket("/ws/dashboard/{session_id}")
async def websocket_dashboard_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    print(f"Dashboard connected: {session_id}")

    event_queue = await register_dashboard_client(session_id, websocket)

    async def sender():
        while True:
            event = await event_queue.get()
            try:
                await websocket.send_text(json.dumps(event))
            except WebSocketDisconnect:
                break

    async def receiver():
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break

    send_task = asyncio.create_task(sender())
    receive_task = asyncio.create_task(receiver())

    try:
        done, pending = await asyncio.wait(
            {send_task, receive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            with suppress(asyncio.CancelledError):
                await task
    finally:
        await unregister_dashboard_client(session_id)
        print(f"Dashboard disconnected: {session_id}")

# --- API Endpoints for Dashboard ---

class CustomerData(BaseModel):
    name: str
    phone: str
    loan_id: str
    amount: str
    due_date: str
    state: str
    language_code: str

@app.post("/api/upload-customers")
async def upload_customers(file: UploadFile = File(...)):
    """
    Accepts a CSV or Excel file, processes it, and stores customer data in the database.
    """
    print(f"📁 [CHECKPOINT] /api/upload-customers endpoint hit")
    print(f"📁 [CHECKPOINT] File name: {file.filename}")
    print(f"📁 [CHECKPOINT] File content type: {file.content_type}")
    
    try:
        file_data = await file.read()
        print(f"📁 [CHECKPOINT] File size: {len(file_data)} bytes")
        
        result = await call_service.upload_and_process_customers(file_data, file.filename)
        print(f"📁 [CHECKPOINT] File processing result: {result}")
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in upload_customers endpoint: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/trigger-single-call")
async def trigger_single_call(customer_id: str = Body(..., embed=True)):
    """
    Triggers a single call to a customer by their ID.
    """
    print(f"🚀 [CHECKPOINT] /api/trigger-single-call endpoint hit")
    print(f"🚀 [CHECKPOINT] Customer ID: {customer_id}")
    
    try:
        result = await call_service.trigger_single_call(customer_id)
        print(f"🚀 [CHECKPOINT] Call service result: {result}")

        if result.get("success") and result.get("call_sid"):
            status_value = result.get("status") or CallStatus.RINGING
            customer_id = result.get("customer", {}).get("id")
            await push_status_update(
                result["call_sid"],
                status_value,
                "Call initiated successfully",
                customer_id=customer_id,
            )
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in trigger_single_call endpoint: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/trigger-bulk-calls")
async def trigger_bulk_calls(customer_ids: list[str] = Body(..., embed=True)):
    """
    Triggers calls to a list of customers by their IDs.
    """
    print(f"🚀 [CHECKPOINT] /api/trigger-bulk-calls endpoint hit")
    print(f"🚀 [CHECKPOINT] Customer IDs: {customer_ids}")
    print(f"🚀 [CHECKPOINT] Number of customers: {len(customer_ids)}")
    
    try:
        result = await call_service.trigger_bulk_calls(customer_ids)
        print(f"🚀 [CHECKPOINT] Bulk call service result: {result}")

        for call_result in result:
            call_sid = call_result.get("call_sid")
            if call_result.get("success") and call_sid:
                status_value = call_result.get("status") or CallStatus.RINGING
                customer_id = call_result.get("customer", {}).get("id")
                await push_status_update(
                    call_sid,
                    status_value,
                    "Bulk call initiated",
                    customer_id=customer_id,
                )
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in trigger_bulk_calls endpoint: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/customers")
async def get_all_customers():
    """
    Retrieves all customers from the database.
    """
    print(f"👥 [CHECKPOINT] /api/customers endpoint hit")
    
    session = db_manager.get_session()
    try:
        customers = session.query(Customer).all()
        print(f"👥 [CHECKPOINT] Found {len(customers)} customers in database")
        
        result = [
            {
                "id": str(c.id),
                "name": c.name,
                "phone_number": c.phone_number,
                "language_code": c.language_code,
                "loan_id": c.loan_id,
                "amount": c.amount,
                "due_date": c.due_date,
                "state": c.state,
                "call_status": c.call_status or "not_initiated",
                "call_attempts": c.call_attempts or 0,
                "last_call_attempt": c.last_call_attempt.isoformat() if c.last_call_attempt else None,
                "created_at": c.created_at.isoformat()
            } for c in customers
        ]
        
        print(f"👥 [CHECKPOINT] Returning customer list successfully")
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in get_all_customers endpoint: {e}")
        return []
    finally:
        session.close()

@app.post("/exotel-webhook")
async def exotel_webhook(request: Request):
    """
    Enhanced webhook handler with proper agent_transfer → completed transition
    """
    try:
        form_data = await request.form()

        # Debug logs
        print(f"\n{'='*60}")
        print(f"📞 [WEBHOOK DEBUG] Timestamp: {datetime.now()}")
        print(f"📞 [WEBHOOK DEBUG] Raw form data: {dict(form_data)}")
        print(f"{'='*60}\n")

        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus") or form_data.get("Status")
        call_duration = form_data.get("CallDuration")

        if not call_sid or not call_status:
            print(f"❌ [WEBHOOK] Missing CallSid or CallStatus")
            return {"status": "error", "message": "Missing CallSid or CallStatus"}

        session = db_manager.get_session()
        try:
            call_session = get_call_session_by_sid(session, call_sid)

            if not call_session:
                print(f"❌ [WEBHOOK] Call session NOT FOUND for SID: {call_sid}")
                return {"status": "error", "message": "Call session not found"}

            print(f"📞 [WEBHOOK] Found call session with current status: {call_session.status}")

            # Status mappings
            call_status_mapping = {
                'ringing': 'ringing',
                'in-progress': 'in_progress',
                'answered': 'in_progress',
                'completed': 'completed',
                'hangup': 'completed',
                'busy': 'busy',
                'no-answer': 'no_answer',
                'failed': 'failed',
                'canceled': 'failed',
                'cancelled': 'failed',
                'terminal': 'completed',
                'end': 'completed',
                'finished': 'completed',
                'agent_transfer': 'agent_transfer'
            }

            customer_status_mapping = {
                'ringing': 'ringing',
                'in_progress': 'call_in_progress',
                'completed': 'call_completed',
                'busy': 'call_failed',
                'no_answer': 'disconnected',
                'failed': 'call_failed',
                'agent_transfer': 'agent_transfer'
            }

            status_key = call_status.lower().strip()
            normalized_status = call_status_mapping.get(status_key, status_key)
            customer_status = customer_status_mapping.get(normalized_status, 'call_in_progress')

            print(f"📞 [WEBHOOK] Normalized={normalized_status}, Customer={customer_status}")

            # ✅ Allow transition from agent_transfer → completed
            final_status = normalized_status

            # 1. Update call_sessions
            update_call_status(
                session,
                call_sid,
                final_status,
                f"Exotel webhook: {call_status} (Duration: {call_duration}s)",
                {'webhook_data': dict(form_data), 'call_duration': call_duration}
            )
            session.commit()
            print(f"✅ [WEBHOOK] Call session updated to: {final_status}")

            # 2. Update customer
            if call_session.customer_id:
                update_customer_call_status(
                    session,
                    str(call_session.customer_id),
                    customer_status,
                    call_attempt=True
                )
                session.commit()
                print(f"✅ [WEBHOOK] Customer updated to: {customer_status}")

            await push_status_update(
                call_sid,
                customer_status,
                f"Webhook status: {call_status}",
                customer_id=str(call_session.customer_id) if call_session and call_session.customer_id else None,
            )

            return {"status": "success", "message": f"Webhook processed with {final_status}"}

        except Exception as db_error:
            session.rollback()
            print(f"❌ [WEBHOOK] Database error: {db_error}")
            import traceback; traceback.print_exc()
            return {"status": "error", "message": str(db_error)}
        finally:
            session.close()

    except Exception as e:
        print(f"❌ [WEBHOOK] Critical error: {e}")
        import traceback; traceback.print_exc()
        return {"status": "error", "message": str(e)}



    
@app.get("/api/debug-tables/{customer_id}")
async def debug_all_tables(customer_id: str):
    """Debug all tables for a specific customer"""
    session = db_manager.get_session()
    try:
        # Get customer data
        customer = session.query(Customer).filter(Customer.id == customer_id).first()
        
        # Get call sessions for this customer
        call_sessions = session.query(CallSession).filter(CallSession.customer_id == customer_id).order_by(CallSession.created_at.desc()).limit(5).all()
        
        # Get call status updates
        call_status_updates = []
        for call_session in call_sessions:
            updates = session.execute(
                text("SELECT * FROM call_status_updates WHERE call_session_id = :session_id ORDER BY timestamp DESC"),
                {"session_id": call_session.id}
            ).fetchall()
            call_status_updates.extend([dict(row._mapping) for row in updates])
        
        return {
            "customer": {
                "id": customer.id if customer else None,
                "name": customer.name if customer else None,
                "phone": customer.phone_number if customer else None,
                "call_status": customer.call_status if customer else None,
                "call_attempts": customer.call_attempts if customer else None,
                "last_call_attempt": customer.last_call_attempt.isoformat() if customer and customer.last_call_attempt else None
            } if customer else None,
            "call_sessions": [
                {
                    "id": cs.id,
                    "call_sid": cs.call_sid,
                    "status": cs.status,
                    "start_time": cs.start_time.isoformat() if cs.start_time else None,
                    "end_time": cs.end_time.isoformat() if cs.end_time else None,
                    "created_at": cs.created_at.isoformat() if cs.created_at else None,
                    "updated_at": cs.updated_at.isoformat() if cs.updated_at else None
                } for cs in call_sessions
            ],
            "call_status_updates": call_status_updates
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        session.close()
    
@app.get("/api/recent-calls")
async def get_recent_calls():
    """Get recent call sessions for monitoring"""
    session = db_manager.get_session()
    try:
        from database.schemas import CallSession  # Make sure this import exists
        recent_calls = session.query(CallSession)\
            .order_by(CallSession.created_at.desc())\
            .limit(10)\
            .all()
        
        response = []
        for call in recent_calls:
            latest_status = None
            latest_message = None
            latest_timestamp = None

            if call.status_updates:
                latest_update = max(
                    call.status_updates,
                    key=lambda update: update.timestamp or datetime.min
                )
                latest_status = latest_update.status
                latest_message = latest_update.message
                latest_timestamp = latest_update.timestamp.isoformat() if latest_update.timestamp else None

            response.append({
                "call_sid": call.call_sid,
                "status": latest_status or call.status,
                "customer_name": call.customer.name if call.customer else "Unknown",
                "created_at": call.created_at.isoformat() if call.created_at else None,
                "updated_at": call.updated_at.isoformat() if call.updated_at else None,
                "last_update": latest_timestamp,
                "message": latest_message,
            })

        return response
    except Exception as e:
        print(f"❌ Error getting recent calls: {e}")
        return []
    finally:
        session.close()

@app.post("/api/force-update-status")
async def force_update_status(request: Request):
    """Manually update call status for testing"""
    try:
        data = await request.json()
        call_sid = data.get('call_sid')
        new_status = data.get('new_status')
        
        if not call_sid or not new_status:
            return {"success": False, "error": "Missing call_sid or new_status"}
        
        session = db_manager.get_session()
        try:
            print(f"🔧 [FORCE-UPDATE] Updating {call_sid} to {new_status}")
            
            result = update_call_status(
                session,
                call_sid,
                new_status,
                f"Manual update to {new_status}"
            )
            
            if result:
                session.commit()
                print(f"✅ [FORCE-UPDATE] Successfully updated {call_sid}")
                await push_status_update(
                    call_sid,
                    new_status,
                    "Manual status override",
                    customer_id=str(result.customer_id) if result and result.customer_id else None,
                )
                return {"success": True, "message": f"Updated {call_sid} to {new_status}"}
            else:
                return {"success": False, "message": f"Call {call_sid} not found"}
                
        except Exception as e:
            session.rollback()
            print(f"❌ [FORCE-UPDATE] Error: {e}")
            return {"success": False, "error": str(e)}
        finally:
            session.close()
    except Exception as e:
        return {"success": False, "error": str(e)}

'''
def print_call_status_to_console(call_sid: str, operation: str = "INITIATED"):
    """
    Standalone function to print call status to console without affecting any other functionality
    """
    try:
        session = db_manager.get_session()
        call_session = get_call_session_by_sid(session, call_sid)
        
        if call_session:
            customer_name = call_session.customer.name if call_session.customer else "Unknown"
            customer_id = call_session.customer_id if call_session.customer_id else "Unknown"
            
            print(f"\n{'='*60}")
            print(f"📞 FETCHED STATUS: {operation}")
            print(f"   CallSid: {call_sid}")
            print(f"   Status: {call_session.status}")
            print(f"   Customer: {customer_name}")
            print(f"   Customer ID: {customer_id}")
            print(f"   Created: {call_session.created_at}")
            print(f"   Updated: {call_session.updated_at}")
            print(f"   Message: {call_session.message}")
            if call_session.customer:
                print(f"   Customer Status: {call_session.customer.call_status}")
                print(f"   Call Attempts: {call_session.customer.call_attempts}")
            print(f"{'='*60}\n")
        else:
            print(f"\n📞 FETCHED STATUS: {operation}")
            print(f"   CallSid: {call_sid} - NOT FOUND IN DATABASE")
            print(f"{'='*60}\n")
            
    except Exception as e:
        print(f"\n❌ FETCHED STATUS ERROR: {operation}")
        print(f"   CallSid: {call_sid}")
        print(f"   Error: {str(e)}")
        print(f"{'='*60}\n")
    finally:
        if 'session' in locals():
            session.close()
'''
@app.get("/api/debug-customer-detailed/{customer_id}")
async def debug_customer_detailed(customer_id: str):
    """Debug a specific customer with all related data"""
    session = db_manager.get_session()
    try:
        customer = session.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return {"error": "Customer not found"}
        
        # Get call sessions for this customer
        call_sessions = session.query(CallSession).filter(CallSession.customer_id == customer_id).order_by(CallSession.created_at.desc()).all()
        
        # Get call status updates for each session
        all_status_updates = []
        for cs in call_sessions:
            status_updates = session.query(CallStatusUpdate).filter(CallStatusUpdate.call_session_id == cs.id).order_by(CallStatusUpdate.timestamp.desc()).all()
            for su in status_updates:
                all_status_updates.append({
                    "id": str(su.id),
                    "call_session_id": str(su.call_session_id),
                    "call_sid": cs.call_sid,
                    "status": su.status,
                    "message": su.message,
                    "timestamp": su.timestamp.isoformat(),
                    "extra_data": su.extra_data
                })
        
        return {
            "customer": {
                "id": str(customer.id),
                "name": customer.name,
                "phone": customer.phone_number,
                "call_status": customer.call_status,
                "call_attempts": customer.call_attempts,
                "last_call_attempt": customer.last_call_attempt.isoformat() if customer.last_call_attempt else None,
                "created_at": customer.created_at.isoformat(),
                "updated_at": customer.updated_at.isoformat() if customer.updated_at else None
            },
            "call_sessions": [
                {
                    "id": str(cs.id),
                    "call_sid": cs.call_sid,
                    "status": cs.status,
                    "start_time": cs.start_time.isoformat() if cs.start_time else None,
                    "end_time": cs.end_time.isoformat() if cs.end_time else None,
                    "duration": cs.duration,
                    "created_at": cs.created_at.isoformat(),
                    "updated_at": cs.updated_at.isoformat() if cs.updated_at else None,
                    "exotel_data": cs.exotel_data
                } for cs in call_sessions
            ],
            "status_updates": all_status_updates
        }
    finally:
        session.close()

@app.post("/api/test-webhook-complete")
async def test_webhook_complete(request: Request):
    """Test webhook with a completed call"""
    try:
        data = await request.json()
        call_sid = data.get('call_sid')
        
        if not call_sid:
            return {"success": False, "error": "call_sid required"}
        
        # Simulate Exotel form data
        from starlette.datastructures import FormData
        mock_form = FormData([
            ('CallSid', call_sid),
            ('CallStatus', 'completed'),
            ('CallDuration', '45')
        ])
        
        # Create mock request
        class MockRequest:
            def __init__(self, form_data):
                self._form_data = form_data
            async def form(self):
                return self._form_data
        
        mock_request = MockRequest(mock_form)
        
        # Call webhook
        result = await exotel_webhook(mock_request)
        
        return {
            "success": True,
            "message": f"Tested webhook completion for {call_sid}",
            "webhook_result": result
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/force-customer-complete/{customer_id}")
async def force_customer_complete(customer_id: str):
    """Force mark a customer as call completed"""
    session = db_manager.get_session()
    try:
        success = update_customer_call_status(
            session, 
            customer_id, 
            'call_completed',
            call_attempt=True
        )
        
        if success:
            return {
                "success": True,
                "message": f"Customer {customer_id} marked as call_completed"
            }
        else:
            return {
                "success": False,
                "error": f"Customer {customer_id} not found"
            }
    finally:
        session.close()
@app.get("/api/call-status/{call_sid}")
async def get_call_status(call_sid: str):
    """Check current call status in database"""
    session = db_manager.get_session()
    try:
        call_session = get_call_session_by_sid(session, call_sid)
        if call_session:
            return {
                "call_sid": call_sid,
                "call_status": call_session.status,
                "customer_id": call_session.customer_id,
                "customer_name": call_session.customer.name if call_session.customer else None,
                "customer_status": call_session.customer.call_status if call_session.customer else None,
                "created_at": call_session.created_at.isoformat(),
                "updated_at": call_session.updated_at.isoformat() if call_session.updated_at else None,
                "message": call_session.message
            }
        else:
            return {"error": "Call session not found", "call_sid": call_sid}
    finally:
        session.close()

@app.get("/api/recent-calls")
async def get_recent_calls():
    """Get recent call sessions for monitoring"""
    session = db_manager.get_session()
    try:
        recent_calls = session.query(CallSession)\
            .order_by(CallSession.created_at.desc())\
            .limit(10)\
            .all()
        
        return [
            {
                "call_sid": call.call_sid,
                "status": call.status,
                "customer_name": call.customer.name if call.customer else "Unknown",
                "created_at": call.created_at.isoformat(),
                "updated_at": call.updated_at.isoformat() if call.updated_at else None
                #"message": call.message 
            }
            for call in recent_calls
        ]
    finally:
        session.close()

@app.post("/api/test-webhook")
async def test_webhook_manually():
    """Test webhook processing manually"""
    from fastapi import Form
    from unittest.mock import Mock
    
    # Create a mock request with test data
    test_form_data = {
        "CallSid": "test_call_123",
        "CallStatus": "completed", 
        "CallDuration": "45"
    }
    
    print(f"🧪 [TEST] Testing webhook with data: {test_form_data}")
    
    # You'll need to replace this with an actual CallSid from your database
    return {"message": "Use this endpoint to test with real CallSid", "test_data": test_form_data}

from fastapi.responses import PlainTextResponse

@app.post("/status-callback", response_class=PlainTextResponse)
async def status_callback(request: Request):
    """
    Exotel call status callback.
    Ensures agent_transfer is not overwritten by completed.
    """
    data = await request.form()
    call_sid = data.get("CallSid")
    call_status = data.get("Status")  # Exotel passes: completed, failed, busy, no-answer, etc.

    logger.websocket.info(f"📡 Exotel /status-callback: CallSid={call_sid}, Status={call_status}")

    if not call_sid:
        logger.error.error("❌ No CallSid in status callback")
        return "OK"

    session = db_manager.get_session()
    try:
        call_session = get_call_session_by_sid(session, call_sid)
        if not call_session:
            logger.error.error(f"❌ Call session not found for CallSid={call_sid}")
            return "OK"

        # Preserve agent_transfer
        if call_session.status == CallStatus.AGENT_TRANSFER:
            logger.database.info(f"ℹ️ CallSid={call_sid} already in AGENT_TRANSFER, preserving status")

            # Log a "completed" event in history but don’t overwrite main status
            status_update = CallStatusUpdate(
                call_session_id=call_session.id,
                status=CallStatus.COMPLETED,
                message="Call ended after agent transfer"
            )
            session.add(status_update)

            if call_session.customer_id:
                update_customer_call_status(
                    session,
                    str(call_session.customer_id),
                    CallStatus.AGENT_TRANSFER
                )
            session.commit()
            await push_status_update(
                call_sid,
                "agent_transfer",
                "Call ended after agent transfer",
                customer_id=str(call_session.customer_id) if call_session.customer_id else None,
            )
        else:
            # Normal status updates
            if call_status == "completed":
                updated_session = update_call_status(session, call_sid, CallStatus.COMPLETED, "Call completed")
                customer_id_event = (
                    str(updated_session.customer_id)
                    if updated_session and updated_session.customer_id
                    else str(call_session.customer_id) if call_session and call_session.customer_id else None
                )
                await push_status_update(
                    call_sid,
                    "completed",
                    "Call completed",
                    customer_id=customer_id_event,
                )
            elif call_status == "failed":
                updated_session = update_call_status(session, call_sid, CallStatus.FAILED, "Call failed")
                customer_id_event = (
                    str(updated_session.customer_id)
                    if updated_session and updated_session.customer_id
                    else str(call_session.customer_id) if call_session and call_session.customer_id else None
                )
                await push_status_update(
                    call_sid,
                    "failed",
                    "Call failed",
                    customer_id=customer_id_event,
                )
            elif call_status == "busy":
                updated_session = update_call_status(session, call_sid, CallStatus.BUSY, "Call busy")
                customer_id_event = (
                    str(updated_session.customer_id)
                    if updated_session and updated_session.customer_id
                    else str(call_session.customer_id) if call_session and call_session.customer_id else None
                )
                await push_status_update(
                    call_sid,
                    "busy",
                    "Call busy",
                    customer_id=customer_id_event,
                )
            elif call_status == "no-answer":
                updated_session = update_call_status(session, call_sid, CallStatus.NO_ANSWER, "Call not answered")
                customer_id_event = (
                    str(updated_session.customer_id)
                    if updated_session and updated_session.customer_id
                    else str(call_session.customer_id) if call_session and call_session.customer_id else None
                )
                await push_status_update(
                    call_sid,
                    "no_answer",
                    "Call not answered",
                    customer_id=customer_id_event,
                )
            elif call_status == "agent_transfer":
                updated_session = update_call_status(session, call_sid, CallStatus.AGENT_TRANSFER, "Agent transferred")
                if updated_session and updated_session.customer_id:
                    update_customer_call_status(
                        session,
                        str(updated_session.customer_id),
                        CallStatus.AGENT_TRANSFER
                    )
                customer_id_event = (
                    str(updated_session.customer_id)
                    if updated_session and updated_session.customer_id
                    else str(call_session.customer_id) if call_session and call_session.customer_id else None
                )
                await push_status_update(
                    call_sid,
                    "agent_transfer",
                    "Agent transferred",
                    customer_id=customer_id_event,
                )
            else:
                logger.websocket.warning(f"⚠️ Unknown status from Exotel: {call_status}")
            session.commit()
    except Exception as e:
        session.rollback()
        logger.error.error(f"❌ Failed to process status callback for CallSid={call_sid}: {e}")
    finally:
        session.close()

    return "OK"



@app.post("/api/update-customer-status")
async def update_customer_status(request: Request):
    """Update customer call status in the database"""
    try:
        data = await request.json()
        customer_id = data.get('customer_id')
        call_status = data.get('call_status')
        
        if not customer_id or not call_status:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Missing customer_id or call_status"}
            )
        
        # FIX: Replace next(get_db()) with db_manager.get_session()
        session = db_manager.get_session()
        try:
            # Update customer call status
            update_customer_call_status(
                session,
                customer_id,
                call_status
            )
            session.commit()  # Add explicit commit
            
            return JSONResponse(
                status_code=200,
                content={"success": True, "message": f"Customer status updated to {call_status}"}
            )
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [API] Error updating customer status: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Internal server error: {str(e)}"}
        )
@app.post("/api/update-bulk-customer-status")
async def update_bulk_customer_status(request: Request):
    """Update multiple customer call statuses in the database"""
    try:
        data = await request.json()
        customer_ids = data.get('customer_ids', [])
        call_status = data.get('call_status')
        
        if not customer_ids or not call_status:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Missing customer_ids or call_status"}
            )
        
        # FIX: Replace next(get_db()) with db_manager.get_session()
        session = db_manager.get_session()
        try:
            updated_count = 0
            for customer_id in customer_ids:
                if update_customer_call_status(session, customer_id, call_status):
                    updated_count += 1
            
            session.commit()  # Add explicit commit
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True, 
                    "message": f"Updated {updated_count}/{len(customer_ids)} customers to {call_status}"
                }
            )
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [API] Error updating bulk customer status: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Internal server error: {str(e)}"}
        )
# This is a catch-all for the old websocket endpoint, redirecting or handling as needed.
@app.websocket("/stream")
async def old_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    query_params = dict(websocket.query_params)
    temp_call_id = query_params.get("temp_call_id")
    call_sid = query_params.get("call_sid")
    phone = query_params.get("phone")
    await run_voice_session(
        websocket=websocket,
        session_id="compat",
        temp_call_id=temp_call_id,
        call_sid=call_sid,
        phone=phone,
        compat_mode=True,
    )


if __name__ == "__main__":
    logger.app.info("Starting server directly from main.py")
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
