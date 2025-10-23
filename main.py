import os
import asyncio
import base64
import csv
import io
import json
import tempfile
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager, suppress
from datetime import datetime, date, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
import requests
import re
import uvicorn
import pytz
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from fastapi import (Body, FastAPI, File, HTTPException, Request, UploadFile,
                     WebSocket)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from requests.auth import HTTPBasicAuth
from starlette.websockets import WebSocketDisconnect
from typing import Any, Dict, Optional, List, Union
from sqlalchemy.orm import joinedload

# Load environment variables at the very beginning
load_dotenv()

IST = pytz.timezone("Asia/Kolkata")


def get_ist_timestamp() -> datetime:
    """Return current timestamp in IST."""
    return datetime.now(IST)


def format_ist_datetime(value: Optional[Union[datetime, date]]) -> Optional[str]:
    """Format datetime/date to ISO string in IST timezone."""
    if value is None:
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())

    if value.tzinfo is None:
        value = pytz.utc.localize(value)

    return value.astimezone(IST).isoformat()


# Import project-specific modules
from database.schemas import (
    CallSession,
    CallStatus,
    CallStatusUpdate,
    Customer,
    FileUpload,
    UploadRow,
    db_manager,
    init_database,
    update_call_status,
    get_call_session_by_sid,
    get_customer_by_phone,
    update_customer_call_status_by_phone,
    update_customer_call_status,
)
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
    normalized_status = (status or "ready").lower()

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
        "event": "call_status_update",
        "call_sid": call_sid,
        "status": normalized_status,
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
        "Respond in 1-2 short sentences and always append a tag in brackets at the end. "
        "Do not output JSON or code blocks; speak naturally as a human agent. "
        "Match the caller's language at all times. If the caller switches languages, instantly switch with them. "
        "Use a casual, modern tone—sound like a friendly contemporary caller, not a formal script. "
        "Avoid archaic or literary vocabulary in any language. "
        "For Tamil, lean on everyday spoken Tamil (உங்களுக்கு → உங்களுக்கு, நான் → நா, etc.) rather than நூல் தமிழ். "
        "For Hindi, use simple spoken Hindi and avoid heavy Sanskrit. "
        "For Telugu, Malayalam, Kannada, Bengali, Marathi, Gujarati, Punjabi, and Odia, prefer the kind of words people use in daily conversations at home or with friends. "
        "Only append [promise] after the customer clearly confirms repayment in a declarative sentence—never add it to your own questions. "
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
CLAUDE_REFUSAL_THRESHOLD = int(os.getenv("CLAUDE_REFUSAL_THRESHOLD", "3"))

# --- Multilingual Prompt Templates with SSML and Pauses ---
GREETING_TEMPLATE = {
    "en-IN": "Hi {name}, Priya here from South India Finvest Bank. Is this you on the line?",
    "hi-IN": "नमस्ते {name} जी, मैं प्रिया बोल रही हूँ, साउथ इंडिया फिनवेस्ट बैंक से. क्या आप अभी बात कर सकते हैं?",
    "ta-IN": "ஹாய் {name} அவர்களே, நான் பிரியா. சவுத் இந்தியா ஃபின்வெஸ்ட் வங்கியிலிருந்து பேசுகிறேன். நீங்கள்தானே பேசுறது?",
    "te-IN": "హాయ్ {name} గారూ, నేను ప్రియా, సౌత్ ఇండియా ఫిన్వెస్ట్ బ్యాంక్ నుంచి మాట్లాడుతున్నాను. మీరు నేనే మాట్లాడ్తున్నారా?",
    "ml-IN": "ഹായ് {name} സാർ, ഞാൻ പ്രിയ, സൗത്ത് ഇന്ത്യ ഫിൻവെസ്റ്റ് ബാങ്കിൽ നിന്ന് സംസാരിക്കുകയാണ്. ഇത് നിങ്ങൾ തന്നെയാണോ?",
    "gu-IN": "હાય {name}જી, હું પ્રિયા, સાઉથ ઇન્ડિયા ફિનવેસ્ટ બેંકમાંથી વાત કરું છું. તમે જ બોલી રહ્યા છો ને?",
    "mr-IN": "हाय {name} जी, मी प्रिया, साउथ इंडिया फिनवेस्ट बँकेतून बोलते आहे. आपणच बोलत आहात ना?",
    "bn-IN": "হাই {name}, আমি প্রিয়া, সাউথ ইন্ডিয়া ফিনভেস্ট ব্যাংক থেকে বলছি। আপনি কি এখন লাইনে আছেন?",
    "kn-IN": "ಹಾಯ್ {name} ಅವ್ರೇ, ನಾನು ಪ್ರಿಯಾ, ಸೌತ್ ಇಂಡಿಯಾ ಫಿನ್‌ವೆಸ್ಟ್ ಬ್ಯಾಂಕ್‌ನಿಂದ ಮಾತಾಡ್ತಾ ಇದ್ದೀನಿ. ನೀವು ಮಾತಾಡ್ತಿದ್ದೀರಾ?",
    "pa-IN": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ {name} ਜੀ, ਮੈਂ ਪ੍ਰਿਆ ਹਾਂ, ਸਾਊਥ ਇੰਡੀਆ ਫਿਨਵੈਸਟ ਬੈਂਕ ਤੋਂ. ਤੁਸੀਂ ਗੱਲ ਕਰ ਰਹੇ ਹੋ ਨਾ?",
    "od-IN": "ହାଇ {name} ଜୀ, ମୁଁ ପ୍ରିୟା, ସାଉଥ ଇଣ୍ଡିଆ ଫିନଭେଷ୍ଟ ବ୍ୟାଙ୍କରୁ କଥାହୁଁଛି। ଆପଣେ କଥା କରୁଛନ୍ତି तो?",
}

EMI_DETAILS_PART1_TEMPLATE = {
    "en-IN": "Thanks {name}. I'm calling about your loan ending {loan_id}. The EMI of ₹{amount} was due on {due_date} and is still open. I get that delays happen, so I wanted to see how we can close it without stress.",
    "hi-IN": "थैंक्यू {name} जी. आपका {loan_id} वाला लोन है, उसकी ₹{amount} की EMI {due_date} से पेंडिंग है. थोड़ा लेट होना समझ में आता है, बस बिना झंझट इसे कैसे निपटाएं यही देखना था.",
    "ta-IN": "சரி {name}, {loan_id} ல் முடியும் உங்கள் கடனுக்கான ₹{amount} EMI {due_date}க்கு கட்ட வேண்டியது இன்னும் ஓப்பனாக இருக்கு. தாமதம் ஆகலாம் என்பதுனு புரியுது, tension இல்லாமல் எப்படி முடிக்கலாம் என்பதையே பேசுறேன்.",
    "te-IN": "సరి {name} గారు, {loan_id} నంబర్‌‌ ఉన్న మీ లోన్‌కు ₹{amount} EMI {due_date}కి పెండింగ్‌గా ఉంది. ఆలస్యం అవడం సహజం, కాబట్టి ఇబ్బంది లేకుండా ఎలా క్లియర్ చేసేద్దాం అని మాట్లాడుతున్నాను.",
    "ml-IN": "ശരി {name} സാർ, {loan_id} ലായുള്ള ലോണിന്റെ ₹{amount} EMI {due_date}-ന് അടയ്ക്കേണ്ടതായിരുന്നു, അത് ഇനിയും ബാക്കി. താമസമാവുന്നത് മനസ്സിലാകുന്നു, ചില്ലറ ക്ലേശമില്ലാതെ തീർപ്പാക്കാൻ സഹായിക്കാനാണ് വിളിച്ചത്.",
    "gu-IN": "સારું {name}જી, {loan_id} પરના તમારા લોનની ₹{amount} EMI {due_date} થી બાકી છે. મોડું થવું બને છે, તો કોઈ ટેન્શન વગર કેવી રીતે સેટલ કરીએ એ માટે વાત કરવી હતી.",
    "mr-IN": "बरं {name} जी, {loan_id} नंबरच्या लोनची ₹{amount} ची EMI {due_date} पासून बाकी आहे. उशीर होऊ शकतो हे समजतो, म्हणून तणावाशिवाय कसं क्लिअर करायचं ते पाहायला कॉल केला.",
    "bn-IN": "ঠিক আছে {name}, {loan_id} নম্বরের লোনের ₹{amount} EMI {due_date} থেকে ঝুলে আছে. দেরি হওয়া স্বাভাবিক, তাই বিনা ঝামেলায় মিটিয়ে দিতে পারি কি না সেটাই দেখতে ফোন করেছি.",
    "kn-IN": "ಸರಿ {name} ಅವ್ರೇ, {loan_id} ಸಾಲದ ₹{amount} EMI {due_date} ರಿಂದ ಉಳಿದಿದೆ. ಸ್ವಲ್ಪ ತಡವಾಗೋದು ಆಗುತ್ತೇ, ಚಿಂತೆ ಇಲ್ಲದೆ ಹೇಗೆ ಕ್ಲೋಸ್ ಮಾಡೋದು ಅಂತ ನೋಡ್ತಾ ಇದ್ದೀನಿ.",
    "pa-IN": "ਚਲੋ {name} ਜੀ, {loan_id} ਵਾਲੇ ਤੁਹਾਡੇ ਲੋਨ ਦੀ ₹{amount} EMI {due_date} ਤੋਂ ਪੈਂਡਿੰਗ ਹੈ. ਥੋੜ੍ਹੀ ਦੇਰੀ ਹੋ ਜਾਂਦੀ ਹੈ, ਬਿਨਾ ਟੈਂਸ਼ਨ ਕਿਵੇਂ ਕਲੀਅਰ ਕਰੀਏ ਇਹੀ ਗੱਲ ਕਰਨੀ ਸੀ.",
    "od-IN": "ଠିକ ଅଛି {name} ଜୀ, {loan_id} ଲୋନର ₹{amount} EMI {due_date} ଠାରୁ ଅପେଣ୍ଡିଂ ଅଛି। ଦେରି ହେବା ସାଧାରଣ, ଚିନ୍ତା ବିନା କେମିତି ସେଟଲ କରିବା ଭଲ ହେବ ସେଇଥି ପାଇଁ କହୁଛି."
}

EMI_DETAILS_PART2_TEMPLATE = {
    "en-IN": "If we let it hang longer, the bank has to alert the credit bureau and your score can dip. Penalties or collection follow-ups could also start, so better to sort it now.",
    "hi-IN": "अगर ये और लटका तो बैंक को क्रेडिट ब्यूरो को बताना पड़ेगा और स्कोर गिर सकता है. पेनल्टी या कलेक्शन फॉलो-अप भी आ सकते हैं, इसलिए अभी निपटा लें.",
    "ta-IN": "இன்னும் இழுத்தால் கிரெடிட் போர்டுக்கு தகவல் போகும், ஸ்கோர் குறைய வாய்ப்பு உண்டு. அபராதம் அல்லது follow-up calls வரலாம், அதுக்குள் முடிச்சிடலாம்.",
    "te-IN": "ఇంకా దాపురిస్తే క్రెడిట్ బ్యూరోకి సమాచారం వెళ్లి స్కోర్ తగ్గొచ్చు. పెనాల్టీ లేదా కలెక్షన్ కాల్స్ రావచ్చు, కాబట్టి ఇప్పుడు క్లియర్ చేసేద్దాం.",
    "ml-IN": "ഇത് കൂടുതല്‍ നീണ്ടാല്‍ ക്രെഡിറ്റ് ബ്യൂറോയിലേക്ക് റിപ്പോട്ട് പോകും, സ്കോര്‍ താഴാം. പിഴയോ കളക്ഷന്‍ കോള്‍സോ വരാം, അതിനാല്‍ ഉടന്‍ തീര്‍ക്കാം.",
    "gu-IN": "વધારે લટકશે તો ક્રેડિટ બ્યુરો સુધી વાત જશે અને સ્કોર ઘટી શકે. દંડ અથવા કલેક્શન કોલ પણ આવી શકે, એટલે હમણાં જ સેટલ કરી દઈએ.",
    "mr-IN": "अजून थांबवलं तर क्रेडिट ब्युरोला कळेल आणि स्कोर खाली येऊ शकतो. पेनल्टी किंवा कलेक्शन कॉल लागू शकतात, म्हणून आत्ताच मिटवू या.",
    "bn-IN": "আর দেরি হলে ক্রেডিট ব্যুরোতে রিপোর্ট যাবে, স্কোর কমে যেতে পারে। পেনাল্টি বা কালেকশন কলও আসতে পারে, তাই এখনই মিটিয়ে ফেলি.",
    "kn-IN": "ಇನ್ನೂ ವಿಳಂಬವಾಯ್ತು ಅಂದರೆ ಕ್ರೆಡಿಟ್ ಬ್ಯೂರೋಗೆ ವರದಿ ಹೋಗಿ ಸ್ಕೋರ್ ಕೆಳಗೆ ಬೀಳಬಹುದು. ಪೆನಾಲ್ಟಿ ಅಥವಾ ಕಲೆಕ್ಷನ್ ಫಾಲೋ-ಅಪ್ ಬರಬಹುದು, ಆದ್ದರಿಂದ ಈಗಲೇ ಮುಗಿಸೋಣ.",
    "pa-IN": "ਜੇ ਹੋਰ ਲਟਕਿਆ ਰਿਹਾ ਤਾਂ ਗੱਲ ਕਰੈਡਿਟ ਬਿਊਰੋ ਤੱਕ ਜਾਵੇਗੀ ਤੇ ਸਕੋਰ ਡਿੱਗ ਸਕਦਾ ਹੈ. ਪੈਨਲਟੀ ਜਾਂ ਕਲੇਕਸ਼ਨ ਕਾਲ ਵੀ ਆ ਸਕਦੇ ਨੇ, ਸੋ ਚੰਗਾ ਹੈ ਹੁਣੇ ਫਾਇਨਲ ਕਰੀਏ.",
    "od-IN": "ଆଉ ଦେରି କଲେ ବ୍ୟାଙ୍କୁ କ୍ରେଡିଟ ବ୍ୟୁରୋକୁ ଜଣାଇବାକୁ ପଡ଼ିବ ଏବଂ ସ୍କୋର କମିଯିବାର ସମ୍ଭାବନା ରହିବ. ପେନାଲ୍ଟି କିମ୍ବା କଲେକ୍ସନ କଲ୍‌ ମଧ୍ୟ ଆସିପାରେ, ତେଣୁ ଏବେ ସଟିକେ ସେଟଲ କରିଦେବା ଭଲ."
}

AGENT_CONNECT_TEMPLATE = {
    "en-IN": "Want me to loop in someone from our team who can walk you through part-pay or a fresh EMI date?",
    "hi-IN": "चाहें तो मैं अभी हमारे टीम के किसी साथी को जोड़ दूँ, वो पार्ट पेमेंट या नई EMI डेट का आसान तरीका समझा देंगे?",
    "ta-IN": "வேணும்னா நம்ம டீம்ல ஒருவரை லைன்ல சேர்க்கட்டுமா? அவர் part payment, புதிய due date எல்லாம் தெளிவா சொல்லிவிடுவார்.",
    "te-IN": "వెంటనే మా టీమ్‌లోని ఓ వ్యక్తిని లైన్‌లోకి తీసుకురావాలా? ఆయన పార్ట్ పేమెంట్ లేదా కొత్త EMI తేదీల గురించి క్లియర్‌గా చెప్పేస్తారు.",
    "ml-IN": "ഇഷ്ടമാണെങ്കിൽ ഇപ്പോൾ തന്നേ ഞങ്ങളുടെ ടീമിലെ ഒരാളെ ചേർക്കട്ടെ? അവൻ ഭാഗിക പണമടക്കൽ അല്ലെങ്കിൽ പുതിയ EMI തീയതികൾ എളുപ്പത്തിൽ വിശദീകരിക്കും.",
    "gu-IN": "ગમેતોયે હમણાં જ અમારી ટીમમાંથી એક જણને જોડું? તે ભાગ ચુકવણી કે નવી EMI તારીખ વિશે ગાઇડ કરી દેશે.",
    "mr-IN": "हवं असेल तर आत्ताच आमच्या टीममधला एखादा सदस्य लाईनवर आणू का? तो पार्ट पेमेंट किंवा नवीन EMI तारखेबद्दल मार्गदर्शन करेल.",
    "bn-IN": "চাইলে আমি এখনই আমাদের টিমের একজনকে যুক্ত করতে পারি, উনি পার্ট পেমেন্ট বা নতুন EMI তারিখের অপশনগুলো বুঝিয়ে দেবেন.",
    "kn-IN": "ಇಷ್ಟ ಇದ್ದರೆ ಈಗಲೇ ನಮ್ಮ ತಂಡದೊಬ್ಬರನ್ನು ಕರೆತರುತ್ತೀನಿ, ಅವರು ಭಾಗಪಾವತಿ ಅಥವಾ ಹೊಸ EMI ದಿನಾಂಕಗಳ ಬಗ್ಗೆ ಎಲ್ಲ ಹೇಳ್ತಾರೆ.",
    "pa-IN": "ਚਾਹੋ ਤਾਂ ਮੈਂ ਹੁਣੇ ਹੀ ਸਾਡੀ ਟੀਮ ਤੋਂ ਕਿਸੇ ਨੂੰ ਲਾਈਨ ਤੇ ਲਿਆ ਦਿਆਂ? ਉਹ part payment ਜਾਂ ਨਵੀਂ EMI ਤਾਰੀਖ ਦਾ ਸਧਾਰਨ ਰਾਹ ਦੱਸ ਦੇਵੇਗਾ.",
    "od-IN": "ଚାହିଁଥିଲେ ମୁଁ ଏବେ ଆମ ଟିମରୁ ଜଣେ ସହକର୍ମୀଙ୍କୁ କଲ୍‌ରେ ନେଇଆସେ? ସେ ଭାଗି ପେମେଣ୍ଟ କିମ୍ବା ନୂଆ EMI ତାରିଖ ସହଜରେ ବୁଝାଇଦେବେ."
}

GOODBYE_TEMPLATE = {
    "en-IN": "Alright, no worries. If it works later, just give us a ring. Thanks for your time!",
    "hi-IN": "ठीक है, कोई बात नहीं. जब भी सही लगे हमें कॉल कर दीजिए. धन्यवाद!",
    "ta-IN": "சரி, கவலை வேண்டாம். பிறகு நேரம் கிடைத்தா நமக்கே ஒரு call பண்ணுங்க. நன்றி!",
    "te-IN": "సరే, సమస్య లేదు. తర్వాత సమయం దొరికితే మాకు కాల్ చేయండి. ధన్యవాదాలు!",
    "ml-IN": "ശരി, പ്രശ്നമില്ല. പിന്നീട് സൗകര്യം കിട്ടുമ്പോൾ ഒരു ഫോൺ തരൂ. നന്ദി!",
    "gu-IN": "બરાબર, કોઈ ટેન્શન નહીં. પછી અનુકૂળ લાગે ત્યારે અમને ફોન કરજો. ધન્યવાદ!",
    "mr-IN": "ठीक आहे, काही हरकत नाही. नंतर वेळ मिळाला की आम्हाला कॉल करा. धन्यवाद!",
    "bn-IN": "ঠিক আছে, কোনো সমস্যা নেই। পরে সুবিধা মতো আমাদের একটা ফোন করে দেবেন। ধন্যবাদ!",
    "kn-IN": "ಸರಿ, ಸಮಸ್ಯೆ ಇಲ್ಲ. ನಂತರ ಸೌಕರ್ಯ ಇದ್ದಾಗ ನಮಗೆ ಒಂದು ಕಾಲ್ ಮಾಡಿ. ಧನ್ಯವಾದಗಳು!",
    "pa-IN": "ਠੀਕ ਹੈ, ਕੋਈ ਗੱਲ ਨਹੀਂ. ਜਦੋਂ ਵੀ ਤੁਹਾਡੇ ਲਈ ਠੀਕ ਹੋਵੇ ਸਾਨੂੰ ਇੱਕ ਕਾਲ ਕਰ ਦੇਣਾ. ਧੰਨਵਾਦ!",
    "od-IN": "ଠିକ ଅଛି, କିଛି ଚିନ୍ତା ନାହିଁ. ପରେ ସମୟ ହେଲେ ଆମକୁ ଫୋନ କରନ୍ତୁ. ଧନ୍ୟବାଦ!"
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
    "od-IN": "ଆପଣ ଏବେ କହିପାରିବେ।",
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


async def play_connecting_prompt(websocket, language: str = "en-IN") -> None:
    prompt = "Wait a second, I will connect you to our agent."
    logger.tts.info(f"🔁 Connecting prompt: {prompt}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt, language or "en-IN")
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
        return "od-IN"
    
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
    'odisha': 'od-IN',
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
        return "OK"  # Always return OK so Exotel flow isn't broken

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
    current_language = "en-IN"

    async def speak_text(text: str, language: Optional[str] = None) -> None:
        if not text:
            return
        lang_code = language or current_language or "en-IN"
        audio_bytes = await sarvam_handler.synthesize_tts(text, lang_code)
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
        if not info.get('lang'):
            info['lang'] = 'en-IN'
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
        nonlocal call_sid, customer_info, conversation_stage, last_transcription_time, claude_chat, current_language

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
        current_language = customer_info.get('lang') or current_language
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
        nonlocal conversation_stage, confirmation_attempts, claude_chat, current_language

        normalized = transcript.lower()
        affirmative = {"yes", "yeah", "yep", "haan", "ha", "correct", "sure", "yup"}
        negative = {"no", "nah", "nope", "nahi", "na"}

        is_affirmative = any(word in normalized for word in affirmative)
        is_negative = any(word in normalized for word in negative)

        if is_affirmative:
            logger.websocket.info("✅ Customer confirmed identity")
            await play_connecting_prompt(websocket, current_language)
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
                    if intro_text:
                        intro_language = detect_language(intro_text)
                        if intro_language and intro_language != current_language:
                            logger.websocket.info(
                                f"🌐 Switching assistant voice language {current_language} → {intro_language}"
                            )
                            current_language = intro_language
                    await speak_text(intro_text, current_language)
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
        nonlocal claude_turns, conversation_stage, interaction_complete, refusal_count, current_language
        if not transcript:
            return "continue"
        if not claude_chat:
            await speak_text("Thank you for explaining. I'll connect you to our agent now.", "en-IN")
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
            agent_text = (
                "I understand this has been difficult. I'll transfer you to our specialist for more help."
            )
            status = "escalate"
        elif status == "escalate" and not allowed_to_escalate:
            logger.websocket.info(
                f"ℹ️ Escalation deferred (refusal_count={refusal_count} < {CLAUDE_REFUSAL_THRESHOLD}); continuing conversation"
            )
            status = "continue"

        if transcript_logger:
            transcript_logger.add_transcript(f"[Claude_raw] {raw_reply}", time.time())
            transcript_logger.add_transcript(f"[Claude] {agent_text}", time.time())
        if cleaned_agent_text:
            detected_response_language = detect_language(cleaned_agent_text)
            if detected_response_language and detected_response_language != current_language:
                logger.websocket.info(
                    f"🌐 Switching assistant voice language {current_language} → {detected_response_language}"
                )
                current_language = detected_response_language

        if allowed_to_escalate:
            logger.websocket.info(
                f"ℹ️ Refusal threshold reached ({refusal_count}); skipping LLM response and transferring to agent"
            )
            await play_connecting_prompt(websocket, current_language)
            conversation_stage = "WAITING_DISCONNECT"
            interaction_complete = True
            return "end"

        await speak_text(agent_text, current_language)

        if status == "promise":
            await speak_text(
                "Thank you for confirming the repayment. We appreciate your cooperation. Goodbye.",
                current_language
            )
            conversation_stage = "GOODBYE_SENT"
            interaction_complete = True
            return "end"

        if status == "escalate":
            await speak_text(
                "I understand. I'll transfer you to our agent for further assistance.",
                current_language
            )
            await play_connecting_prompt(websocket, current_language)
            conversation_stage = "WAITING_DISCONNECT"
            interaction_complete = True
            return "end"

        if claude_turns >= MAX_CLAUDE_TURNS:
            if allowed_to_escalate:
                logger.websocket.info(
                    f"ℹ️ Max Claude turns reached with refusal threshold ({refusal_count}); transferring to agent"
                )
                await play_connecting_prompt(websocket, current_language)
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
            detected_lang = detect_language(transcript)
            if detected_lang and detected_lang != current_language:
                logger.websocket.info(
                    f"🌐 Switching customer language {current_language} → {detected_lang}"
                )
                current_language = detected_lang

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
async def upload_customers(request: Request, file: UploadFile = File(...)):
    """
    Accepts a CSV or Excel file, processes it, and stores customer data in the database.
    """
    print(f"📁 [CHECKPOINT] /api/upload-customers endpoint hit")
    print(f"📁 [CHECKPOINT] File name: {file.filename}")
    print(f"📁 [CHECKPOINT] File content type: {file.content_type}")
    
    try:
        file_data = await file.read()
        print(f"📁 [CHECKPOINT] File size: {len(file_data)} bytes")
        
        websocket_id = request.query_params.get("websocket_id") or request.headers.get("X-Dashboard-Session")
        result = await call_service.upload_and_process_customers(
            file_data,
            file.filename,
            websocket_id=websocket_id,
        )
        print(f"📁 [CHECKPOINT] File processing result: {result}")

        timestamp = datetime.utcnow().isoformat()

        if result.get("success"):
            processing = result.get("processing_results", {})
            total_records = processing.get("total_records") or processing.get("processed_records") or 0
            processed_records = processing.get("processed_records") or processing.get("success_records") or total_records

            progress = 100.0
            if total_records:
                progress = round((processed_records / total_records) * 100, 1)

            await broadcast_dashboard_update(
                {
                    "type": "upload_progress",
                    "event": "upload_progress",
                    "progress": progress,
                    "message": f"Processed {processed_records}/{total_records} records",
                    "timestamp": timestamp,
                }
            )

            await broadcast_dashboard_update(
                {
                    "type": "upload_complete",
                    "event": "upload_complete",
                    "upload_id": result.get("upload_id"),
                    "filename": file.filename,
                    "processing_results": processing,
                    "timestamp": timestamp,
                }
            )

            await broadcast_dashboard_update(
                {
                    "type": "data_update",
                    "event": "data_update",
                    "resource": "customers",
                    "timestamp": timestamp,
                }
            )
        else:
            await broadcast_dashboard_update(
                {
                    "type": "upload_error",
                    "event": "upload_error",
                    "message": result.get("error") or result.get("message") or "Upload failed",
                    "timestamp": timestamp,
                }
            )

        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in upload_customers endpoint: {e}")
        error_event = {
            "type": "upload_error",
            "event": "upload_error",
            "message": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }
        await broadcast_dashboard_update(error_event)
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

        call_results = result.get("results", []) if isinstance(result, dict) else []
        for call_result in call_results:
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

        total_bulk = result.get("total_calls") if isinstance(result, dict) else len(customer_ids)
        successful_bulk = result.get("successful_calls") if isinstance(result, dict) else 0
        failed_bulk = result.get("failed_calls") if isinstance(result, dict) else max(total_bulk - successful_bulk, 0)

        await broadcast_dashboard_update(
            {
                "type": "bulk_operation_update",
                "event": "bulk_operation_update",
                "operation": "bulk_calls",
                "total": total_bulk,
                "successful": successful_bulk,
                "failed": failed_bulk,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in trigger_bulk_calls endpoint: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/customers")
async def get_all_customers():
    """
    Retrieves all customers with enriched loan and call session data.
    """
    print(f"👥 [CHECKPOINT] /api/customers endpoint hit")
    
    session = db_manager.get_session()
    try:
        customers = (
            session.query(Customer)
            .options(
                joinedload(Customer.loans),
                joinedload(Customer.call_sessions),
            )
            .all()
        )
        print(f"👥 [CHECKPOINT] Found {len(customers)} customers in database")

        result: List[Dict[str, Any]] = []

        for customer in customers:
            # Determine latest call status
            latest_status = customer.status or getattr(customer, "call_status", None)
            if not latest_status and customer.call_sessions:
                latest_session = max(
                    customer.call_sessions,
                    key=lambda session_obj: session_obj.created_at or datetime.min,
                )
                latest_status = latest_session.status or "ready"
            if not latest_status:
                latest_status = "ready"

            # Aggregate loan information
            total_loans = len(customer.loans)
            total_outstanding = 0.0
            total_due = 0.0
            loans_payload: List[Dict[str, Any]] = []

            for loan in customer.loans:
                outstanding_amount = float(loan.outstanding_amount or 0)
                due_amount = float(loan.due_amount or 0)
                total_outstanding += outstanding_amount
                total_due += due_amount

                loans_payload.append(
                    {
                        "id": str(loan.id),
                        "loan_id": loan.loan_id,
                        "outstanding_amount": outstanding_amount,
                        "due_amount": due_amount,
                        "next_due_date": format_ist_datetime(loan.next_due_date),
                        "last_paid_date": format_ist_datetime(loan.last_paid_date),
                        "last_paid_amount": float(loan.last_paid_amount or 0),
                        "status": loan.status,
                        "cluster": loan.cluster,
                        "branch": loan.branch,
                        "branch_contact_number": loan.branch_contact_number,
                        "employee_name": loan.employee_name,
                        "employee_id": loan.employee_id,
                        "employee_contact_number": loan.employee_contact_number,
                        "created_at": format_ist_datetime(loan.created_at),
                        "updated_at": format_ist_datetime(loan.updated_at),
                    }
                )

            primary_loan = customer.loans[0] if customer.loans else None

            customer_payload = {
                "id": str(customer.id),
                "full_name": customer.full_name,
                "primary_phone": customer.primary_phone,
                "state": customer.state,
                "email": customer.email,
                "national_id": customer.national_id,
                "do_not_call": customer.do_not_call,
                "first_uploaded_at": format_ist_datetime(customer.first_uploaded_at),
                "last_contact_date": format_ist_datetime(customer.last_contact_date),
                "created_at": format_ist_datetime(customer.created_at),
                "updated_at": format_ist_datetime(customer.updated_at),
                "status": customer.status or getattr(customer, "call_status", None) or "ready",
                "call_status": latest_status,
                "total_loans": total_loans,
                "total_outstanding": total_outstanding,
                "total_due": total_due,
                "loan_id": primary_loan.loan_id if primary_loan else None,
                "outstanding_amount": float(primary_loan.outstanding_amount or 0)
                if primary_loan
                else 0,
                "due_amount": float(primary_loan.due_amount or 0) if primary_loan else 0,
                "next_due_date": format_ist_datetime(primary_loan.next_due_date)
                if primary_loan
                else None,
                "last_paid_date": format_ist_datetime(primary_loan.last_paid_date)
                if primary_loan
                else None,
                "last_paid_amount": float(primary_loan.last_paid_amount or 0)
                if primary_loan
                else 0,
                "cluster": primary_loan.cluster if primary_loan else None,
                "branch": primary_loan.branch if primary_loan else None,
                "branch_contact_number": primary_loan.branch_contact_number
                if primary_loan
                else None,
                "employee_name": primary_loan.employee_name if primary_loan else None,
                "employee_id": primary_loan.employee_id if primary_loan else None,
                "employee_contact_number": primary_loan.employee_contact_number
                if primary_loan
                else None,
                "loans": loans_payload,
            }

            result.append(customer_payload)

        print(f"👥 [CHECKPOINT] Returning customer list successfully")
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in get_all_customers endpoint: {e}")
        return []
    finally:
        session.close()


@app.get("/api/uploaded-files")
async def get_uploaded_files(
    page: int = 1,
    page_size: int = 25,
    date_filter: Optional[str] = None,
):
    """Return paginated list of uploaded CSV batches."""
    print(
        f"📄 [CHECKPOINT] /api/uploaded-files hit - page={page}, page_size={page_size}, date_filter={date_filter}"
    )

    page = max(page, 1)
    page_size = max(min(page_size, 1000), 1)

    session = db_manager.get_session()
    try:
        query = session.query(FileUpload).order_by(FileUpload.uploaded_at.desc())

        if date_filter:
            now_ist = get_ist_timestamp()
            if date_filter == "today":
                start_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
            elif date_filter == "week":
                start_ist = now_ist - timedelta(days=7)
            elif date_filter == "month":
                start_ist = now_ist - timedelta(days=30)
            else:
                start_ist = None

            if start_ist:
                start_utc = start_ist.astimezone(pytz.UTC).replace(tzinfo=None)
                query = query.filter(FileUpload.uploaded_at >= start_utc)

        total_count = query.count()
        offset = (page - 1) * page_size
        uploads = query.offset(offset).limit(page_size).all()

        uploads_payload = []
        for upload in uploads:
            uploads_payload.append(
                {
                    "id": str(upload.id),
                    "filename": upload.filename,
                    "original_filename": upload.original_filename,
                    "uploaded_by": upload.uploaded_by,
                    "uploaded_at": format_ist_datetime(upload.uploaded_at),
                    "total_records": upload.total_records,
                    "processed_records": upload.processed_records,
                    "success_records": upload.success_records,
                    "failed_records": upload.failed_records,
                    "status": upload.status,
                    "processing_errors": upload.processing_errors,
                }
            )

        total_pages = (total_count + page_size - 1) // page_size if page_size else 1

        return {
            "success": True,
            "uploads": uploads_payload,
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        }
    except Exception as exc:
        print(f"❌ [CHECKPOINT] Exception in get_uploaded_files: {exc}")
        return {
            "success": False,
            "error": str(exc),
            "uploads": [],
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_count": 0,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            },
        }
    finally:
        session.close()


@app.get("/api/uploaded-files/ids")
async def get_uploaded_file_ids(date_filter: Optional[str] = None):
    """Return list of upload IDs for selection controls."""
    print(f"📄 [CHECKPOINT] /api/uploaded-files/ids hit - date_filter={date_filter}")

    session = db_manager.get_session()
    try:
        query = session.query(FileUpload).order_by(FileUpload.uploaded_at.desc())

        if date_filter:
            now_ist = get_ist_timestamp()
            if date_filter == "today":
                start_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
            elif date_filter == "week":
                start_ist = now_ist - timedelta(days=7)
            elif date_filter == "month":
                start_ist = now_ist - timedelta(days=30)
            else:
                start_ist = None

            if start_ist:
                start_utc = start_ist.astimezone(pytz.UTC).replace(tzinfo=None)
                query = query.filter(FileUpload.uploaded_at >= start_utc)

        upload_ids = [str(upload.id) for upload in query.all()]
        return {"success": True, "upload_ids": upload_ids, "total_count": len(upload_ids)}
    except Exception as exc:
        print(f"❌ [CHECKPOINT] Exception in get_uploaded_file_ids: {exc}")
        return {"success": False, "error": str(exc), "upload_ids": [], "total_count": 0}
    finally:
        session.close()


@app.get("/api/uploaded-files/{upload_id}/details")
async def get_upload_details(upload_id: str):
    """Return detailed information about a specific upload batch."""
    print(f"📄 [CHECKPOINT] /api/uploaded-files/{upload_id}/details hit")

    session = db_manager.get_session()
    try:
        upload = (
            session.query(FileUpload)
            .filter(FileUpload.id == upload_id)
            .first()
        )

        if not upload:
            return {"success": False, "error": "Upload not found"}

        rows = (
            session.query(UploadRow)
            .filter(UploadRow.file_upload_id == upload_id)
            .order_by(UploadRow.line_number.asc())
            .all()
        )

        row_payload = []
        for row in rows:
            row_payload.append(
                {
                    "id": str(row.id),
                    "line_number": row.line_number,
                    "raw_data": row.raw_data,
                    "status": row.status,
                    "error": row.error,
                    "match_method": row.match_method,
                    "match_customer_id": str(row.match_customer_id)
                    if row.match_customer_id
                    else None,
                    "match_loan_id": str(row.match_loan_id) if row.match_loan_id else None,
                    "created_at": format_ist_datetime(row.matched_at),
                }
            )

        return {
            "success": True,
            "upload_details": {
                "id": str(upload.id),
                "filename": upload.filename,
                "original_filename": upload.original_filename,
                "uploaded_by": upload.uploaded_by,
                "uploaded_at": format_ist_datetime(upload.uploaded_at),
                "total_records": upload.total_records,
                "processed_records": upload.processed_records,
                "success_records": upload.success_records,
                "failed_records": upload.failed_records,
                "status": upload.status,
                "processing_errors": upload.processing_errors,
                "rows": row_payload,
            },
        }
    except Exception as exc:
        print(f"❌ [CHECKPOINT] Exception in get_upload_details: {exc}")
        return {"success": False, "error": str(exc)}
    finally:
        session.close()


@app.get("/api/uploaded-files/{upload_id}/download")
async def download_upload_report(upload_id: str):
    """Download CSV report for a specific upload batch."""
    print(f"📄 [CHECKPOINT] /api/uploaded-files/{upload_id}/download hit")

    session = db_manager.get_session()
    try:
        upload = (
            session.query(FileUpload)
            .filter(FileUpload.id == upload_id)
            .first()
        )
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")

        rows = (
            session.query(UploadRow)
            .filter(UploadRow.file_upload_id == upload_id)
            .order_by(UploadRow.line_number.asc())
            .all()
        )

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(
            [
                "Line Number",
                "Status",
                "Match Method",
                "Customer ID",
                "Loan ID",
                "Error",
                "Raw Data",
            ]
        )

        for row in rows:
            writer.writerow(
                [
                    row.line_number,
                    row.status,
                    row.match_method,
                    row.match_customer_id,
                    row.match_loan_id,
                    row.error,
                    json.dumps(row.raw_data),
                ]
            )

        output.seek(0)
        original_name = upload.original_filename or upload.filename or "upload_report"
        base_name = Path(original_name).stem or "upload_report"
        headers = {
            "Content-Disposition": f'attachment; filename="{base_name}_report.csv"'
        }

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers=headers,
        )
    except HTTPException:
        raise
    except Exception as exc:
        print(f"❌ [CHECKPOINT] Exception in download_upload_report: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        session.close()


@app.get("/api/call-statuses")
async def get_call_statuses():
    """Return recent call status updates for dashboard."""
    print("📞 [CHECKPOINT] /api/call-statuses hit")
    session = db_manager.get_session()
    try:
        updates = (
            session.query(CallStatusUpdate)
            .options(
                joinedload(CallStatusUpdate.call_session).joinedload(CallSession.customer)
            )
            .order_by(CallStatusUpdate.timestamp.desc())
            .limit(100)
            .all()
        )

        statuses: List[Dict[str, Any]] = []
        for update in updates:
            call_session = update.call_session
            customer = call_session.customer if call_session else None
            statuses.append(
                {
                    "id": str(update.id),
                    "call_sid": call_session.call_sid if call_session else None,
                    "customer_name": customer.full_name if customer else None,
                    "customer_phone": customer.primary_phone if customer else None,
                    "status": update.status,
                    "message": update.message,
                    "timestamp": format_ist_datetime(update.timestamp),
                    "extra_data": update.extra_data,
                }
            )

        return {"success": True, "statuses": statuses}
    except Exception as exc:
        print(f"❌ [CHECKPOINT] Exception in get_call_statuses: {exc}")
        return {"success": False, "error": str(exc), "statuses": []}
    finally:
        session.close()


@app.get("/api/call-statuses/{call_sid}")
async def get_call_status_history(call_sid: str):
    """Return detailed status history for a specific call."""
    print(f"📞 [CHECKPOINT] /api/call-statuses/{call_sid} hit")
    session = db_manager.get_session()
    try:
        call_session = get_call_session_by_sid(session, call_sid)
        if not call_session:
            return {"success": False, "error": "Call session not found"}

        updates = (
            session.query(CallStatusUpdate)
            .filter(CallStatusUpdate.call_session_id == call_session.id)
            .order_by(CallStatusUpdate.timestamp.asc())
            .all()
        )

        statuses = [
            {
                "id": str(update.id),
                "status": update.status,
                "message": update.message,
                "timestamp": format_ist_datetime(update.timestamp),
                "extra_data": update.extra_data,
            }
            for update in updates
        ]

        customer = call_session.customer
        return {
            "success": True,
            "call_sid": call_sid,
            "customer_name": customer.full_name if customer else None,
            "customer_phone": customer.primary_phone if customer else None,
            "statuses": statuses,
        }
    except Exception as exc:
        print(f"❌ [CHECKPOINT] Exception in get_call_status_history: {exc}")
        return {"success": False, "error": str(exc), "statuses": []}
    finally:
        session.close()

@app.post("/exotel-webhook")
async def exotel_webhook(request: Request):
    """
    Exotel webhook: robustly handles declines/rejects arriving on leg SIDs
    and/or with DialCallStatus, and falls back by phone if SID doesn't match.
    """
    try:
        form = await request.form()
        payload = dict(form)

        # ---- Extract IDs/numbers from all likely Exotel keys ----
        sid_candidates = []
        for k in ("CallSid", "ParentCallSid", "DialCallSid", "CallGuid", "Guid"):
            v = payload.get(k)
            if v:
                sid_candidates.append(v)

        to_number = payload.get("DialWhomNumber") or payload.get("To")
        from_number = payload.get("From")

        # ---- Normalize status from any field Exotel may send ----
        raw_status = (
            payload.get("CallStatus")
            or payload.get("Status")
            or payload.get("DialCallStatus")
            or ""
        ).strip().lower()

        # Map Exotel → your internal CallStatus
        status_map = {
            # progress
            "queued":        (CallStatus.CALLING,          "Call ringing customer"),
            "ringing":       (CallStatus.CALLING,          "Call ringing customer"),
            "in-progress":   (CallStatus.CALL_IN_PROGRESS, "Call in progress"),
            "in_progress":   (CallStatus.CALL_IN_PROGRESS, "Call in progress"),
            "answered":      (CallStatus.CALL_IN_PROGRESS, "Call in progress"),
            "agent_transfer":(CallStatus.AGENT_TRANSFER,   "Agent transferred"),

            # terminal (completed)
            "completed":     (CallStatus.CALL_COMPLETED,   "Call completed"),
            "finished":      (CallStatus.CALL_COMPLETED,   "Call completed"),
            "end":           (CallStatus.CALL_COMPLETED,   "Call completed"),
            "terminal":      (CallStatus.CALL_COMPLETED,   "Call completed"),
            "hangup":        (CallStatus.CALL_COMPLETED,   "Call completed"),
            "customer_hangup": (CallStatus.CALL_COMPLETED, "Call completed (customer hung up)"),
            "user_hangup":   (CallStatus.CALL_COMPLETED,   "Call completed (user hung up)"),

            # terminal (no connect → disconnected)
            "busy":          (CallStatus.DISCONNECTED,     "Call disconnected (busy)"),
            "no-answer":     (CallStatus.DISCONNECTED,     "Call disconnected before answer"),
            "no_answer":     (CallStatus.DISCONNECTED,     "Call disconnected before answer"),
            "noanswer":      (CallStatus.DISCONNECTED,     "Call disconnected before answer"),
            "not_answered":  (CallStatus.DISCONNECTED,     "Call disconnected before answer"),
            "not-answered":  (CallStatus.DISCONNECTED,     "Call disconnected before answer"),
            "canceled":      (CallStatus.DISCONNECTED,     "Call disconnected (canceled)"),
            "cancelled":     (CallStatus.DISCONNECTED,     "Call disconnected (canceled)"),

            # terminal (error)
            "failed":        (CallStatus.FAILED,           "Call failed"),
        }
        mapped_status, status_message = status_map.get(raw_status, (None, None))

        session = db_manager.get_session()
        try:
            call_session = None

            # 1) Try all SID variants first (parent/child/leg/etc.)
            for sid in sid_candidates:
                call_session = get_call_session_by_sid(session, sid)
                if call_session:
                    break

            # 2) Fallback by phone → most recent OPEN call for that customer
            if not call_session and to_number:
                try:
                    customer = get_customer_by_phone(session, to_number)
                except Exception:
                    customer = None
                if customer:
                    # only pick an open session so we don’t touch old rows
                    call_session = (
                        session.query(CallSession)
                        .filter(
                            CallSession.customer_id == customer.id,
                            CallSession.status.in_(
                                [CallStatus.CALLING, CallStatus.CALL_IN_PROGRESS]
                            )
                        )
                        .order_by(CallSession.created_at.desc())
                        .first()
                    )

            # (optional) last-ditch by From if that’s how you dial out
            if not call_session and from_number:
                try:
                    customer = get_customer_by_phone(session, from_number)
                except Exception:
                    customer = None
                if customer:
                    call_session = (
                        session.query(CallSession)
                        .filter(
                            CallSession.customer_id == customer.id,
                            CallSession.status.in_(
                                [CallStatus.CALLING, CallStatus.CALL_IN_PROGRESS]
                            )
                        )
                        .order_by(CallSession.created_at.desc())
                        .first()
                    )

            if not call_session:
                logger.error.error(f"❌ [WEBHOOK] No matching call_session. Payload={payload}")
                return {"status": "ok", "info": "no matching session"}  # Ack Exotel; allow retries

            # If status is unknown, infer sensible terminal outcome
            if mapped_status is None:
                current = call_session.status or CallStatus.CALLING
                if current in {CallStatus.CALLING, CallStatus.CALL_IN_PROGRESS}:
                    mapped_status = CallStatus.DISCONNECTED
                    status_message = f"Call disconnected ({raw_status or 'unknown'})"
                else:
                    mapped_status = CallStatus.FAILED
                    status_message = f"Call failed ({raw_status or 'unknown'})"

            # Idempotent: don’t regress if the row already closed
            if call_session.status in {CallStatus.CALL_COMPLETED, CallStatus.DISCONNECTED, CallStatus.FAILED}:
                logger.database.info(
                    f"ℹ️ [WEBHOOK] Session already terminal ({call_session.status}); skipping"
                )
                return {"status": "ok", "info": "already terminal"}

            # Apply the update
            update_call_status(
                session=session,
                call_sid=call_session.call_sid,  # update the original parent row
                status=mapped_status,
                message=status_message,
                extra_data={"webhook": payload},
            )
            session.commit()
            logger.database.info(
                f"✅ [WEBHOOK] {call_session.call_sid} → {mapped_status} ({status_message})"
            )

            return {"status": "success", "new_status": str(mapped_status)}

        except Exception as db_err:
            session.rollback()
            logger.error.error(f"❌ [WEBHOOK] DB error: {db_err}")
            import traceback; traceback.print_exc()
            return {"status": "error", "message": str(db_err)}
        finally:
            session.close()

    except Exception as e:
        logger.error.error(f"❌ [WEBHOOK] Critical error: {e}")
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
                "call_status": customer.status if customer else None,
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
                print(f"   Customer Status: {call_session.customer.status}")
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
                "call_status": customer.status,
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
                "customer_status": call_session.customer.status if call_session.customer else None,
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
from datetime import datetime, timedelta

@app.post("/status-callback", response_class=PlainTextResponse)
async def status_callback(request: Request):
    """
    Exotel call status callback.
    Robustly correlates by SID variants and phone if needed.
    Maps declined/rejected/no-answer to DISCONNECTED so 'calling' doesn't stick.
    """
    data = await request.form()
    payload = dict(data)

    # --- Extract IDs & numbers from possible Exotel payload variants ---
    sid_candidates = []
    for k in ("CallSid", "ParentCallSid", "DialCallSid", "CallGuid", "Guid"):
        v = payload.get(k)
        if v:
            sid_candidates.append(v)

    to_number = payload.get("DialWhomNumber") or payload.get("To")
    from_number = payload.get("From")

    # --- Normalize status from multiple possible fields ---
    raw_status = (
        payload.get("Status")              # Exotel normal
        or payload.get("CallStatus")       # sometimes used
        or payload.get("DialCallStatus")   # leg status on declines
        or ""
    ).strip().lower()

    status_map = {
        # in-progress
        "queued": "calling",
        "ringing": "calling",
        "in-progress": "call_in_progress",
        "in_progress": "call_in_progress",
        "answered": "call_in_progress",
        "agent_transfer": "agent_transfer",

        # terminal (ok)
        "completed": "call_completed",
        "terminal": "call_completed",
        "end": "call_completed",
        "finished": "call_completed",
        "hangup": "call_completed",
        "customer_hangup": "call_completed",
        "user_hangup": "call_completed",

        # terminal (no connect)
        "busy": "disconnected",
        "no-answer": "disconnected",
        "no_answer": "disconnected",
        "canceled": "disconnected",
        "cancelled": "disconnected",

        # terminal (error)
        "failed": "failed",
    }
    normalized = status_map.get(raw_status, raw_status or "failed")
    allowed = {"calling", "call_in_progress", "call_completed", "disconnected", "failed", "agent_transfer"}
    if normalized not in allowed:
        normalized = "failed"

    logger.websocket.info(f"📡 Exotel /status-callback payload: {payload} → normalized={normalized}")

    # --- Correlate the call session ---
    session = db_manager.get_session()
    try:
        call_session = None

        # 1) Try all SID variants first
        for sid in sid_candidates:
            call_session = get_call_session_by_sid(session, sid)
            if call_session:
                break

        # 2) Fallback by number within a recent window for open calls
        if not call_session and to_number:
            fifteen_min_ago = datetime.utcnow() - timedelta(minutes=15)
            call_session = (
                session.query(CallSession)
                .filter(
                    CallSession.to_number == to_number,
                    CallSession.created_at >= fifteen_min_ago,
                    CallSession.status.in_([CallStatus.CALLING, CallStatus.CALL_IN_PROGRESS])
                )
                .order_by(CallSession.created_at.desc())
                .first()
            )

        if not call_session and from_number:
            fifteen_min_ago = datetime.utcnow() - timedelta(minutes=15)
            call_session = (
                session.query(CallSession)
                .filter(
                    CallSession.from_number == from_number,
                    CallSession.created_at >= fifteen_min_ago,
                    CallSession.status.in_([CallStatus.CALLING, CallStatus.CALL_IN_PROGRESS])
                )
                .order_by(CallSession.created_at.desc())
                .first()
            )

        if not call_session:
            logger.error.error(f"❌ /status-callback: No call_session matched. Payload: {payload}")
            return "OK"  # Ack to Exotel; they may retry

        # --- Preserve agent_transfer if already set ---
        if call_session.status == CallStatus.AGENT_TRANSFER:
            logger.database.info(f"ℹ️ Preserve AGENT_TRANSFER for CallSid={call_session.call_sid}")
            # Optionally log a terminal event without overwriting main status
            status_update = CallStatusUpdate(
                call_session_id=call_session.id,
                status=CallStatus.COMPLETED,
                message="Call ended after agent transfer"
            )
            session.add(status_update)
            if call_session.customer_id:
                update_customer_call_status(session, str(call_session.customer_id), "agent_transfer", call_attempt=True)
            session.commit()
            await push_status_update(
                call_session.call_sid, "agent_transfer", "Call ended after agent transfer",
                customer_id=str(call_session.customer_id) if call_session.customer_id else None,
            )
            return "OK"

        # --- Idempotent/terminal-safe updates ---
        # Don’t regress if already terminal
        if call_session.status in {CallStatus.CALL_COMPLETED, CallStatus.DISCONNECTED, CallStatus.FAILED}:
            logger.database.info(f"ℹ️ CallSid={call_session.call_sid} already terminal ({call_session.status}), skipping")
            return "OK"

        status_messages = {
            "calling": "Call ringing customer",
            "call_in_progress": "Call in progress",
            "call_completed": "Call completed",
            "disconnected": "Call disconnected before answer",
            "failed": "Call failed",
            "agent_transfer": "Agent transferred",
        }
        msg = status_messages.get(normalized, normalized)

        updated_session = update_call_status(
            session=session,
            call_sid=call_session.call_sid,
            status=normalized,
            message=msg,
            extra_data={"webhook": payload},
        )

        # Mirror to customer state (string form)
        customer_state = {
            "calling": "calling",
            "call_in_progress": "call_in_progress",
            "call_completed": "call_completed",
            "disconnected": "disconnected",
            "failed": "failed",
            "agent_transfer": "agent_transfer",
        }[normalized]

        if updated_session and updated_session.customer_id:
            update_customer_call_status(session, str(updated_session.customer_id), customer_state, call_attempt=True)

        session.commit()

        await push_status_update(
            call_session.call_sid,
            customer_state,
            msg,
            customer_id=str(call_session.customer_id) if call_session.customer_id else None,
        )

        return "OK"

    except Exception as e:
        session.rollback()
        logger.error.error(f"❌ /status-callback error: {e}")
        import traceback; traceback.print_exc()
        return "OK"
    finally:
        session.close()



@app.post("/api/update-customer-status")
async def update_customer_status(request: Request):
    """Update customer call status in the database"""
    try:
        data = await request.json()
        customer_id = data.get('customer_id')
        call_status = (data.get('call_status') or '').lower()
        
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
        call_status = (data.get('call_status') or '').lower()
        
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


@app.post("/api/update-bulk-status")
async def update_bulk_status(request: Request):
    """Alias endpoint for enhanced dashboard bulk status updates."""
    return await update_bulk_customer_status(request)

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
