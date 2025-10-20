import os
import asyncio
import base64
import csv
import json
import logging
from utils.logger import logger  # Add this import
import os
import re
import tempfile
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
import pytz
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from contextlib import asynccontextmanager, suppress
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
from urllib.parse import quote

import httpx
import pandas as pd
import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import (Body, FastAPI, File, HTTPException, Request, UploadFile,
                     WebSocket, Depends, Query)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse, 
                              RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from requests.auth import HTTPBasicAuth
from sqlalchemy.orm import joinedload
from starlette.websockets import WebSocketDisconnect
from starlette.middleware.sessions import SessionMiddleware

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
    update_customer_call_status_by_phone,
    update_customer_call_status,
)
from services.call_management import call_service
from utils import bedrock_client
from utils.agent_transfer import trigger_exotel_agent_transfer
from utils.logger import setup_application_logging, logger, AuthError
from utils.production_asr import ProductionSarvamHandler
from utils.redis_session import (init_redis, redis_manager,
                                 generate_websocket_session_id)
# Import authentication module
from utils.cognito_hosted_auth import cognito_auth, get_current_user, get_current_user_optional
from utils.session_middleware import RedisSessionMiddleware, get_session

# Set up transcript directory
base_transcript_dir = Path(os.getenv("VOICEBOT_RUNTIME_DIR") or Path(__file__).resolve().parent)
base_transcript_dir = base_transcript_dir.expanduser()
try:
    base_transcript_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Using transcript directory: {base_transcript_dir}")
except Exception as e:
    logger.error(f"Failed to create transcript directory: {e}")
    raise


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
        logger.error("❌ Database initialization failed")
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

# Add Redis-based Session middleware for Cognito authentication
app.add_middleware(
    RedisSessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "your-secret-key-change-in-production-123456789"),
    max_age=3600 * 2,  # 2 hours session expiration
    session_cookie="session_id",
    redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    domain=None,        # Let the browser handle the domain automatically
    secure=True,        # HTTPS required for ngrok
    httponly=True,      # Prevent XSS
    samesite="none"     # Cross-domain cookies for ngrok
)

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
sarvam_handler = ProductionSarvamHandler(SARVAM_API_KEY)

AWS_REGION = os.getenv("AWS_REGION") or "eu-north-1"

# Claude configuration
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", 1000))
CLAUDE_TEMPERATURE = float(os.getenv("CLAUDE_TEMPERATURE", 0.7))
CLAUDE_MODEL_ID = os.getenv("CLAUDE_MODEL_ID") or os.getenv("CLAUDE_INTENT_MODEL_ID")
CLAUDE_SYSTEM_PROMPT = (
    os.getenv("CLAUDE_SYSTEM_PROMPT")
    or (
        "You are Priya, a collections specialist calling from South India Finvest Bank. "
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
        logger.error(f"❌ Failed to configure Claude client: {claude_err}")
        claude_runtime_client = None
else:
    logger.app.warning("⚠️ CLAUDE_MODEL_ID not set; Claude voice handoff disabled")



class ClaudeChatSession:
    """Manages a conversation session with Claude."""
    
    def __init__(self, call_sid: str, context: Dict[str, Any]) -> None:
        self.call_sid = call_sid
        self.context = context
        self.messages: List[Dict[str, Any]] = []
        base_prompt = CLAUDE_SYSTEM_PROMPT or ""
        today_str = datetime.now(IST).strftime("%B %d, %Y")
        context_prompt = (
            "Today is {today}. Caller details: name={name}, loan_id={loan_id}, phone={phone}. "
            "The EMI is overdue; ask about repayment timing."
        ).format(
            today=today_str,
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
    """Manages multiple Claude chat sessions."""
    
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
            logger.error(f"❌ Unable to start Claude chat for {call_sid}: {err}")
            return None
    
    def get_session(self, call_sid: str) -> Optional[ClaudeChatSession]:
        """Get an existing chat session."""
        return self.sessions.get(call_sid)
    
    def end_session(self, call_sid: str) -> None:
        """End a chat session."""
        self.sessions.pop(call_sid, None)


# Global chat manager instance
claude_chat_manager = ClaudeChatManager()


async def claude_reply(chat: ClaudeChatSession, message: str) -> str:
    """Get a response from Claude for the given message."""
    try:
        # Run the synchronous send method in a thread
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, chat.send, message)
        return response
    except Exception as e:
        logger.error(f"Error getting Claude reply: {e}")
        return "I'm sorry, I'm having trouble understanding. Could you please rephrase that?"


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
        """Add a transcript segment and write to disk if enough silence has passed."""
        if not text.strip():
            return
            
        now = timestamp or time.time()
        self.pending_segments.append(text)
        self.last_speech_time = now
        
        # Check if we should flush based on silence gap
        self.flush(force=True, current_time=self.last_speech_time)

    
    def maybe_flush(self, current_time: Optional[float] = None) -> None:
        """Flush pending segments if silence gap has been exceeded."""
        if not self.pending_segments:
            return
            
        current_time = current_time or time.time()
        if self.last_speech_time and (current_time - self.last_speech_time) >= self.silence_gap:
            self.flush()
    
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
        """Write a single line to the transcript file."""
        try:
            self._ensure_header()
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(f"{text}\n")
        except Exception as e:
            logger.error(f"Error writing to transcript: {e}")

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

    chunk_size = 1280  # 80ms at 16kHz mono 16-bit PCM (increased from 20ms to 80ms for smoother streaming)
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

            # Adjust sleep time based on chunk size (80ms chunks)
            await asyncio.sleep(0.075)  # Slightly less than chunk duration to account for processing

        # Calculate buffer time based on audio duration (5% of total duration, min 100ms, max 1.5s)
        audio_duration = len(audio_bytes) / 32000.0  # 16kHz, 16-bit mono = 32000 bytes per second
        buffer_time = min(1.5, max(0.1, audio_duration * 0.05))
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
        logger.error(f"❌ Error streaming audio to websocket: {exc}")
        raise

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
            logger.error("❌ No AGENT_PHONE_NUMBER set in environment variables")
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
        logger.error(f"❌ play_transfer_to_agent failed: {e}")


# --- Language and Intent Detection ---

def _is_devanagari(text):
    """Check if text contains Devanagari characters."""
    devanagari_range = '\u0900-\u097F'
    return bool(re.search(f'[{devanagari_range}]', text))


def _is_tamil(text):
    """Check if text contains Tamil characters."""
    tamil_range = '\u0B80-\u0BFF'
    return bool(re.search(f'[{tamil_range}]', text))


def _is_telugu(text):
    """Check if text contains Telugu characters."""
    telugu_range = '\u0C00-\u0C7F'
    return bool(re.search(f'[{telugu_range}]', text))


def _is_kannada(text):
    """Check if text contains Kannada characters."""
    kannada_range = '\u0C80-\u0CFF'
    return bool(re.search(f'[{kannada_range}]', text))


def _is_malayalam(text):
    """Check if text contains Malayalam characters."""
    malayalam_range = '\u0D00-\u0D7F'
    return bool(re.search(f'[{malayalam_range}]', text))


def _is_gujarati(text):
    """Check if text contains Gujarati characters."""
    gujarati_range = '\u0A80-\u0AFF'
    return bool(re.search(f'[{gujarati_range}]', text))


def _is_marathi(text):
    """Check if text contains Marathi characters (same as Devanagari)."""
    return _is_devanagari(text)


def _is_bengali(text):
    """Check if text contains Bengali characters."""
    bengali_range = '\u0980-\u09FF'
    return bool(re.search(f'[{bengali_range}]', text))


def _is_punjabi(text):
    """Check if text contains Gurmukhi (Punjabi) characters."""
    gurmukhi_range = '\u0A00-\u0A7F'
    return bool(re.search(f'[{gurmukhi_range}]', text))


def _is_oriya(text):
    """Check if text contains Odia (Oriya) characters."""
    oriya_range = '\u0B00-\u0B7F'
    return bool(re.search(f'[{oriya_range}]', text))


def detect_language(text: str) -> str:
    """
    Detect the language of the given text based on script.
    Returns ISO 639-1 language code with region (e.g., 'en-IN', 'hi-IN').
    """
    if not text or not isinstance(text, str):
        return "en-IN"  # Default to English if no text
    
    # Check for different scripts
    if _is_devanagari(text):
        return "hi-IN"  # Hindi (also covers Marathi, Nepali, etc.)
    elif _is_tamil(text):
        return "ta-IN"  # Tamil
    elif _is_telugu(text):
        return "te-IN"  # Telugu
    elif _is_kannada(text):
        return "kn-IN"  # Kannada
    elif _is_malayalam(text):
        return "ml-IN"  # Malayalam
    elif _is_gujarati(text):
        return "gu-IN"  # Gujarati
    elif _is_bengali(text):
        return "bn-IN"  # Bengali
    elif _is_punjabi(text):
        return "pa-IN"  # Punjabi (Gurmukhi)
    elif _is_oriya(text):
        return "or-IN"  # Odia (Oriya)
    
    # Default to English if no script detected
    return "en-IN"

async def stream_audio_to_websocket_not_working(websocket, audio_bytes):
    # Legacy wrapper retained for backward compatibility; delegates to the new implementation.
    await stream_audio_to_websocket(websocket, audio_bytes)


async def detect_intent_with_claude(transcript: str, lang: str) -> str:
    """
    Detect intent for agent handoff using Claude via Bedrock.
    Returns 'affirmative'|'negative'|'unclear'.
    """
    try:
        # Prepare the prompt for Claude
        prompt = f"""
        Analyze the following customer statement and determine if they want to:
        1. Speak to a human agent (affirmative)
        2. Do not want to speak to an agent (negative)
        3. Are unclear in their response (unclear)
        
        Customer: "{transcript}"
        
        Respond with ONLY one of these exact words: affirmative, negative, or unclear
        """
        
        # Call Claude
        response = await bedrock_client.invoke_model(
            model_id=CLAUDE_MODEL_ID,
            body={
                "prompt": prompt,
                "max_tokens_to_sample": 50,
                "temperature": 0.3,
            }
        )
        
        # Parse the response
        intent = response.get("completion", "").strip().lower()
        
        # Validate the response
        if intent in ["affirmative", "negative", "unclear"]:
            return intent
        
        logger.warning(f"Unexpected intent response from Claude: {intent}")
        return "unclear"
        
    except Exception as e:
        logger.error(f"Error in detect_intent_with_claude: {e}")
        return "unclear"


def detect_intent_fur(text: str, lang: str) -> str:
    """
    A fallback intent detection function.
    This is a simple keyword-based approach that can be used if Claude is not available.
    """
    if not text:
        return "unclear"
    
    text_lower = text.lower()
    
    # Affirmative patterns
    affirmative_patterns = [
        r'\byes\b', r'\byeah\b', r'\bya\b', r'\byep\b', r'\bsure\b',
        r'\bok\b', r'\bokay\b', r'\bplease\b', r'\bgo ahead\b',
        r'\bconnect\b', r'\btransfer\b', r'\bspeak to\b', r'\btalk to\b',
        r'\bagent\b', r'\bhuman\b', r'\bperson\b', r'\brepresentative\b',
        r'\bmanager\b', r'\bsupervisor\b', r'\bhelp\b', r'\bassist\b'
    ]
    
    # Negative patterns
    negative_patterns = [
        r'\bno\b', r'\bnope\b', r'\bnah\b', r'\bnot now\b',
        r'\bnot interested\b', r'\bno thanks\b', r'\bno thank you\b',
        r'\bnot needed\b', r'\bnot necessary\b', r'\bdont need\b',
        r'\bdon\'t need\b', r'\bnot now\b', r'\bmaybe later\b',
        r'\bcall back\b', r'\bnot now\b', r'\bnot today\b'
    ]
    
    # Check for affirmative patterns
    for pattern in affirmative_patterns:
        if re.search(pattern, text_lower):
            return "affirmative"
    
    # Check for negative patterns
    for pattern in negative_patterns:
        if re.search(pattern, text_lower):
            return "negative"
    
    # If no clear intent, return unclear
    return "unclear"


def detect_intent(text: str) -> str:
    """
    Wrapper function to detect intent using the available methods.
    Defaults to the simple keyword-based approach.
    """
    # First try the simple keyword-based approach
    intent = detect_intent_fur(text, "")
    
    # If unclear, we could try Claude here if available
    if intent == "unclear" and os.getenv("USE_CLAUDE_FOR_INTENT", "").lower() == "true":
        # Note: In a real implementation, you would await this coroutine
        # For now, we'll just log and return the simple intent
        logger.debug("Claude intent detection is available but not used in this context")
    
    return intent


# Transcript logging configuration
base_transcript_dir = Path(os.getenv("VOICEBOT_RUNTIME_DIR") or Path(__file__).resolve().parent)
base_transcript_dir = base_transcript_dir.expanduser()
try:
    base_transcript_dir.mkdir(parents=True, exist_ok=True)
except Exception as transcript_dir_err:
    fallback_dir = Path(tempfile.gettempdir()) / "voicebot_transcripts"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    logger.app.warning(
        f"⚠️ Could not create transcript directory at {base_transcript_dir}: {transcript_dir_err}. "
        f"Falling back to {fallback_dir}"
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
            logger.error(f"❌ Failed to write transcript log: {exc}")


def parse_claude_response(raw: str) -> tuple[str, str]:
    """Parse Claude's response into text and status.
    
    Args:
        raw: Raw response from Claude
        
    Returns:
        Tuple of (response_text, status) where status is one of:
        - 'continue': Normal response, continue conversation
        - 'promise': Customer made a payment promise
        - 'escalate': Escalate to human agent
    """
    if not raw:
        return "", "continue"
    text = raw.strip()
    
    # Check for status in brackets at the end of the response
    bracket_pattern = r"\[(continue|promise|escalate)\]\s*$"
    match = re.search(bracket_pattern, text, re.IGNORECASE)
    if match:
        status = match.group(1).lower()
        response = text[:match.start()].strip()
        return response, status
    
    # Check for JSON response
    try:
        data = json.loads(text)
        resp = data.get("response")
        status = data.get("status", "continue")
        
        # Validate response types
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


# Audio streaming configuration
CHUNK_SIZE = 3200  # Increased chunk size for better performance
SAMPLE_RATE = 16000  # 16kHz sample rate
BYTES_PER_SAMPLE = 2  # 16-bit audio
CHANNELS = 1  # Mono audio
AUDIO_FORMAT = 'slin'  # Signed linear PCM

# Audio state management
class AudioState:
    """Manages audio state for a call."""
    def __init__(self, call_sid: str):
        self.call_sid = call_sid
        self.audio_buffer = bytearray()
        self.last_audio_time = time.time()
        self.silence_duration = 0
        self.is_speaking = False
        self.last_interaction_time = time.time()
        self.utterance_start_time = None
        self.utterance_buffer = []
        self.utterance_start_sample = 0
        self.sample_count = 0
        self.vad = webrtcvad.Vad(3)  # Aggressiveness mode 3 (highest)
        self.sample_rate = 16000
        self.frame_duration = 30  # ms
        self.samples_per_frame = int(self.sample_rate * self.frame_duration / 1000) * 2  # 16-bit samples

    def add_audio(self, audio_data: bytes) -> None:
        """Add audio data to the buffer."""
        self.audio_buffer.extend(audio_data)
        self.last_audio_time = time.time()
        
        # Process audio for voice activity detection
        self._process_audio_for_vad(audio_data)
    
    def _process_audio_for_vad(self, audio_data: bytes) -> None:
        """Process audio data for voice activity detection."""
        # Process in chunks of the right size for VAD
        frame_size = self.samples_per_frame
        for i in range(0, len(audio_data), frame_size):
            frame = audio_data[i:i + frame_size]
            if len(frame) < frame_size:
                continue  # Skip incomplete frames
                
            # Check if this frame contains speech
            is_speech = self.vad.is_speech(frame, self.sample_rate)
            self.sample_count += 1
            
            if is_speech:
                self.silence_duration = 0
                if not self.is_speaking:
                    self.is_speaking = True
                    self.utterance_start_time = time.time()
                    self.utterance_start_sample = self.sample_count
                    logger.debug(f"Speech started at sample {self.utterance_start_sample}")
            else:
                self.silence_duration += 1
                if self.is_speaking and self.silence_duration >= 3:  # 90ms of silence
                    self.is_speaking = False
                    utterance_end_sample = self.sample_count
                    utterance_duration = (utterance_end_sample - self.utterance_start_sample) * self.frame_duration / 1000.0
                    logger.debug(f"Speech ended at sample {utterance_end_sample}, duration: {utterance_duration:.2f}s")
    
    def get_audio_chunk(self, chunk_size: int = CHUNK_SIZE) -> Optional[bytes]:
        """Get a chunk of audio data from the buffer."""
        if len(self.audio_buffer) >= chunk_size:
            chunk = bytes(self.audio_buffer[:chunk_size])
            self.audio_buffer = self.audio_buffer[chunk_size:]
            return chunk
        return None
    
    def clear(self) -> None:
        """Clear the audio buffer."""
        self.audio_buffer = bytearray()
        self.silence_duration = 0
        self.is_speaking = False
        self.utterance_buffer = []
        self.utterance_start_sample = 0
        self.sample_count = 0

async def is_websocket_connected(websocket) -> bool:
    """Check if WebSocket is still connected and healthy."""
    try:
        if not websocket or not hasattr(websocket, 'client_state'):
            return False
        
        # Get WebSocket state safely
        state = getattr(websocket.client_state, 'name', 'UNKNOWN')
        return state in ['CONNECTED', 'CONNECTING']
    except Exception as e:
        logger.audio.error(f"Error checking WebSocket state: {str(e)}")
        return False

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

    chunk_size = 1280  # 80ms at 16kHz mono 16-bit PCM (increased from 20ms to 80ms for smoother streaming)
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

            # Adjust sleep time based on chunk size (80ms chunks)
            await asyncio.sleep(0.075)  # Slightly less than chunk duration to account for processing

        # Calculate buffer time based on audio duration (5% of total duration, min 100ms, max 1.5s)
        audio_duration = len(audio_bytes) / 32000.0  # 16kHz, 16-bit mono = 32000 bytes per second
        buffer_time = min(1.5, max(0.1, audio_duration * 0.05))
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
        logger.error(f"❌ Error streaming audio to websocket: {exc}")
        raise


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
    
    # CONVERSATION FLOW FIX: Give user adequate time to process the question and respond
    logger.websocket.info("⏳ Waiting for user to process agent connect question...")
    await asyncio.sleep(2.0)  # Wait 2 seconds for user to process the question
    logger.websocket.info("🎯 Now actively listening for user response to agent question")

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
        f"Hello {name}. I am a voice agent calling from South India Finvest bank. "
        f"Am I speaking with {name} with the loan ID ending in {loan_suffix}?"
    )
    logger.tts.info(f"🔁 Confirmation prompt: {prompt}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt, "en-IN")
    await stream_audio_to_websocket(websocket, audio_bytes)

async def play_connecting_prompt(websocket, language: str = "en-IN") -> None:
    prompt = "Thank you for confirming your identity. Please wait a second."
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
    """A fallback intent detection function with strict validation to prevent false positives."""
    return detect_intent_strict(text)


def detect_intent_strict(text):
    """Enhanced intent detection with stricter validation to prevent false agent transfers."""
    if not text or len(text.strip()) < 2:
        logger.websocket.info(f"🚫 Intent detection: text too short '{text}'")
        return "unclear"
    
    text = text.lower().strip()
    
    # Log what we're analyzing
    logger.websocket.info(f"🔍 Analyzing intent for: '{text}'")
    
    # Explicit agent transfer requests
    if any(word in text for word in ["agent", "live agent", "speak to someone", "transfer", "help desk", "human"]):
        logger.websocket.info(f"✅ Detected explicit agent request")
        return "agent_transfer"
    
    # Strict affirmative detection - require clear positive responses
    affirmative_keywords = ["yes", "yeah", "sure", "okay", "ok", "haan", "ஆம்", "अवुनु", "हाँ", "ಹೌದು", "हॉं"]
    if any(word == text or f" {word} " in f" {text} " or text.startswith(f"{word} ") or text.endswith(f" {word}") for word in affirmative_keywords):
        logger.websocket.info(f"✅ Detected clear affirmative response")
        return "affirmative"
    
    # Strict negative detection
    negative_keywords = ["no", "not now", "later", "nah", "nahi", "nope", "இல்லை", "काधू", "ನಹಿ", "नहीं"]
    if any(word == text or f" {word} " in f" {text} " or text.startswith(f"{word} ") or text.endswith(f" {word}") for word in negative_keywords):
        logger.websocket.info(f"✅ Detected clear negative response")
        return "negative"
    
    # Confusion indicators
    if any(word in text for word in ["what", "who", "why", "repeat", "pardon", "sorry", "didn't hear"]):
        logger.websocket.info(f"✅ Detected confusion/clarification request")
        return "confused"
    
    # Default to unclear for ambiguous inputs
    logger.websocket.info(f"⚠️ Unclear intent - defaulting to 'unclear'")
    return "unclear"


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

# =============================================================================
# AUTHENTICATION ROUTES - TEMPORARILY DISABLED FOR TESTING
# =============================================================================
# ALL AUTHENTICATION ROUTES DISABLED FOR TESTING - UNCOMMENT WHEN AUTH IS NEEDED
# The authentication section has been temporarily removed to allow direct dashboard access

# Pydantic models for request/response (keeping these for when auth is re-enabled)
class SignupRequest(BaseModel):
    email: str
    password: str
    first_name: str = None
    last_name: str = None

class LoginRequest(BaseModel):
    email: str
    password: str

class ConfirmSignupRequest(BaseModel):
    email: str
    confirmation_code: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

# Authentication routes temporarily removed for testing - all auth endpoints disabled

# =============================================================================
# END AUTHENTICATION ROUTES (REMOVED FOR TESTING)
# =============================================================================

# --- HTML Endpoints ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """
    Serves the dashboard with authentication enabled.
    """
    # Get Redis session
    session = get_session(request)
    
    # Debug logging
    session_data = dict(session.data)
    user_data = session.get("user")
    is_auth = user_data is not None
    
    logger.info(f"Dashboard access attempt - Session data: {session_data}")
    logger.info(f"Dashboard access attempt - User data: {user_data}")
    logger.info(f"Dashboard access attempt - Is authenticated: {is_auth}")
    
    # Check if user is authenticated
    if not is_auth:
        logger.info("User not authenticated, redirecting to Cognito login")
        # Redirect to Cognito hosted UI login
        login_url = cognito_auth.get_login_url()
        return RedirectResponse(url=login_url, status_code=302)
    
    logger.info("User authenticated, serving dashboard")
    # User is authenticated, redirect to the static dashboard
    return RedirectResponse(url="/static/index.html", status_code=302)

# DEBUG SESSION ENDPOINT
@app.get("/debug/session")
async def debug_session(request: Request):
    """Debug endpoint to check session state"""
    session = get_session(request)
    session_data = dict(session.data)
    user_data = session.get("user")
    is_auth = user_data is not None
    
    return {
        "session_exists": bool(session),
        "session_data": session_data,
        "user_data": user_data,
        "is_authenticated": is_auth,
        "session_keys": list(session.data.keys()) if session else []
    }

# =============================================================================
# AUTHENTICATION ROUTES
# =============================================================================

@app.get("/login")
async def login():
    """Redirect to Cognito Hosted UI login"""
    login_url = cognito_auth.get_login_url()
    return RedirectResponse(url=login_url, status_code=302)

@app.get("/logout")
async def logout(request: Request):
    """Logout user and clear session from Redis"""
    session = get_session(request)
    
    # Log the logout activity
    user_email = session.get("user", {}).get("email", "unknown")
    logger.info(f"User logout initiated: {user_email}")
    
    # Clear session data
    session.clear()
    
    # Also delete from Redis directly to ensure cleanup
    session_id = request.cookies.get("session_id")
    if session_id and hasattr(session, 'redis_client') and session.redis_client:
        try:
            session.redis_client.delete(f"session:{session_id}")
            logger.info(f"Session {session_id} deleted from Redis")
        except Exception as e:
            logger.error(f"Error deleting session from Redis: {e}")
    
    # Get Cognito logout URL
    logout_url = cognito_auth.get_logout_url()
    
    # Create response that redirects to Cognito logout and clears cookie
    response = RedirectResponse(url=logout_url, status_code=302)
    
    # Clear the session cookie
    response.delete_cookie(
        key="session_id",
        domain=None,
        secure=True,
        httponly=True,
        samesite="none"
    )
    
    return response

@app.post("/api/logout")
async def api_logout(request: Request):
    """API endpoint for immediate logout (AJAX)"""
    session = get_session(request)
    
    # Log the logout activity
    user_email = session.get("user", {}).get("email", "unknown")
    logger.info(f"API logout initiated: {user_email}")
    
    # Clear session data
    session.clear()
    
    # Also delete from Redis directly to ensure cleanup
    session_id = request.cookies.get("session_id")
    if session_id and hasattr(session, 'redis_client') and session.redis_client:
        try:
            session.redis_client.delete(f"session:{session_id}")
            logger.info(f"Session {session_id} deleted from Redis via API")
        except Exception as e:
            logger.error(f"Error deleting session from Redis via API: {e}")
    
    # Return JSON response for AJAX
    response = JSONResponse({
        "success": True,
        "message": "Logged out successfully",
        "logout_url": cognito_auth.get_logout_url()
    })
    
    # Clear the session cookie
    response.delete_cookie(
        key="session_id",
        domain=None,
        secure=True,
        httponly=True,
        samesite="none"
    )
    
    return response

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = Query(...), state: str = Query(default="default")):
    """Handle Cognito authentication callback"""
    try:
        # Exchange authorization code for tokens
        token_data = await cognito_auth.exchange_code_for_tokens(code)
        
        # Get user info from access token
        user_info = await cognito_auth.get_user_info_from_access_token(token_data["access_token"])
        
        # Store user info in Redis session
        session = get_session(request)
        session["user"] = user_info
        session["tokens"] = token_data
        
        logger.info(f"User authenticated successfully: {user_info.get('email', 'unknown')}")
        
        # Redirect to dashboard
        return RedirectResponse(url="/", status_code=302)
        
    except Exception as e:
        logger.error(f"Authentication callback error: {e}")
        raise HTTPException(status_code=400, detail=f"Authentication failed: {str(e)}")

@app.get("/auth/user")
async def get_auth_user(request: Request):
    """Get current authenticated user"""
    session = get_session(request)
    user_data = session.get("user")
    
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return {"user": user_data, "authenticated": True}

@app.get("/auth/session-status")
async def get_session_status(request: Request):
    """Check if session is still valid and get remaining time"""
    session = get_session(request)
    user_data = session.get("user")
    
    if not user_data:
        return {
            "authenticated": False,
            "expired": True,
            "remaining_time": 0
        }
    
    # Get session expiration info from Redis
    session_id = request.cookies.get("session_id")
    remaining_time = 0
    
    if session_id and hasattr(session, 'redis_client') and session.redis_client:
        try:
            ttl = session.redis_client.ttl(f"session:{session_id}")
            remaining_time = max(0, ttl) if ttl > 0 else 0
        except Exception as e:
            logger.error(f"Error checking session TTL: {e}")
    
    return {
        "authenticated": True,
        "expired": False,
        "remaining_time": remaining_time,
        "remaining_minutes": round(remaining_time / 60, 1),
        "user": {
            "email": user_data.get("email"),
            "name": user_data.get("name", user_data.get("email", "User"))
        }
    }

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
            logger.error(f"🔗 Failed to parse temp_call_id from CustomField: {e}")
    
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

# --- WebSocket URL Endpoint ---
@app.get("/websocket-url")
async def get_websocket_url():
    """
    Returns the WebSocket URL configuration for Exotel Flow Stream/Voicebot applet.
    This provides the correct WebSocket endpoint that Exotel should connect to.
    """
    # Get the base URL (ngrok URL)
    base_url = os.getenv('BASE_URL', 'http://localhost:8000')
    # Convert http to ws
    ws_base_url = base_url.replace('http://', 'ws://').replace('https://', 'wss://')
    
    # The main WebSocket endpoint for voice templates
    websocket_endpoint = f"{ws_base_url}/ws/voicebot/{{session_id}}"
    
    return {
        "websocket_url": websocket_endpoint,
        "endpoint_pattern": "/ws/voicebot/{session_id}",
        "example_url": f"{ws_base_url}/ws/voicebot/example_session_123",
        "protocol": "wss" if base_url.startswith('https') else "ws",
        "note": "Replace {session_id} with actual CallSid or unique session identifier",
        "exotel_flow_config": {
            "applet_type": "Stream/Voicebot", 
            "websocket_url": websocket_endpoint,
            "description": "Add this URL to your Exotel Flow after the Passthru applet"
        }
    }

# --- Exotel Passthru Handler ---
@app.get("/passthru-handler", response_class=PlainTextResponse)
async def handle_passthru(request: Request):
    """
    Handles Exotel's Passthru applet request.
    This is a critical, lightweight endpoint that must respond quickly.
    It receives call data, caches it, and updates the DB.
    """
    logger.websocket.info("✅ /passthru-handler hit")
    
    params = request.query_params
    call_sid = params.get("CallSid")
    custom_field = params.get("CustomField")

    if not call_sid:
        logger.error("❌ Passthru handler called without a CallSid.")
        # Still return OK to Exotel to not break their flow, but log the error.
        return "OK"

    logger.websocket.info(f"📞 Passthru: CallSid received: {call_sid}")
    logger.websocket.info(f"📦 Passthru: CustomField received: {custom_field}")

    # Parse the pipe-separated CustomField
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
            logger.error(f"❌ Passthru: Failed to parse CustomField: {e}")
            # Log error but continue, as we might have the CallSid
    
    # Get the temporary ID to link sessions
    temp_call_id = customer_data.get("temp_call_id")
    logger.websocket.info(f"ℹ️ Passthru: temp_call_id from CustomField: {temp_call_id}")

    # --- Redis Caching ---
    # We now have the official CallSid, let's update/create the Redis session
    if temp_call_id:
        logger.websocket.info(f"🔄 Passthru: Linking session from temp_call_id: {temp_call_id} to new CallSid: {call_sid}")
        redis_manager.link_session_to_sid(temp_call_id, call_sid)
    else:
        logger.websocket.info(f"📦 Passthru: Creating new Redis session for CallSid: {call_sid}")
        redis_manager.create_call_session(call_sid, customer_data)

    # --- Database Update ---
    try:
        logger.database.info(f"✍️ Passthru: Updating database for CallSid: {call_sid}")
        session = db_manager.get_session()
        try:
            update_call_status(
                session=session,
                call_sid=call_sid,
                status=CallStatus.IN_PROGRESS,
                message=f"Call flow started - temp_call_id: {temp_call_id}"
            )
            session.commit()
            logger.database.info(f"✅ Passthru: Database updated successfully for CallSid: {call_sid}")
        finally:
            session.close()
    except Exception as e:
        logger.error(f"❌ Passthru: Database update failed for CallSid {call_sid}: {e}")

    # IMPORTANT: Always return "OK" for Exotel to proceed with the call flow.
    logger.websocket.info("✅ Passthru: Responding 'OK' to Exotel.")
    return "OK"

# --- Test Passthru Handler ---
@app.get("/test-passthru")
async def test_passthru_handler():
    """Test the passthru handler with sample data"""
    return {
        "status": "success",
        "message": "Passthru handler is working",
        "passthru_url": "https://4ee3feb8d5e0.ngrok-free.app/passthru-handler",
        "instructions": "Add this URL to your Exotel Flow Passthru applet"
    }
async def play_audio_message(websocket, text: str, language_code: str = "en-IN"):
    """
    Convert text to speech and send it to Exotel passthru stream.
    """
    try:
        logger.websocket.info(f"🗣️ Playing audio message: {text}")

        # Generate speech (replace with your actual TTS call)
        audio_data = await synthesize_speech(text, language_code)

        if not audio_data:
            logger.error("❌ TTS synthesis failed, no audio generated")
            return

        # Send audio chunks to Exotel via websocket
        await websocket.send_bytes(audio_data)
        logger.websocket.info("✅ Audio message sent to Exotel stream")

    except Exception as e:
        logger.error(f"❌ Failed to play audio message: {e}")

#Newly added...
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
        info = dict(info)
        if not info.get('name'):
            info['name'] = 'Customer'
        phone_value = info.get('phone') or info.get('phone_number')
        if phone_value:
            info.setdefault('phone', phone_value)
            info.setdefault('phone_number', phone_value)
        if not info.get('loan_id'):
            info['loan_id'] = 'unknown'
        if not info.get('amount'):
            info['amount'] = info.get('due_amount') or 'the outstanding amount'
        if not info.get('due_amount'):
            info['due_amount'] = info.get('amount')
        if not info.get('due_date'):
            info['due_date'] = 'the due date'
        if not info.get('lang'):
            info['lang'] = info.get('language_code', 'en-IN')
        return info

    def format_amount(value: Optional[str]) -> str:
        if value is None or value == '':
            return 'the outstanding amount'

        text_value = str(value).strip()
        cleaned = (text_value.replace('₹', '').replace(',', '').replace(' ', ''))

        try:
            num = float(cleaned)
        except ValueError:
            return text_value

        if num.is_integer():
            return f"₹{int(num):,}"
        return f"₹{num:,.2f}"

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
        nonlocal call_sid, customer_info, conversation_stage, last_transcription_time, claude_chat, current_language, phone

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
        
        # Try to get customer data from Redis using temp_call_id or call_sid
        session_data = None
        if temp_call_id:
            logger.websocket.info(f"🔍 Looking up customer data by temp_call_id: {temp_call_id}")
            session_data = redis_manager.get_call_session(temp_call_id)
            if session_data:
                info = session_data.get('customer_data') or session_data
                logger.websocket.info(f"✅ Found customer data by temp_call_id")
        
        if not info and call_sid:
            logger.websocket.info(f"🔍 Looking up customer data by call_sid: {call_sid}")
            session_data = redis_manager.get_call_session(call_sid)
            if session_data:
                info = session_data.get('customer_data') or session_data
                logger.websocket.info(f"✅ Found customer data by call_sid")
        
        # If still no data, try to get from custom fields or phone number
        if not info:
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

        if info and not phone:
            phone = info.get('phone') or info.get('phone_number')

        if not info and phone:
            info = await resolve_customer_from_db(phone)

        # Ensure we have valid customer data with required fields
        info = ensure_customer_info(info)
        if not info:
            logger.websocket.error("❌ Customer data missing; attempting to use fallback data")
            
            # Create minimal customer info with default values
            info = {
                'name': 'Customer',
                'phone': phone or 'Unknown',
                'phone_number': phone or 'Unknown',
                'loan_id': 'N/A',
                'amount': '0',
                'due_date': 'N/A',
                'state': '',
                'lang': 'en-IN',
                'language_code': 'en-IN'
            }
            
            logger.websocket.warning(f"⚠️ Using fallback customer data: {info}")
            
            # Store this minimal data in Redis for future reference
            if call_sid:
                try:
                    redis_manager.create_call_session(
                        call_sid=call_sid,
                        customer_data=info,
                        websocket_id=str(websocket)
                    )
                    logger.websocket.info(f"💾 Saved fallback customer data to Redis for call_sid: {call_sid}")
                except Exception as e:
                    logger.websocket.error(f"❌ Failed to save fallback data to Redis: {e}")
            
            # Continue with the minimal data instead of failing

        customer_info = info

        phone_value = phone or customer_info.get('phone') or customer_info.get('phone_number')
        customer_info.setdefault('name', 'Customer')
        customer_info['phone'] = phone_value or 'Unknown'
        customer_info.setdefault('phone_number', customer_info['phone'])
        customer_info.setdefault('loan_id', 'N/A')
        customer_info.setdefault('amount', '0')
        customer_info.setdefault('due_amount', customer_info.get('amount'))
        customer_info.setdefault('due_date', 'N/A')
        customer_info.setdefault('state', '')
        customer_info.setdefault('lang', customer_info.get('language_code', 'en-IN'))

        if customer_info.get('amount') is not None:
            customer_info['amount'] = str(customer_info['amount'])
        if customer_info.get('due_amount') is not None:
            customer_info['due_amount'] = str(customer_info['due_amount'])
        if customer_info.get('due_date') is not None:
            customer_info['due_date'] = str(customer_info['due_date'])

        current_language = customer_info['lang']
        
        # Initialize transcript logger with customer info
        try:
            transcript_logger.update_customer(
                customer_info['name'],
                customer_info['phone']
            )
        except Exception as e:
            logger.websocket.error(f"❌ Failed to update transcript logger: {e}")
            
        logger.websocket.info(f"👤 Customer info initialized: {customer_info}")

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
                    "The caller is now on the line. Introduce yourself as Priya from South India Finvest Bank, "
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
        logger.error(f"WebSocket error: {err}")
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
            logger.error(f"Error closing WebSocket: {close_err}")

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
    try:
        while True:
            # This loop will keep the connection alive.
            # We can add logic here later to handle messages from the dashboard.
            await websocket.receive_text()
    except WebSocketDisconnect:
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
async def upload_customers(file: UploadFile = File(...)):  # REMOVED AUTH FOR TESTING: current_user: dict = Depends(get_current_user_optional)
    """
    Accepts a CSV or Excel file, processes it, and stores customer data in the database.
    Authentication optional for development.
    """
    user_email = 'testing-mode'  # REMOVED AUTH FOR TESTING: current_user.get('email', 'anonymous') if current_user else 'anonymous'
    print(f"📁 [CHECKPOINT] /api/upload-customers endpoint hit by user: {user_email}")
    print(f"📁 [CHECKPOINT] File name: {file.filename}")
    print(f"📁 [CHECKPOINT] File content type: {file.content_type}")
    
    try:
        file_data = await file.read()
        print(f"📁 [CHECKPOINT] File size: {len(file_data)} bytes")
        
        result = await call_service.upload_and_process_customers(file_data, file.filename)
        print(f"📁 [CHECKPOINT] File processing result: {result}")
        
        # Log the action with user information
        logger.info(f"User {user_email} uploaded customer file: {file.filename}")
        
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in upload_customers endpoint: {e}")
        import traceback
        traceback.print_exc()
        logger.error(f"Upload customers error for user {user_email}: {str(e)}")
        return {"success": False, "error": str(e)}

@app.post("/api/trigger-single-call")
async def trigger_single_call(customer_id: str = Body(..., embed=True)):  # REMOVED AUTH FOR TESTING: current_user: dict = Depends(get_current_user)
    """
    Triggers a single call to a customer by their ID.
    """
    print(f"🚀 [CHECKPOINT] /api/trigger-single-call endpoint hit by user: testing-mode")
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
            
        # Log the action with user information
        logger.info(f"User testing-mode triggered single call for customer: {customer_id}")
        
        return result
    except Exception as e:
        error_msg = f"Trigger single call error for user testing-mode: {str(e)}"
        print(f"❌ [CHECKPOINT] {error_msg}")
        logger.error(error_msg, exc_info=True)
        return {"success": False, "error": str(e)}

@app.post("/api/trigger-bulk-calls")
async def trigger_bulk_calls(customer_ids: list[str] = Body(..., embed=True)):  # REMOVED AUTH FOR TESTING: current_user: dict = Depends(get_current_user)
    """
    Triggers calls to a list of customers by their IDs.
    Requires authentication.
    """
    print(f"🚀 [CHECKPOINT] /api/trigger-bulk-calls endpoint hit by user: testing-mode")
    print(f"🚀 [CHECKPOINT] Customer IDs: {customer_ids}")
    print(f"🚀 [CHECKPOINT] Number of customers: {len(customer_ids)}")
    
    try:
        result = await call_service.trigger_bulk_calls(customer_ids)
        print(f"🚀 [CHECKPOINT] Bulk call service result: {result}")
        
        # Log the action with user information
        logger.info(f"User testing-mode triggered bulk calls for {len(customer_ids)} customers")
        
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in trigger_bulk_calls endpoint: {e}")
        logger.error(f"Trigger bulk calls error for user testing-mode: {str(e)}")
        return {"success": False, "error": str(e)}

def safe_float_conversion(value):
    """Safely convert a value to float, handling edge cases"""
    if not value or value in ['None', '', 'null', 'undefined', 'N/A']:
        return 0
    
    # If it's already a number
    if isinstance(value, (int, float)):
        return float(value)
    
    # Convert to string and clean
    str_value = str(value).strip()
    
    # Remove currency symbols and common formatting
    str_value = str_value.replace('₹', '').replace(',', '').replace(' ', '')
    
    # Handle date-like formats or other non-numeric strings
    if '/' in str_value or '-' in str_value or ':' in str_value:
        return 0
    
    try:
        return float(str_value)
    except (ValueError, TypeError):
        return 0

@app.get("/api/customers")
async def get_all_customers():  # REMOVED AUTH FOR TESTING: current_user: dict = Depends(get_current_user_optional)
    """
    Retrieves all customers from the database with loans relationship.
    Authentication optional for development.
    """
    user_email = 'testing-mode'  # REMOVED AUTH FOR TESTING
    print(f"👥 [CHECKPOINT] /api/customers endpoint hit by user: {user_email}")
    
    session = db_manager.get_session()
    try:
        # Import joinedload for relationship loading
        from sqlalchemy.orm import joinedload, selectinload
        
        # Load customers with optimized relationship loading
        # Use selectinload for better performance with many customers
        customers = session.query(Customer).options(
            selectinload(Customer.loans),
            selectinload(Customer.call_sessions)
        ).order_by(Customer.created_at.desc()).limit(1000).all()  # Limit for performance
        
        print(f"👥 [CHECKPOINT] Found {len(customers)} customers in database")
        
        # Log the action with user information
        logger.info(f"User {user_email} accessed customer list ({len(customers)} customers)")
        
        result = []
        for c in customers:
            # Prepare loans data with better error handling
            loans_data = []
            if hasattr(c, 'loans') and c.loans:
                loans_data = []
                for loan in c.loans:
                    try:
                        loan_dict = {
                            "id": str(loan.id),
                            "loan_id": loan.loan_id,
                            "outstanding_amount": float(loan.outstanding_amount) if loan.outstanding_amount else 0,
                            "due_amount": float(loan.due_amount) if loan.due_amount else 0,
                            "next_due_date": loan.next_due_date.isoformat() if loan.next_due_date else None,
                            "last_paid_date": loan.last_paid_date.isoformat() if loan.last_paid_date else None,
                            "last_paid_amount": float(loan.last_paid_amount) if loan.last_paid_amount else 0,
                            "status": loan.status or "active",
                            "cluster": loan.cluster or "Unknown",
                            "branch": loan.branch or "Unknown",
                            "branch_contact_number": loan.branch_contact_number or "N/A",
                            "employee_name": loan.employee_name or "Unknown",
                            "employee_id": loan.employee_id or "Unknown",
                            "employee_contact_number": loan.employee_contact_number or "N/A"
                        }
                        loans_data.append(loan_dict)
                    except Exception as loan_error:
                        print(f"⚠️ Error processing loan for customer {c.id}: {loan_error}")
                        continue
            
            # Get call status (most recent call)
            call_status = 'ready'
            if hasattr(c, 'call_sessions') and c.call_sessions:
                recent_call = max(c.call_sessions, key=lambda x: x.initiated_at)
                call_status = recent_call.status or 'ready'
            
            try:
                customer_data = {
                    "id": str(c.id),
                    "name": c.name or "Unknown",  # Uses backward compatibility property
                    "phone_number": c.phone_number or "Unknown",  # Uses backward compatibility property
                    "language_code": getattr(c, 'language_code', 'hi-IN'),
                    "loan_id": c.loan_id or (loans_data[0].get("loan_id") if loans_data else "Unknown"),
                    "amount": c.amount or (f"₹{loans_data[0].get('outstanding_amount', 0):,.0f}" if loans_data else "₹0"),
                    "due_date": c.due_date or (loans_data[0].get("next_due_date") if loans_data else "N/A"),
                    "state": c.state or "Unknown",
                    "created_at": c.created_at.isoformat() if hasattr(c, 'created_at') and c.created_at else datetime.now().isoformat(),
                    "call_status": call_status,
                    "upload_date": c.first_uploaded_at.isoformat() if hasattr(c, 'first_uploaded_at') and c.first_uploaded_at else c.created_at.isoformat(),
                    "loans": loans_data,  # New loans relationship data
                    
                    # Additional fields the frontend expects
                    "cluster": loans_data[0].get("cluster", "Unknown") if loans_data else getattr(c, 'cluster', 'Unknown'),
                    "branch": loans_data[0].get("branch", "Unknown") if loans_data else getattr(c, 'branch', 'Unknown'), 
                    "branch_contact": loans_data[0].get("branch_contact_number", "N/A") if loans_data else getattr(c, 'branch_contact', 'N/A'),
                    "employee_name": loans_data[0].get("employee_name", "Unknown") if loans_data else getattr(c, 'employee_name', 'Unknown'),
                    "employee_id": loans_data[0].get("employee_id", "Unknown") if loans_data else getattr(c, 'employee_id', 'Unknown'),
                    "employee_contact": loans_data[0].get("employee_contact_number", "N/A") if loans_data else getattr(c, 'employee_contact', 'N/A'),
                    "last_paid_date": loans_data[0].get("last_paid_date") if loans_data else getattr(c, 'last_paid_date', None),
                    "last_paid_amount": loans_data[0].get("last_paid_amount", 0) if loans_data else getattr(c, 'last_paid_amount', 0),
                    "due_amount": loans_data[0].get("due_amount", 0) if loans_data else safe_float_conversion(c.amount)
                }
                result.append(customer_data)
            except Exception as customer_error:
                print(f"⚠️ Error processing customer {c.id}: {customer_error}")
                continue
        
        print(f"👥 [CHECKPOINT] Returning customer list successfully")
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in get_all_customers endpoint: {e}")
        import traceback
        traceback.print_exc()
        return []
    finally:
        session.close()

@app.get("/api/uploaded-files")
async def get_uploaded_files():  # REMOVED AUTH FOR TESTING: current_user: dict = Depends(get_current_user_optional)
    """
    Get list of uploaded files/batches
    """
    session = db_manager.get_session()
    try:
        from database.schemas import FileUpload
        uploads = session.query(FileUpload).order_by(FileUpload.uploaded_at.desc()).all()
        
        result = []
        for upload in uploads:
            result.append({
                "id": str(upload.id),
                "filename": upload.filename,
                "uploaded_at": upload.uploaded_at.isoformat(),
                "uploaded_by": upload.uploaded_by,
                "total_records": upload.total_records,
                "processed_records": upload.processed_records,
                "success_records": upload.success_records,
                "failed_records": upload.failed_records,
                "status": upload.status
            })
        
        return result
    except Exception as e:
        print(f"❌ Error getting uploaded files: {e}")
        return []
    finally:
        session.close()

@app.get("/api/uploaded-files/ids")
async def get_uploaded_file_ids():  # REMOVED AUTH FOR TESTING: current_user: dict = Depends(get_current_user_optional)
    """
    Get list of uploaded file IDs for batch selection
    """
    session = db_manager.get_session()
    try:
        from database.schemas import FileUpload
        uploads = session.query(FileUpload).order_by(FileUpload.uploaded_at.desc()).all()
        
        result = []
        for upload in uploads:
            result.append({
                "id": str(upload.id),
                "filename": upload.filename,
                "uploaded_at": upload.uploaded_at.isoformat(),
                "total_records": upload.total_records,
                "status": upload.status
            })
        
        return result
    except Exception as e:
        print(f"❌ Error getting uploaded file IDs: {e}")
        return []
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




@app.get("/api/uploaded-files/{batch_id}/details")
async def get_batch_details(batch_id: str):  # REMOVED AUTH FOR TESTING: current_user: dict = Depends(get_current_user_optional)
    """
    Get detailed information about a specific batch
    """
    session = db_manager.get_session()
    try:
        from database.schemas import FileUpload, UploadRow
        
        upload = session.query(FileUpload).filter(FileUpload.id == batch_id).first()
        if not upload:
            raise HTTPException(status_code=404, detail="Batch not found")
        
        # Get upload rows for this batch
        rows = session.query(UploadRow).filter(UploadRow.file_upload_id == batch_id).all()
        
        return {
            "id": str(upload.id),
            "filename": upload.filename,
            "uploaded_at": upload.uploaded_at.isoformat(),
            "uploaded_by": upload.uploaded_by,
            "total_records": upload.total_records,
            "processed_records": upload.processed_records,
            "success_records": upload.success_records,
            "failed_records": upload.failed_records,
            "status": upload.status,
            "processing_errors": upload.processing_errors,
            "rows": [
                {
                    "id": str(row.id),
                    "line_number": row.line_number,
                    "phone_normalized": row.phone_normalized,
                    "status": row.status,
                    "error": row.error,
                    "match_customer_id": str(row.match_customer_id) if row.match_customer_id else None,
                    "match_loan_id": str(row.match_loan_id) if row.match_loan_id else None
                } for row in rows
            ]
        }
    except Exception as e:
        print(f"❌ Error getting batch details: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.post("/exotel-webhook")
async def exotel_webhook(request: Request):
    """
    Handles Exotel status webhooks for call status updates.
    """
    try:
        # Get the form data from Exotel webhook
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus") or form_data.get("Status")  # Try both fields
        call_duration = form_data.get("CallDuration") 
        
        print(f"📞 [WEBHOOK] Received Exotel webhook:")
        print(f"   CallSid: {call_sid}")
        print(f"   CallStatus: {call_status}")
        print(f"   CallDuration: {call_duration}")
        print(f"   All form data: {dict(form_data)}")
        
        if call_sid and call_status:
            # Update call status in database
            session = db_manager.get_session()
            try:
                call_session = get_call_session_by_sid(session, call_sid)
                if call_session:
                    # Map Exotel status to internal status
                    status_mapping = {
                        'ringing': 'ringing',
                        'in-progress': 'in_progress', 
                        'completed': 'completed',
                        'busy': 'busy',
                        'no-answer': 'no_answer',
                        'failed': 'failed',
                        'canceled': 'failed'
                    }
                    
                    # Safely handle call_status - convert to lowercase only if not None
                    status_key = call_status.lower() if call_status else 'unknown'
                    internal_status = status_mapping.get(status_key, call_status or 'unknown')
                    
                    # Update call session
                    update_call_status(
                        session, 
                        call_sid, 
                        internal_status,
                        f"Exotel webhook: {call_status}",
                        extra_data={'webhook_data': dict(form_data)}
                    )
                    
                    print(f"✅ [WEBHOOK] Updated call {call_sid} status to: {internal_status}")
                else:
                    print(f"⚠️ [WEBHOOK] Call session not found for SID: {call_sid}")
                    
            finally:
                session.close()
        else:
            print(f"⚠️ [WEBHOOK] Missing required data - CallSid: {call_sid}, CallStatus: {call_status}")
        
        return {"status": "success", "message": "Webhook processed"}
        
    except Exception as e:
        print(f"❌ [WEBHOOK] Error processing webhook: {e}")
        return {"status": "error", "message": str(e)}

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
    logger.info("Starting server directly from main.py")
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
