import os
import asyncio
import base64
import json
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager, suppress
from datetime import datetime, date
from urllib.parse import quote
from pathlib import Path
import tempfile
import pytz

import httpx
import pandas as pd
import requests
import uvicorn
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
# Load environment variables at the very beginning
load_dotenv()
EXOTEL_SID = os.getenv("EXOTEL_SID")
EXOTEL_TOKEN = os.getenv("EXOTEL_TOKEN")
EXOTEL_FLOW_APP_ID = os.getenv("EXOTEL_FLOW_APP_ID")
EXOTEL_VIRTUAL_NUMBER = os.getenv("EXOTEL_VIRTUAL_NUMBER")
EXOTEL_TIME_LIMIT = os.getenv("EXOTEL_TIME_LIMIT", "3600")
EXOTEL_RING_TIMEOUT = os.getenv("EXOTEL_RING_TIMEOUT", "15")
# IST timezone setup
IST = pytz.timezone('Asia/Kolkata')

def get_ist_timestamp():
    """Get current timestamp in IST"""
    return datetime.now(IST)

def format_ist_datetime(dt):
    """Format datetime object to IST string"""
    if dt is None:
        return None
    
    # Handle date objects (convert to datetime first)
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time())
    
    # Handle timezone-naive datetime objects
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    
    return dt.astimezone(IST).isoformat()

# Import project-specific modules
from database.schemas import (CallStatus, Customer,
                              db_manager, init_database, update_call_status, get_call_session_by_sid,
                              update_customer_call_status_by_phone, update_customer_call_status)
from sqlalchemy.orm import joinedload
from services.call_management import call_service
from utils import bedrock_client
from utils.agent_transfer import trigger_exotel_agent_transfer, trigger_ai_agent_mode
from utils.enhanced_ai_agent import ai_agent_manager
from utils.websocket_ai_agent_handler import handle_ai_agent_conversation, cleanup_ai_agent_session
from utils.logger import setup_application_logging, logger
from utils.production_asr import ProductionSarvamHandler
from utils.redis_session import (init_redis, redis_manager,
                                 generate_websocket_session_id)
from enhanced_main_integration import enhanced_audio_processing, get_enhanced_greeting

import httpx
import asyncio
from datetime import datetime
import httpx
import asyncio

from fastapi import FastAPI, WebSocket, Request
import httpx, sqlite3

# Initialize FastAPI
app = FastAPI()
active_connections = []

# --- Dashboard WebSocket Management ---
dashboard_clients: Dict[str, Dict[str, Any]] = {}
dashboard_clients_lock = asyncio.Lock()


async def register_dashboard_client(session_id: str, websocket: WebSocket) -> asyncio.Queue:
    """Register a dashboard client and provide a queue for outbound events."""
    event_queue: asyncio.Queue = asyncio.Queue()
    async with dashboard_clients_lock:
        dashboard_clients[session_id] = {"websocket": websocket, "queue": event_queue}
    return event_queue


async def unregister_dashboard_client(session_id: str) -> None:
    """Remove a dashboard client when disconnected."""
    async with dashboard_clients_lock:
        dashboard_clients.pop(session_id, None)


async def broadcast_dashboard_update(event: Dict[str, Any]) -> None:
    """Dispatch an event to all connected dashboard clients."""
    stale_sessions: List[str] = []

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
) -> Dict[str, Any]:
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
        "event": "call_status_update",
        "call_sid": call_sid,
        "status": status,
        "message": message or f"Call status updated to {status}",
        "timestamp": datetime.utcnow().isoformat(),
    }

    if resolved_customer_id:
        event["customer_id"] = resolved_customer_id

    redis_manager.publish_event(call_sid, event)
    await broadcast_dashboard_update(event)
    return event




@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_connections.append(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive
    except:
        active_connections.remove(ws)

# -------------------------------
# Trigger call to Exotel
# -------------------------------
@app.post("/make_call")
async def make_call(number: str):
    BASE_URL = os.getenv("BASE_URL", "https://9a81252242ca.ngrok-free.app")
    
    # Use ExoML flow URL instead of direct callback (as per passthru applet workflow)
    flow_url = f"http://my.exotel.com/{EXOTEL_SID}/exoml/start_voice/{EXOTEL_FLOW_APP_ID}"

    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"https://api.exotel.com/v1/Accounts/{EXOTEL_SID}/Calls/connect",
            auth=(EXOTEL_SID, EXOTEL_TOKEN),
            data={
                "From": number,   # customer number
                "CallerId": EXOTEL_VIRTUAL_NUMBER,   # your Exotel virtual number
                "Url": flow_url,                               # ✅ ExoML flow URL
                "CallType": "trans",                           # ✅ Added proper call parameters
                "TimeLimit": EXOTEL_TIME_LIMIT,
                "TimeOut": EXOTEL_RING_TIMEOUT,
                "StatusCallback": f"{BASE_URL}/passthru-handler"  # ✅ final status updates
            }
        )

    return {
        "message": "Call triggered",
        "response": res.text
    }


# -------------------------------
# Callback from Exotel
# -------------------------------
import asyncio
import threading
from fastapi.responses import PlainTextResponse

@app.post("/exotel-callback", response_class=PlainTextResponse)
async def exotel_callback(request: Request):
    """
    Unified Exotel callback handler.
    Handles both:
      - Passthru Applet callbacks (field = 'Status')
      - Call API StatusCallbacks (field = 'CallStatus')
    Updates DB and broadcasts to frontend.
    """

    logger.websocket.info("✅ /exotel-callback hit")

    data = await request.form()
    form_dict = dict(data)
    logger.websocket.info(f"📨 FULL Exotel payload: {form_dict}")

    call_sid = data.get("CallSid")
    # Accept either "Status" (Passthru) or "CallStatus" (API)
    raw_status = data.get("Status") or data.get("CallStatus")
    custom_field = data.get("CustomField")

    if not call_sid:
        logger.error.error("❌ Exotel callback called without a CallSid.")
        return "OK"

    logger.websocket.info(f"📞 CallSid={call_sid}, RawStatus={raw_status}")
    logger.websocket.info(f"📦 CustomField={custom_field}")

    # --- Parse custom field if present ---
    customer_data = {}
    if custom_field:
        try:
            pairs = custom_field.split('|')
            for pair in pairs:
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    customer_data[key.strip()] = value.strip()
            logger.websocket.info(f"📊 Parsed Custom Fields: {customer_data}")
        except Exception as e:
            logger.error.error(f"❌ Failed to parse CustomField: {e}")

    temp_call_id = customer_data.get("temp_call_id")

    # --- Redis Caching ---
    if temp_call_id:
        redis_manager.link_session_to_sid(temp_call_id, call_sid)
    else:
        redis_manager.create_call_session(call_sid, customer_data)

    # --- Map Exotel raw status → internal status ---
    status_map = {
        "queued": "initiated",
        "in-progress": "call_in_progress",
        "answered": "call_in_progress",
        "ringing": "call_in_progress",   # 🔹 normalize ringing
        "completed": "call_completed",
        "busy": "call_failed",
        "failed": "call_failed",
        "no-answer": "call_failed",
        "not-answered": "call_failed",
        "cancelled": "call_failed",
        "canceled": "call_failed",
    }
    status = status_map.get(raw_status.lower() if raw_status else "", "call_failed")

    # --- Database Update ---
    try:
        logger.database.info(f"✍️ Updating database for CallSid={call_sid} with status={status}")
        session = db_manager.get_session()
        try:
            update_call_status(
                session=session,
                call_sid=call_sid,
                status=status,
                message=f"Exotel callback update (raw={raw_status}, temp_call_id={temp_call_id})"
            )
            session.commit()
            logger.database.info(f"✅ Database updated for CallSid={call_sid}")

            # 🔹 Auto-mark ringing → failed after 30s if no update
            if status == "call_in_progress":
                def mark_call_failed_if_still_in_progress(call_sid, customer_id):
                    s = db_manager.get_session()
                    try:
                        call_session = get_call_session_by_sid(s, call_sid)
                        if call_session and call_session.status == "call_in_progress":
                            update_call_status(
                                s,
                                call_sid,
                                "call_failed",
                                "Auto-marked after 30s with no further updates"
                            )
                            s.commit()
                            logger.database.info(f"⏱️ Auto-marked CallSid={call_sid} as call_failed")

                            # Broadcast safely
                            try:
                                loop = asyncio.get_event_loop()
                                loop.create_task(
                                    broadcast_status_update(call_sid, "call_failed", customer_id)
                                )
                            except RuntimeError:
                                asyncio.run(broadcast_status_update(call_sid, "call_failed", customer_id))
                    finally:
                        s.close()

                threading.Timer(
                    30,
                    mark_call_failed_if_still_in_progress,
                    args=[call_sid, customer_data.get("customer_id")]
                ).start()
        finally:
            session.close()
    except Exception as e:
        logger.error.error(f"❌ Database update failed for CallSid {call_sid}: {e}")

    # --- Broadcast to frontend immediately ---
    try:
        await broadcast_status_update(call_sid, status, customer_data.get("customer_id"))
    except Exception as e:
        logger.error.error(f"❌ Failed to broadcast status update: {e}")

    # Always return OK so Exotel doesn’t retry
    return "OK"

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

# Add 404 handler to track missing endpoints
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Handle 404 errors and log them for debugging"""
    print(f"🚨 404 NOT FOUND: {request.method} {request.url}")
    print(f"🚨 Headers: {dict(request.headers)}")
    if request.method == "POST":
        try:
            body = await request.body()
            print(f"🚨 Body: {body}")
        except:
            pass
    return JSONResponse(
        status_code=404,
        content={"detail": "Not Found", "path": str(request.url), "method": request.method}
    )

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
sarvam_handler = ProductionSarvamHandler(SARVAM_API_KEY)

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
BUFFER_DURATION_SECONDS = 4.0  # Increased from 1.0 to 4.0 seconds for better user response time
AGENT_RESPONSE_BUFFER_DURATION = 6.0  # Increased from 3.0 to 6.0 seconds for agent questions
MIN_AUDIO_BYTES = 1600  # Reduced from 3200 to 1600 (~0.1s) to capture shorter responses like 'yes', 'no'
AI_AGENT_RESPONSE_WAIT_SECONDS = 5.0  # Wait time before transcribing customer reply after AI agent speaks

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

# --- TTS & Audio Helper Functions ---

async def generate_dynamic_greeting(customer_data: dict, language: str = "en-IN") -> str:
    """
    Generate a dynamic greeting using Claude + Sarvam TTS.
    Returns the path to the saved audio file.
    """
    try:
        # 1. Ask Claude to create a personalized greeting
        system_prompt = f"""
You are a polite voice agent for Intalks AI Bank.
The customer is {customer_data.get('name', 'valued customer')} from {customer_data.get('state', 'their state')}.
Their loan ID is {customer_data.get('loan_id', 'N/A')}.
Generate a short, warm greeting (1–2 sentences) suitable for the start of a voice call.
Be sure to:
- Address the customer by name
- Mention their loan ID
- Ask if it is the right time to speak
"""
        
        messages = [
            {"role": "user", "content": [{"type": "text", "text": system_prompt}]}
        ]
        
        # Call Claude via Bedrock
        response_text = bedrock_client.invoke_claude_model(messages)
        print(f"🤖 Claude Greeting: {response_text}")
        
        # 2. Convert to speech
        sarvam_handler = ProductionSarvamHandler(os.getenv("SARVAM_API_KEY"))
        audio_bytes = await sarvam_handler.synthesize_tts(response_text, language)
        
        # 3. Save audio to file (Exotel expects file/URL)
        import wave, time
        from pathlib import Path
        audio_dir = Path("voice_bot_greetings")
        audio_dir.mkdir(exist_ok=True)
        
        filename = f"greeting_{int(time.time())}.wav"
        audio_path = audio_dir / filename
        
        with wave.open(str(audio_path), 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(8000)
            wav_file.writeframes(audio_bytes)
        
        print(f"💾 Greeting saved: {audio_path}")
        return str(audio_path)
    
    except Exception as e:
        print(f"❌ Error generating dynamic greeting: {e}")
        return None

async def play_transfer_to_agent(websocket, customer_number: str, customer_data: dict = None, session_id: str = None, language: str = "en-IN"):
    logger.tts.info("play_transfer_to_agent - Switching to Enhanced AI Agent mode")
    transfer_text = (
        "Please wait, I'm connecting you to our specialist agent who can provide more detailed assistance."
    )
    logger.tts.info("🔁 Converting agent transfer prompt")
    # Using 'en-IN' for transfer prompt for consistency, but could be `call_detected_lang`
    audio_bytes = await sarvam_handler.synthesize_tts(transfer_text, "en-IN")
    logger.tts.info(" Agent transfer audio generated")

    await stream_audio_to_websocket(websocket, audio_bytes)

    logger.websocket.info(" Switching to Enhanced AI Agent mode")
    logger.websocket.info(f" Agent creation - session_id: {session_id}, customer: {customer_data.get('name') if customer_data else 'None'}")
    
    # Switch to Enhanced AI Agent mode instead of human transfer
    if customer_data:
        ai_agent = await trigger_ai_agent_mode(websocket, customer_data, session_id, language)
        if ai_agent:
            logger.websocket.info(" Successfully switched to Enhanced AI Agent mode")
            return ai_agent
        else:
            logger.error.error(" Failed to switch to Enhanced AI Agent mode")
            return None
    else:
        logger.error.error("Could not switch to Enhanced AI Agent mode. Missing customer_data.")
        return None


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
        f"Hello {name}. I am calling from Intalks NGN Bank. "
        f"Am I speaking with {name} whose loan ID ends with {loan_suffix}?"
    )
    logger.tts.info(f"🔁 Confirmation prompt: {prompt}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt, "en-IN")
    await stream_audio_to_websocket(websocket, audio_bytes)


async def play_connecting_prompt(websocket) -> None:
    prompt = "Wait a second, I will connect you to one of our agents."
    logger.tts.info(f"🔁 Connecting prompt: {prompt}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt, "en-IN")
    await stream_audio_to_websocket(websocket, audio_bytes)


async def play_sorry_prompt(websocket) -> None:
    prompt = "Sorry for the disturbance. Thank you."
    logger.tts.info(f"🔁 Sorry prompt: {prompt}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt, "en-IN")
    await stream_audio_to_websocket(websocket, audio_bytes)


async def play_repeat_prompt(websocket, customer_info: Dict[str, Any]) -> None:
    name = customer_info.get("name") or "there"
    loan_suffix = _loan_suffix(customer_info.get("loan_id"))
    prompt = (
        f"I am sorry, I did not catch that. Am I speaking with {name} whose loan ID ends with {loan_suffix}?"
    )
    logger.tts.info(f"🔁 Repeat prompt: {prompt}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt, "en-IN")
    await stream_audio_to_websocket(websocket, audio_bytes)

# ... (rest of the code remains the same)
CHUNK_SIZE = 1600
async def stream_audio_to_websocket(websocket, audio_bytes):
    print("stream_audio_to_websocket")
    if not audio_bytes:
        print("[stream_audio_to_websocket] ❌ No audio bytes to stream.")
        return
    #CHUNK_SIZE=1600
    duration_ms = len(audio_bytes) / 16000 * 1000  # 16kBps → ~8kHz mono SLIN
    for i in range(0, len(audio_bytes), CHUNK_SIZE):
        chunk = audio_bytes[i:i + CHUNK_SIZE]
        if not chunk:
            continue
        b64_chunk = base64.b64encode(chunk).decode("utf-8")
        response_msg = {
            "event": "media",
            "media": {"payload": b64_chunk}
        }
      # Send audio chunk with improved error handling
        try:
            # Check if WebSocket is still open before sending
            if hasattr(websocket, 'client_state') and str(websocket.client_state) in ['DISCONNECTED', 'CLOSED']:
                print(f"🛑 WebSocket closed, stopping at chunk {i//CHUNK_SIZE + 1}")
                break
                
            await websocket.send_json(response_msg)
            print(f"🎵 Sent chunk {i//CHUNK_SIZE + 1} ({len(chunk)} bytes)")
            
        except Exception as _e:
            error_msg = str(_e)
            if "close message has been sent" in error_msg or "closed" in error_msg.lower():
                print(f"🛑 WebSocket closed during streaming at chunk {i//CHUNK_SIZE + 1}")
                break  # Stop gracefully when WebSocket is closed
            else:
                print(f"❌ Send failed on chunk {i//CHUNK_SIZE + 1}: {_e}")
                continue  # Continue for other errors

async def stream_audio_to_websocket_not_working(websocket, audio_bytes):
    CHUNK_SIZE = 8000  # Send 1 second of audio at a time
    if not audio_bytes:
        logger.error.warning("No audio bytes to stream.")
        return
    
    # Check if WebSocket is still connected before streaming
    websocket_state = getattr(getattr(websocket, 'client_state', None), 'name', 'UNKNOWN')
    if websocket_state not in ['CONNECTED', 'CONNECTING']:
        logger.error.warning(f"WebSocket not connected (state: {websocket_state}). Skipping audio stream.")
        return
    
    try:
        logger.websocket.info(f"📡 Starting audio stream: {len(audio_bytes)} bytes in {len(audio_bytes)//CHUNK_SIZE + 1} chunks")
        
        for i in range(0, len(audio_bytes), CHUNK_SIZE):
            # Check connection state before each chunk
            current_state = getattr(getattr(websocket, 'client_state', None), 'name', 'UNKNOWN')
            if current_state != 'CONNECTED':
                logger.error.warning(f"WebSocket disconnected during streaming (state: {current_state}). Stopping audio stream.")
                break
                
            chunk = audio_bytes[i:i + CHUNK_SIZE]
            if not chunk:
                continue
            b64_chunk = base64.b64encode(chunk).decode("utf-8")
            response_msg = {
                "event": "media",
                "media": {"payload": b64_chunk}
            }
            await websocket.send_json(response_msg)
            await asyncio.sleep(float(CHUNK_SIZE) / 16000.0) # Sleep for the duration of the audio chunk
            
        logger.websocket.info("✅ Audio stream completed successfully")
    except Exception as e:
        logger.error.error(f"Error streaming audio to WebSocket: {e}")
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

async def play_goodbye_after_decline(websocket, lang: str):
    """Plays a goodbye message if the user declines agent connection."""
    prompt_text = GOODBYE_TEMPLATE.get(lang, GOODBYE_TEMPLATE["en-IN"])
    logger.tts.info(f"🔁 Converting goodbye after decline: {prompt_text}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
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

def debug_intent_detection(transcript, language):
    """Debug function to test intent detection"""
    print(f"🔍 [DEBUG_INTENT] Testing intent detection for transcript: '{transcript}'")
    print(f"🔍 [DEBUG_INTENT] Language: {language}")
    
    # Test fallback detection first
    fallback_intent = detect_intent(transcript)
    print(f"🔍 [DEBUG_INTENT] Fallback detect_intent() result: '{fallback_intent}'")
    
    # Test Claude detection
    try:
        claude_intent = detect_intent_with_claude(transcript, language)
        print(f"🔍 [DEBUG_INTENT] Claude detect_intent_with_claude() result: '{claude_intent}'")
        return claude_intent
    except Exception as e:
        print(f"🔍 [DEBUG_INTENT] Claude detection failed: {e}")
        import traceback
        print(f"🔍 [DEBUG_INTENT] Full traceback: {traceback.format_exc()}")
        return fallback_intent


def detect_intent(text):
    print(f"🔄 [FALLBACK_INTENT_DEBUG] Input text: '{text}'")
    text = text.lower()
    
    if any(word in text for word in ["agent", "live agent", "speak to someone", "transfer", "help desk"]): 
        print(f"🔄 [FALLBACK_INTENT_DEBUG] Matched 'agent_transfer' keywords")
        return "agent_transfer"
    if any(word in text for word in ["yes", "yeah", "sure", "okay", "haan", "ஆம்", "అవుনు", "हॉं", "ಹೌದು", "please"]): 
        print(f"🔄 [FALLBACK_INTENT_DEBUG] Matched 'affirmative' keywords")
        return "affirmative"
    if any(word in text for word in ["no", "not now", "later", "nah", "nahi", "இல்லை", "காது", "ನಹಿ"]): 
        print(f"🔄 [FALLBACK_INTENT_DEBUG] Matched 'negative' keywords")
        return "negative"
    if any(word in text for word in ["what", "who", "why", "repeat", "pardon"]): 
        print(f"🔄 [FALLBACK_INTENT_DEBUG] Matched 'confused' keywords")
        return "confused"
    
    print(f"🔄 [FALLBACK_INTENT_DEBUG] No keywords matched, returning 'unknown'")
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
from fastapi.responses import PlainTextResponse

import threading

import asyncio
import threading
from fastapi.responses import PlainTextResponse

@app.post("/passthru-handler", response_class=PlainTextResponse)
async def handle_passthru(request: Request):
    """
    Handles Exotel's Passthru applet status callbacks.
    Exotel will POST form-encoded data (CallSid, Status, etc.).
    """
    logger.websocket.info("✅ /passthru-handler hit")

    # Read Exotel payload
    data = await request.form()
    form_dict = dict(data)
    logger.websocket.info(f"📨 FULL Exotel payload: {form_dict}")

    call_sid = data.get("CallSid")
    raw_status = data.get("Status")   # Exotel final status
    custom_field = data.get("CustomField")

    if not call_sid:
        logger.error.error("❌ Passthru handler called without a CallSid.")
        return "OK"

    logger.websocket.info(f"📞 Passthru: CallSid={call_sid}, Status={raw_status}")
    logger.websocket.info(f"📦 Passthru: CustomField={custom_field}")

    # --- Parse custom field if present ---
    customer_data = {}
    if custom_field:
        try:
            pairs = custom_field.split('|')
            for pair in pairs:
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    customer_data[key.strip()] = value.strip()
            logger.websocket.info(f"📊 Parsed Custom Fields: {customer_data}")
        except Exception as e:
            logger.error.error(f"❌ Failed to parse CustomField: {e}")

    temp_call_id = customer_data.get("temp_call_id")

    # --- Redis Caching ---
    if temp_call_id:
        redis_manager.link_session_to_sid(temp_call_id, call_sid)
    else:
        redis_manager.create_call_session(call_sid, customer_data)

    # --- Map Exotel raw status → internal status ---
    status_map = {
        "in-progress": "call_in_progress",
        "completed": "call_completed",
        "ringing": "ringing",
        "busy": "call_failed",
        "failed": "call_failed",
        "no-answer": "call_failed",
        "not-answered": "call_failed",
        "cancelled": "call_failed",
    }
    status = status_map.get(raw_status.lower() if raw_status else "", "call_failed")

    # --- Database Update ---
    try:
        logger.database.info(f"✍️ Updating database for CallSid={call_sid} with status={status}")
        session = db_manager.get_session()
        try:
            update_call_status(
                session=session,
                call_sid=call_sid,
                status=status,
                message=f"Passthru update - temp_call_id: {temp_call_id}"
            )
            session.commit()
            logger.database.info(f"✅ Database updated for CallSid={call_sid}")

            # 🔹 Auto-mark ringing → failed after 30s if no update
            if status == "ringing":
                def mark_call_failed_if_still_ringing(call_sid, customer_id):
                    s = db_manager.get_session()
                    try:
                        call_session = get_call_session_by_sid(s, call_sid)
                        if call_session and call_session.status == "ringing":
                            update_call_status(
                                s,
                                call_sid,
                                "call_failed",
                                "Auto-marked after ringing timeout"
                            )
                            s.commit()
                            logger.database.info(f"⏱️ Auto-marked CallSid={call_sid} as call_failed")

                            # Broadcast safely from thread
                            try:
                                loop = asyncio.get_event_loop()
                                loop.create_task(
                                    broadcast_status_update(call_sid, "call_failed", customer_id)
                                )
                            except RuntimeError:
                                asyncio.run(broadcast_status_update(call_sid, "call_failed", customer_id))
                    except Exception as e:
                        logger.error.error(f"❌ Auto-fail check failed for {call_sid}: {e}")
                    finally:
                        s.close()

                threading.Timer(30, mark_call_failed_if_still_ringing, args=[call_sid, customer_data.get("customer_id")]).start()

        finally:
            session.close()
    except Exception as e:
        logger.error.error(f"❌ Database update failed for CallSid {call_sid}: {e}")

    # --- Broadcast to frontend immediately ---
    try:
        await broadcast_status_update(call_sid, status, customer_data.get("customer_id"))
    except Exception as e:
        logger.error.error(f"❌ Failed to broadcast status update: {e}")

    # Always return OK so Exotel doesn’t retry
    return "OK"


@app.post("/flow-status", response_class=PlainTextResponse)
async def handle_flow_status(request: Request):
    """
    Handles status updates from ExoML flow.
    This endpoint receives status updates during the call flow execution.
    """
    logger.websocket.info("✅ /flow-status endpoint hit")

    # Read payload from Exotel
    data = await request.form()
    form_dict = dict(data)
    logger.websocket.info(f"📨 Flow status payload: {form_dict}")

    call_sid = form_dict.get("CallSid")
    status = form_dict.get("Status", "unknown")
    message = form_dict.get("Message", "")
    
    if call_sid:
        try:
            # Save status to call_status_updates table
            session = db_manager.get_session()
            try:
                from database.schemas import CallStatusUpdate, get_call_session_by_sid
                
                # Get the call session
                call_session = get_call_session_by_sid(session, call_sid)
                if call_session:
                    # Create status update record
                    status_update = CallStatusUpdate(
                        call_session_id=call_session.id,
                        status=status,
                        message=message,
                        extra_data=form_dict
                    )
                    session.add(status_update)
                    session.commit()
                    
                    logger.database.info(f"✅ Flow status saved: CallSid={call_sid}, Status={status}")
                    
                    # Broadcast to UI
                    await broadcast_status_update(call_sid, status, call_session.customer_id)
                else:
                    logger.database.warning(f"⚠️ Call session not found for CallSid: {call_sid}")
                    
            finally:
                session.close()
                
        except Exception as e:
            logger.error.error(f"❌ Failed to save flow status: {e}")

    return "OK"


EXOTEL_TOKEN="bbe529a13a976cbe1e2d90c92ce50a58f2559d87fed34380"      # Your Exotel API Token
EXOTEL_API_KEY="dbe31dfc1d3448dbd1d446f34f8941062201ca42fc153a0b" 


# --- WebSocket Endpoint for Voicebot ---
async def handle_voicebot_websocket(
    websocket: WebSocket,
    session_id: str,
    temp_call_id: str = None,
    call_sid: str = None,
    phone: str = None,
) -> None:
    """Voicebot session that verifies identity then hands off to Claude agent."""
    logger.websocket.info(f"✅ Connected to Exotel Voicebot for session: {session_id}")

    if not call_sid:
        call_sid = session_id

    transcript_logger = TranscriptLogger(TRANSCRIPTS_FILE_PATH, call_sid)

    customer_info: Optional[Dict[str, Any]] = None
    call_detected_lang = "en-IN"
    conversation_stage = "AWAIT_START"
    audio_buffer = bytearray()
    last_transcription_time = time.time()
    interaction_complete = False
    confirmation_attempts = 0
    ai_agent_active = False

    async def speak_text(text: str, language: str = "en-IN") -> None:
        if not text:
            return
        try:
            audio_bytes = await sarvam_handler.synthesize_tts(text, language)
        except Exception as err:
            logger.tts.error(f"❌ Error synthesizing speech: {err}")
            return
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
        if not info or not info.get('name'):
            return None
        if not info.get('loan_id'):
            info['loan_id'] = 'unknown'
        if not info.get('amount'):
            info['amount'] = 'the outstanding amount'
        if not info.get('due_date'):
            info['due_date'] = 'the due date'
        return info

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

    async def record_status(status: str, message: str = "", fallback_customer_id: Optional[str] = None) -> None:
        resolved_customer_id = fallback_customer_id
        try:
            session = db_manager.get_session()
            try:
                call_session = update_call_status(
                    session=session,
                    call_sid=call_sid,
                    status=status,
                    message=message,
                )
                session.commit()
                if call_session and call_session.customer_id:
                    resolved_customer_id = str(call_session.customer_id)
            finally:
                session.close()
        except Exception as status_error:
            logger.database.error(f"❌ Failed to persist status {status} for {call_sid}: {status_error}")
        try:
            await broadcast_status_update(call_sid, status, resolved_customer_id, message)
        except Exception as broadcast_error:
            logger.websocket.error(f"❌ Failed to broadcast status update: {broadcast_error}")

    async def handle_start_event(msg: Dict[str, Any]) -> bool:
        nonlocal call_sid, customer_info, conversation_stage, last_transcription_time, call_detected_lang

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

        if temp_call_id and call_sid:
            try:
                redis_manager.link_session_to_sid(temp_call_id, call_sid)
            except Exception as link_error:
                logger.websocket.warning(f"⚠️ Failed to link temp session: {link_error}")

        info: Optional[Dict[str, Any]] = None
        if temp_call_id:
            session_data = redis_manager.get_call_session(temp_call_id)
            if session_data:
                info = session_data.get('customer_data') or session_data
        if not info and call_sid:
            session_data = redis_manager.get_call_session(call_sid)
            if session_data:
                info = session_data.get('customer_data') or session_data

        custom_field = (
            msg.get('customField')
            or (msg.get('start') or {}).get('customField')
            or (msg.get('start') or {}).get('custom_field')
        )
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
                    'id': parsed.get('customer_id'),
                }

        if not info and phone:
            clean_phone = sanitize_phone(phone)
            phone_candidates = {phone}
            if clean_phone:
                phone_candidates.add(clean_phone)
                if len(clean_phone) >= 10:
                    last_10 = clean_phone[-10:]
                    phone_candidates.update({
                        last_10,
                        f"91{last_10}",
                        f"+91{last_10}",
                    })

            for candidate in list(phone_candidates):
                try:
                    temp_key = f"customer_phone_{candidate}"
                    temp_data = redis_manager.get_temp_data(temp_key)
                    if temp_data:
                        info = {
                            'name': temp_data.get('name'),
                            'loan_id': temp_data.get('loan_id'),
                            'amount': temp_data.get('amount'),
                            'due_date': temp_data.get('due_date'),
                            'lang': temp_data.get('language_code', 'en-IN'),
                            'phone': temp_data.get('phone_number') or temp_data.get('phone'),
                            'state': temp_data.get('state', ''),
                            'id': temp_data.get('customer_id'),
                        }
                        break
                except Exception as temp_err:
                    logger.websocket.warning(f"⚠️ Redis temp lookup failed for {candidate}: {temp_err}")

            if not info:
                info = await resolve_customer_from_db(phone)

        info = ensure_customer_info(info)
        if not info:
            logger.websocket.warning("⚠️ Customer data not found; falling back to minimal context")
            info = {
                'name': 'valued customer',
                'loan_id': 'unknown',
                'amount': 'the outstanding amount',
                'due_date': 'the due date',
                'lang': 'en-IN',
                'phone': phone,
                'state': '',
                'id': None,
            }

        customer_info = info
        transcript_logger.update_customer(
            customer_info.get('name'),
            customer_info.get('phone') or customer_info.get('phone_number'),
        )
        call_detected_lang = customer_info.get('lang') or 'en-IN'

        await record_status(
            CallStatus.CALL_IN_PROGRESS,
            "Voice assistant connected",
            fallback_customer_id=str(customer_info.get('id')) if customer_info.get('id') else None,
        )

        await play_confirmation_prompt(websocket, customer_info)
        conversation_stage = "WAITING_CONFIRMATION"
        last_transcription_time = time.time()
        return True

    async def handle_confirmation_response(transcript: str) -> Optional[str]:
        nonlocal conversation_stage, confirmation_attempts, call_detected_lang, ai_agent_active, interaction_complete, last_transcription_time

        normalized = (transcript or "").lower()
        affirmative = {"yes", "yeah", "yep", "haan", "ha", "correct", "sure", "yup"}
        negative = {"no", "nah", "nope", "nahi", "na"}

        if any(word in normalized for word in affirmative):
            call_detected_lang = detect_language(transcript)
            await play_connecting_prompt(websocket)
            await record_status(
                CallStatus.AGENT_TRANSFER,
                "Customer verified identity",
                fallback_customer_id=str(customer_info.get('id')) if customer_info and customer_info.get('id') else None,
            )
            try:
                agent = await trigger_ai_agent_mode(
                    websocket,
                    customer_info or {},
                    call_sid,
                    call_detected_lang,
                )
                if agent:
                    ai_agent_active = True
                    conversation_stage = "AI_AGENT_MODE"
                    confirmation_attempts = 0
                    last_transcription_time = time.time()
                    return "affirmative"
            except Exception as agent_error:
                logger.error.error(f"❌ Failed to start AI agent: {agent_error}")

            await speak_text(
                "I'm sorry, I'm unable to connect you to our agent right now. We'll reach out shortly. Goodbye.",
            )
            conversation_stage = "GOODBYE_SENT"
            interaction_complete = True
            return "end"

        if any(word in normalized for word in negative):
            await play_sorry_prompt(websocket)
            await record_status(
                CallStatus.DISCONNECTED,
                "Customer declined identity confirmation",
                fallback_customer_id=str(customer_info.get('id')) if customer_info and customer_info.get('id') else None,
            )
            conversation_stage = "GOODBYE_SENT"
            interaction_complete = True
            return "negative"

        confirmation_attempts += 1
        if confirmation_attempts >= 3:
            await play_sorry_prompt(websocket)
            await record_status(
                CallStatus.DISCONNECTED,
                "Identity confirmation failed",
                fallback_customer_id=str(customer_info.get('id')) if customer_info and customer_info.get('id') else None,
            )
            conversation_stage = "GOODBYE_SENT"
            interaction_complete = True
            return "negative"

        await play_repeat_prompt(websocket, customer_info or {})
        return None

    try:
        while True:
            try:
                message_text = await websocket.receive_text()
            except WebSocketDisconnect:
                logger.websocket.warning("⚠️ WebSocket disconnected")
                break

            msg = json.loads(message_text)
            event = msg.get("event")
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

            payload_b64 = (msg.get("media") or {}).get("payload")
            if not payload_b64:
                continue

            try:
                raw_audio = base64.b64decode(payload_b64)
            except Exception as decode_error:
                logger.websocket.error(f"❌ Failed to decode audio payload: {decode_error}")
                continue

            if raw_audio and any(b != 0 for b in raw_audio):
                audio_buffer.extend(raw_audio)

            now = time.time()
            buffer_timeout = BUFFER_DURATION_SECONDS
            if conversation_stage == "AI_AGENT_MODE":
                buffer_timeout = AI_AGENT_RESPONSE_WAIT_SECONDS

            if now - last_transcription_time < buffer_timeout:
                continue

            if len(audio_buffer) < MIN_AUDIO_BYTES:
                audio_buffer.clear()
                last_transcription_time = now
                continue

            try:
                transcript_result = await sarvam_handler.transcribe_from_payload(audio_buffer)
            except Exception as err:
                logger.websocket.error(f"❌ Error transcribing audio: {err}")
                audio_buffer.clear()
                last_transcription_time = now
                continue

            audio_buffer.clear()
            last_transcription_time = time.time()

            if isinstance(transcript_result, tuple):
                transcript_text, detected_lang = transcript_result
                if detected_lang:
                    call_detected_lang = detected_lang
                transcript = transcript_text
            else:
                transcript = transcript_result

            transcript = (transcript or "").strip()
            if not transcript:
                continue

            transcript_logger.add_transcript(transcript, last_transcription_time)

            if conversation_stage == "WAITING_CONFIRMATION":
                outcome = await handle_confirmation_response(transcript)
                if outcome in {"negative", "end"}:
                    interaction_complete = True
                    break
                continue

            if conversation_stage == "AI_AGENT_MODE":
                call_detected_lang = detect_language(transcript) or call_detected_lang
                should_continue = await handle_ai_agent_conversation(
                    websocket,
                    transcript,
                    call_sid,
                    customer_info or {},
                    call_detected_lang,
                )
                last_transcription_time = time.time()
                if not should_continue:
                    interaction_complete = True
                    break
                continue

            if conversation_stage == "GOODBYE_SENT":
                interaction_complete = True
                break

    except Exception as err:
        logger.error.error(f"WebSocket error: {err}")
    finally:
        if transcript_logger:
            transcript_logger.flush(force=True)

        if ai_agent_active:
            try:
                await cleanup_ai_agent_session(call_sid)
            except Exception as cleanup_error:
                logger.websocket.error(f"❌ Error cleaning up AI agent: {cleanup_error}")

        final_status = (
            CallStatus.CALL_COMPLETED
            if conversation_stage == "AI_AGENT_MODE" and ai_agent_active
            else CallStatus.DISCONNECTED
            if conversation_stage == "GOODBYE_SENT"
            else CallStatus.CALL_COMPLETED
        )
        try:
            await record_status(final_status, "Conversation ended")
        except Exception as final_status_error:
            logger.database.error(f"❌ Failed to persist final status: {final_status_error}")

        try:
            if not interaction_complete:
                await asyncio.sleep(1)

            websocket_state = getattr(getattr(websocket, 'client_state', None), 'name', 'UNKNOWN')
            if websocket_state not in ['DISCONNECTED', 'CLOSED']:
                try:
                    await websocket.close()
                    logger.websocket.info("🔒 WebSocket connection closed gracefully")
                except Exception as close_attempt_error:
                    if "close message has been sent" in str(close_attempt_error):
                        logger.websocket.info("🔒 WebSocket already closed")
                    else:
                        logger.error.error(f"Error closing WebSocket: {close_attempt_error}")
            else:
                logger.websocket.info(f"🔒 WebSocket already in state: {websocket_state}")
        except Exception as close_error:
            if "close message has been sent" not in str(close_error):
                logger.error.error(f"Error closing WebSocket: {close_error}")


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

    async def sender() -> None:
        while True:
            event = await event_queue.get()
            try:
                await websocket.send_text(json.dumps(event))
            except WebSocketDisconnect:
                break

    async def receiver() -> None:
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
    Accepts a CSV file with the new format and processes it using the enhanced CSV processor.
    Expected CSV columns: name,phone,loan_id,amount,due_date,state,Cluster,Branch,
    Branch Contact Number,Employee,Employee ID,Employee Contact Number,
    Last Paid Date,Last Paid Amount,Due Amount
    """
    print(f"📁 [CHECKPOINT] /api/upload-customers endpoint hit")
    print(f"📁 [CHECKPOINT] File name: {file.filename}")
    print(f"📁 [CHECKPOINT] File content type: {file.content_type}")
    
    try:
        # Validate file type
        if not file.filename.lower().endswith('.csv'):
            return {
                "success": False, 
                "error": "Only CSV files are supported with the new format"
            }
        
        file_data = await file.read()
        print(f"📁 [CHECKPOINT] File size: {len(file_data)} bytes")
        
        # Use the enhanced CSV service
        from services.enhanced_csv_upload_service import enhanced_csv_service
        result = await enhanced_csv_service.upload_and_process_csv(
            file_data=file_data,
            filename=file.filename,
            uploaded_by="dashboard_user"  # TODO: Get from auth context
        )
        
        print(f"📁 [CHECKPOINT] Enhanced CSV processing result: {result}")
        return result
        
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in upload_customers endpoint: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/uploaded-files")
async def get_uploaded_files(
    page: int = 1, 
    page_size: int = 25, 
    date_filter: str = None
):
    """
    Retrieves uploaded file records with pagination and filtering.
    
    Args:
        page: Page number (1-based)
        page_size: Number of records per page (25, 50, or 100)
        date_filter: Filter by date - 'today', 'week', 'month', or None for all
    """
    print(f"📄 [CHECKPOINT] /api/uploaded-files endpoint hit - page: {page}, page_size: {page_size}, filter: {date_filter}")
    
    # Validate input parameters
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 25
    if page_size > 1000:  # Prevent excessive load
        page_size = 1000
    
    try:
        from database.schemas import get_session, FileUpload
        from sqlalchemy import desc, and_
        from datetime import datetime, timedelta
        import pytz
        
        # IST timezone setup
        IST = pytz.timezone('Asia/Kolkata')
        
        session = get_session()
        try:
            # Build base query
            query = session.query(FileUpload).order_by(desc(FileUpload.uploaded_at))
            
            # Apply date filtering if specified
            if date_filter:
                # Get current time in IST and convert to UTC for database comparison
                ist_now = datetime.now(IST)
                if date_filter == 'today':
                    start_date_ist = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
                    start_date_utc = start_date_ist.astimezone(pytz.UTC).replace(tzinfo=None)
                    query = query.filter(FileUpload.uploaded_at >= start_date_utc)
                elif date_filter == 'week':
                    start_date_ist = ist_now - timedelta(days=7)
                    start_date_utc = start_date_ist.astimezone(pytz.UTC).replace(tzinfo=None)
                    query = query.filter(FileUpload.uploaded_at >= start_date_utc)
                elif date_filter == 'month':
                    start_date_ist = ist_now - timedelta(days=30)
                    start_date_utc = start_date_ist.astimezone(pytz.UTC).replace(tzinfo=None)
                    query = query.filter(FileUpload.uploaded_at >= start_date_utc)
            
            # Get total count for pagination
            total_count = query.count()
            
            # Apply pagination
            offset = (page - 1) * page_size
            file_uploads = query.offset(offset).limit(page_size).all()
            
            # Convert to list of dictionaries with detailed information
            upload_data = []
            for upload in file_uploads:
                upload_info = {
                    'id': str(upload.id),
                    'filename': upload.filename,
                    'original_filename': upload.original_filename,
                    'uploaded_by': upload.uploaded_by,
                    'uploaded_at': upload.uploaded_at.isoformat() if upload.uploaded_at else None,
                    'total_records': upload.total_records,
                    'processed_records': upload.processed_records,
                    'success_records': upload.success_records,
                    'failed_records': upload.failed_records,
                    'status': upload.status,
                    'processing_errors': upload.processing_errors,
                    # Computed fields
                    'file_size_bytes': 0,  # Not stored in current schema
                    'duplicate_records': 0,  # Not tracked separately
                    'processing_started_at': None,  # Not stored in current schema
                    'processing_completed_at': None,  # Not stored in current schema
                    'validation_errors': None,  # Not stored in current schema
                    'metadata': None  # Not stored in current schema
                }
                upload_data.append(upload_info)
            
            # Calculate pagination info
            total_pages = (total_count + page_size - 1) // page_size  # Ceiling division
            has_next = page < total_pages
            has_prev = page > 1
            
            print(f"📄 [CHECKPOINT] Found {len(upload_data)} uploaded files on page {page}/{total_pages} (total: {total_count})")
            return {
                'success': True,
                'uploads': upload_data,
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_count': total_count,
                    'total_pages': total_pages,
                    'has_next': has_next,
                    'has_prev': has_prev
                }
            }
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in get_uploaded_files endpoint: {e}")
        return {"success": False, "error": str(e), "uploads": [], "pagination": {"current_page": 1, "page_size": 25, "total_count": 0, "total_pages": 0, "has_next": False, "has_prev": False}}

@app.get("/api/uploaded-files/ids")
async def get_uploaded_file_ids(date_filter: str = None):
    """
    Retrieves all uploaded file IDs for select all functionality with filtering.
    
    Args:
        date_filter: Filter by date - 'today', 'week', 'month', or None for all
    """
    print(f"📄 [CHECKPOINT] /api/uploaded-files/ids endpoint hit - filter: {date_filter}")
    
    try:
        from database.schemas import get_session, FileUpload
        from sqlalchemy import desc
        from datetime import datetime, timedelta
        import pytz
        
        # IST timezone setup
        IST = pytz.timezone('Asia/Kolkata')
        
        session = get_session()
        try:
            # Build base query
            query = session.query(FileUpload.id).order_by(desc(FileUpload.uploaded_at))
            
            # Apply date filtering if specified
            if date_filter:
                # Get current time in IST and convert to UTC for database comparison
                ist_now = datetime.now(IST)
                if date_filter == 'today':
                    start_date_ist = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
                    start_date_utc = start_date_ist.astimezone(pytz.UTC).replace(tzinfo=None)
                    query = query.filter(FileUpload.uploaded_at >= start_date_utc)
                elif date_filter == 'week':
                    start_date_ist = ist_now - timedelta(days=7)
                    start_date_utc = start_date_ist.astimezone(pytz.UTC).replace(tzinfo=None)
                    query = query.filter(FileUpload.uploaded_at >= start_date_utc)
                elif date_filter == 'month':
                    start_date_ist = ist_now - timedelta(days=30)
                    start_date_utc = start_date_ist.astimezone(pytz.UTC).replace(tzinfo=None)
                    query = query.filter(FileUpload.uploaded_at >= start_date_utc)
            
            # Get all IDs
            upload_ids = [str(upload.id) for upload in query.all()]
            
            print(f"📄 [CHECKPOINT] Found {len(upload_ids)} upload IDs with filter: {date_filter}")
            return {
                'success': True,
                'upload_ids': upload_ids,
                'total_count': len(upload_ids)
            }
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in get_uploaded_file_ids endpoint: {e}")
        return {"success": False, "error": str(e), "upload_ids": []}

@app.get("/api/uploaded-files/{upload_id}/details")
async def get_upload_details(upload_id: str):
    """
    Retrieves detailed information about a specific upload including individual row processing results.
    """
    print(f"📄 [CHECKPOINT] /api/uploaded-files/{upload_id}/details endpoint hit")
    
    try:
        from database.schemas import get_session, FileUpload, UploadRow
        
        session = get_session()
        try:
            # Get the file upload record
            upload = session.query(FileUpload).filter(FileUpload.id == upload_id).first()
            
            if not upload:
                return {"success": False, "error": "Upload not found"}
            
            # Get associated upload rows
            upload_rows = session.query(UploadRow).filter(UploadRow.file_upload_id == upload_id).all()
            
            # Convert upload rows to detailed information
            row_details = []
            for row in upload_rows:
                row_info = {
                    'id': str(row.id),
                    'line_number': row.line_number,
                    'raw_data': row.raw_data,
                    'status': row.status,
                    'error': row.error,
                    'match_method': row.match_method,
                    'match_customer_id': str(row.match_customer_id) if row.match_customer_id else None,
                    'match_loan_id': str(row.match_loan_id) if row.match_loan_id else None,
                    'created_at': row.matched_at.isoformat() if row.matched_at else None
                }
                row_details.append(row_info)
            
            # Upload summary
            upload_details = {
                'id': str(upload.id),
                'filename': upload.filename,
                'original_filename': upload.original_filename,
                'uploaded_by': upload.uploaded_by,
                'uploaded_at': upload.uploaded_at.isoformat() if upload.uploaded_at else None,
                'total_records': upload.total_records,
                'processed_records': upload.processed_records,
                'success_records': upload.success_records,
                'failed_records': upload.failed_records,
                'status': upload.status,
                'processing_errors': upload.processing_errors,
                'rows': row_details,
                # Fields not in current schema
                'file_size_bytes': 0,
                'duplicate_records': 0,
                'processing_started_at': None,
                'processing_completed_at': None,
                'validation_errors': None,
                'metadata': None
            }
            
            print(f"📄 [CHECKPOINT] Retrieved details for upload {upload_id} with {len(row_details)} rows")
            return {
                'success': True,
                'upload_details': upload_details
            }
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in get_upload_details endpoint: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/uploaded-files/{upload_id}/download")
async def download_batch_report(upload_id: str):
    """
    Downloads a CSV report for a specific batch upload.
    """
    print(f"📄 [CHECKPOINT] /api/uploaded-files/{upload_id}/download endpoint hit")
    
    try:
        from database.schemas import get_session, FileUpload, UploadRow
        from fastapi.responses import StreamingResponse
        import io
        import csv
        
        session = get_session()
        try:
            # Get the upload record
            upload = session.query(FileUpload).filter(FileUpload.id == upload_id).first()
            if not upload:
                raise HTTPException(status_code=404, detail="Upload not found")
            
            # Get upload rows for this batch
            upload_rows = session.query(UploadRow).filter(UploadRow.file_upload_id == upload_id).all()
            
            # Create CSV content
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            headers = [
                'Line Number', 'Status', 'Customer Name', 'Phone', 'Loan ID', 
                'Amount', 'Due Date', 'State', 'Cluster', 'Branch',
                'Match Method', 'Error Message', 'Processed At'
            ]
            writer.writerow(headers)
            
            # Write data rows
            for row in upload_rows:
                raw_data = row.raw_data or {}
                writer.writerow([
                    row.line_number,
                    row.status,
                    raw_data.get('name', ''),
                    raw_data.get('phone', ''),
                    raw_data.get('loan_id', ''),
                    raw_data.get('amount', ''),
                    raw_data.get('due_date', ''),
                    raw_data.get('state', ''),
                    raw_data.get('cluster', ''),
                    raw_data.get('branch', ''),
                    row.match_method or '',
                    row.error or '',
                    row.matched_at.isoformat() if row.matched_at else ''
                ])
            
            # Create response
            output.seek(0)
            filename = f"batch_report_{upload.filename}_{upload.uploaded_at.strftime('%Y%m%d_%H%M%S')}.csv"
            
            print(f"📄 [CHECKPOINT] Generated CSV report for upload {upload_id} with {len(upload_rows)} rows")
            
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode('utf-8')),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
            
        finally:
            session.close()
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in download_batch_report endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession



@app.post("/api/trigger-single-call")
async def trigger_single_call(customer_id: str = Body(..., embed=True)):
    """
    Triggers a single call to a customer by their ID and starts polling for status.
    """
    print(f"🚀 [CHECKPOINT] /api/trigger-single-call endpoint hit")
    print(f"🚀 [CHECKPOINT] Customer ID: {customer_id}")
    
    try:
        result = await call_service.trigger_single_call(customer_id)
        print(f"🚀 [CHECKPOINT] Call service result: {result}")

        call_sid = result.get("call_sid")
        if call_sid:
            asyncio.create_task(poll_exotel_call_status(call_sid, customer_id))
            print(f"🚀 [CHECKPOINT] Polling started for CallSid: {call_sid}")
        else:
            print("⚠️ [CHECKPOINT] No call_sid found in result, polling not started")

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
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in trigger_bulk_calls endpoint: {e}")
        return {"success": False, "error": str(e)}
    

@app.get("/api/customers")
async def get_all_customers():
    """
    Retrieves all customers with their loan information from the database.
    Updated to support new CSV schema with enhanced data.
    """
    print(f"👥 [CHECKPOINT] /api/customers endpoint hit")
    
    from database.schemas import get_session
    session = get_session()
    try:
        # Query customers with their loans and call sessions
        from database.schemas import CallSession
        customers = session.query(Customer).options(
            joinedload(Customer.loans),
            joinedload(Customer.call_sessions)
        ).all()
        print(f"👥 [CHECKPOINT] Found {len(customers)} customers in database")
        
        result = []
        for customer in customers:
            # Calculate totals from loans
            total_outstanding = sum(loan.outstanding_amount or 0 for loan in customer.loans)
            total_due = sum(loan.due_amount or 0 for loan in customer.loans)
            total_loans = len(customer.loans)
            
            # Get primary loan data (first loan or most recent)
            primary_loan = customer.loans[0] if customer.loans else None
            
            # Get latest call status from call sessions
            latest_call_status = "ready"  # Default status
            if customer.call_sessions:
                # Sort call sessions by created_at descending to get the latest
                latest_session = sorted(customer.call_sessions, key=lambda x: x.created_at, reverse=True)[0]
                latest_call_status = latest_session.status or "ready"
            
            customer_data = {
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
                "call_status": latest_call_status,  # Use latest call status from call sessions
                
                # Loan aggregation data
                "total_loans": total_loans,
                "total_outstanding": float(total_outstanding),
                "total_due": float(total_due),
                
                # Primary loan details (from first loan)
                "loan_id": primary_loan.loan_id if primary_loan else None,
                "outstanding_amount": float(primary_loan.outstanding_amount or 0) if primary_loan else 0,
                "due_amount": float(primary_loan.due_amount or 0) if primary_loan else 0,
                "next_due_date": format_ist_datetime(primary_loan.next_due_date) if primary_loan and primary_loan.next_due_date else None,
                "last_paid_date": format_ist_datetime(primary_loan.last_paid_date) if primary_loan and primary_loan.last_paid_date else None,
                "last_paid_amount": float(primary_loan.last_paid_amount or 0) if primary_loan else 0,
                
                # Branch and employee information (from primary loan)
                "cluster": primary_loan.cluster if primary_loan else None,
                "branch": primary_loan.branch if primary_loan else None,
                "branch_contact_number": primary_loan.branch_contact_number if primary_loan else None,
                "employee_name": primary_loan.employee_name if primary_loan else None,
                "employee_id": primary_loan.employee_id if primary_loan else None,
                "employee_contact_number": primary_loan.employee_contact_number if primary_loan else None,
                
                # All loans details
                "loans": [
                    {
                        "id": str(loan.id),
                        "loan_id": loan.loan_id,
                        "outstanding_amount": float(loan.outstanding_amount or 0),
                        "due_amount": float(loan.due_amount or 0),
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
                        "updated_at": format_ist_datetime(loan.updated_at)
                    } for loan in customer.loans
                ]
            }
            
            result.append(customer_data)
        
        print(f"👥 [CHECKPOINT] Returning customer list successfully")
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in get_all_customers endpoint: {e}")
        return []
    finally:
        session.close()

from fastapi import Request
from database.schemas import (
    db_manager,
    update_call_status,
    get_call_session_by_sid,
    update_customer_call_status_by_phone
)


@app.post("/exotel-webhook")
async def exotel_webhook(request: Request):
    """
    Handles Exotel call status webhooks and updates DB + Customer status.
    """
    form_data = await request.form()
    form_dict = dict(form_data)

    print("📩 Webhook received:", form_dict)

    call_sid = form_dict.get("CallSid")
    exotel_status = form_dict.get("CallStatus")

    print("📩 Raw Exotel Status:", exotel_status)

    # Map Exotel → internal statuses (used in DB + frontend)
    status_mapping = {
        "initiated": "initiated",
        "ringing": "call_in_progress",
        "answered": "call_in_progress",
        "in-progress": "call_in_progress",
        "completed": "call_completed",
        "failed": "call_failed",
        "busy": "call_failed",
        "no-answer": "call_failed",
        "not-answered": "call_failed",
        "canceled": "call_failed",
        "cancelled": "call_failed",
    }

    internal_status = status_mapping.get(exotel_status.lower(), "call_failed") if exotel_status else "call_failed"

    # --- Database update ---
    session = db_manager.get_session()
    try:
        call_session = get_call_session_by_sid(session, call_sid)
        if call_session:
            print(f"✅ Found call session for CallSid={call_sid}")
            
            # Update CallSession
            update_call_status(
                session,
                call_sid,
                internal_status,
                f"Exotel webhook: {exotel_status}",
                extra_data=form_dict
            )

            # Save to call_status_updates table
            from database.schemas import CallStatusUpdate
            status_update = CallStatusUpdate(
                call_session_id=call_session.id,
                status=internal_status,
                message=f"Exotel webhook: {exotel_status}",
                extra_data=form_dict
            )
            session.add(status_update)

            # Update Customer
            if call_session.customer:
                print(f"✅ Found customer for call: {call_session.customer.full_name} ({call_session.customer.primary_phone})")
                update_customer_call_status_by_phone(
                    session,
                    call_session.customer.primary_phone,
                    internal_status
                )
            else:
                print(f"⚠️ No customer found for call session CallSid={call_sid}")

            session.commit()
            print(f"✅ CallSid={call_sid} updated → {internal_status}")
        else:
            print(f"⚠️ No call session found for CallSid={call_sid}")

    except Exception as e:
        session.rollback()
        print(f"❌ Error updating call status: {e}")
    finally:
        db_manager.close_session(session)

    return {"status": "ok"}


async def poll_exotel_call_status(call_sid: str, customer_id: str, interval: int = 10, max_attempts: int = 20):
    """
    Polls Exotel API for call status and updates DB until call is completed or max attempts reached.
    Uses db_manager instead of SessionLocal and maps Exotel statuses → internal statuses.
    """
    url = f"https://api.exotel.com/v1/Accounts/{EXOTEL_SID}/Calls/{call_sid}.json"
    auth = (EXOTEL_API_KEY, EXOTEL_TOKEN)

    status_map = {
        "in-progress": "call_in_progress",
        "answered": "call_in_progress",
        "completed": "call_completed",
        "failed": "call_failed",
        "busy": "call_failed",
        "no-answer": "call_failed",
        "not-answered": "call_failed",
        "canceled": "call_failed",
        "cancelled": "call_failed",
    }

    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, auth=auth)

            if response.status_code == 200:
                call_data = response.json().get("Call", {})
                raw_status = call_data.get("Status", "").lower()
                end_time = call_data.get("EndTime")
                duration = call_data.get("Duration")

                logger.websocket.info(f"📞 [POLL] Call {call_sid} status: {raw_status}")

                # Map to internal status
                status = status_map.get(raw_status, "call_failed")

                # --- DB Update ---
                session = db_manager.get_session()
                try:
                    # Update call_sessions
                    call_session = get_call_session_by_sid(session, call_sid)
                    if call_session:
                        update_call_status(
                            session=session,
                            call_sid=call_sid,
                            status=status,
                            message=f"Polled Exotel: {raw_status}",
                            extra_data=call_data
                        )

                    # Update customers
                    customer = session.query(Customer).filter_by(id=customer_id).first()
                    if customer:
                        customer.call_status = status
                        customer.updated_at = datetime.utcnow()

                    session.commit()
                    logger.database.info(f"✅ [POLL] DB updated: {call_sid} → {status}")

                    # --- Broadcast ---
                    await broadcast_status_update(call_sid, status, customer_id)

                finally:
                    session.close()

                # Stop polling if final status reached
                if raw_status in ["completed", "failed", "busy", "no-answer", "canceled", "cancelled"]:
                    logger.websocket.info(f"✅ [POLL] Final status for {call_sid}: {status}")
                    break

            else:
                logger.error.error(f"⚠️ [POLL] Failed to fetch status for {call_sid}. HTTP {response.status_code}")

        except Exception as e:
            logger.error.error(f"❌ [POLL] Error while polling Exotel: {e}")

        await asyncio.sleep(interval)


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
        
        session = db_manager.get_session()  # Use db_manager to get session
        try:
            # Update customer call status
            update_customer_call_status(
                session,
                customer_id,
                call_status
            )
            session.commit()
            return JSONResponse(
                status_code=200,
                content={"success": True, "message": f"Customer status updated to {call_status}"}
            )
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
        
        session = db_manager.get_session()  # Use db_manager to get session
        try:
            updated_count = 0
            for customer_id in customer_ids:
                if update_customer_call_status(session, customer_id, call_status):
                    updated_count += 1
            session.commit()
            return JSONResponse(
                status_code=200,
                content={
                    "success": True, 
                    "message": f"Updated {updated_count}/{len(customer_ids)} customers to {call_status}"
                }
            )
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [API] Error updating bulk customer status: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Internal server error: {str(e)}"}
        )


@app.get("/api/call-statuses")
async def get_call_statuses(request: Request):
    """Get call status updates for the UI dashboard"""
    try:
        session = db_manager.get_session()
        try:
            from database.schemas import CallStatusUpdate, CallSession, Customer
            
            # Get all call status updates with related data
            status_updates = session.query(CallStatusUpdate).join(
                CallSession, CallStatusUpdate.call_session_id == CallSession.id
            ).join(
                Customer, CallSession.customer_id == Customer.id
            ).order_by(CallStatusUpdate.timestamp.desc()).limit(100).all()
            
            # Format response
            statuses = []
            for update in status_updates:
                statuses.append({
                    "id": str(update.id),
                    "call_sid": update.call_session.call_sid,
                    "customer_name": update.call_session.customer.full_name,
                    "customer_phone": update.call_session.customer.primary_phone,
                    "status": update.status,
                    "message": update.message,
                    "timestamp": format_ist_datetime(update.timestamp),
                    "extra_data": update.extra_data
                })
            
            return JSONResponse(
                status_code=200,
                content={"success": True, "statuses": statuses}
            )
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [API] Error fetching call statuses: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Internal server error: {str(e)}"}
        )


@app.get("/api/call-statuses/{call_sid}")
async def get_call_status_by_sid(call_sid: str):
    """Get all status updates for a specific call"""
    try:
        session = db_manager.get_session()
        try:
            from database.schemas import CallStatusUpdate, CallSession, Customer
            
            # Get call session
            call_session = get_call_session_by_sid(session, call_sid)
            if not call_session:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "error": "Call session not found"}
                )
            
            # Get all status updates for this call
            status_updates = session.query(CallStatusUpdate).filter(
                CallStatusUpdate.call_session_id == call_session.id
            ).order_by(CallStatusUpdate.timestamp.asc()).all()
            
            # Format response
            statuses = []
            for update in status_updates:
                statuses.append({
                    "id": str(update.id),
                    "status": update.status,
                    "message": update.message,
                    "timestamp": format_ist_datetime(update.timestamp),
                    "extra_data": update.extra_data
                })
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True, 
                    "call_sid": call_sid,
                    "customer_name": call_session.customer.full_name if call_session.customer else None,
                    "customer_phone": call_session.customer.primary_phone if call_session.customer else None,
                    "statuses": statuses
                }
            )
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [API] Error fetching call status: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Internal server error: {str(e)}"}
        )


# This is a catch-all for the old websocket endpoint, redirecting or handling as needed.
@app.websocket("/stream")
async def old_websocket_endpoint(websocket: WebSocket):
    """Legacy /stream endpoint delegates to the unified voicebot handler."""
    await websocket.accept()

    query_params = dict(websocket.query_params)
    temp_call_id = query_params.get('temp_call_id')
    call_sid = query_params.get('call_sid')
    phone = query_params.get('phone')

    session_identifier = call_sid or temp_call_id or generate_websocket_session_id()

    await handle_voicebot_websocket(
        websocket,
        session_identifier,
        temp_call_id=temp_call_id,
        call_sid=call_sid,
        phone=phone,
    )


async def broadcast_status_update(
    call_sid: str,
    status: str,
    customer_id: Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    """Broadcast a call status update to dashboard listeners and legacy clients."""

    event_message = message or f"Call status updated to {status}"
    try:
        event = await push_status_update(
            call_sid=call_sid,
            status=status,
            message=event_message,
            customer_id=customer_id,
        )
    except Exception as publish_error:
        logger.websocket.error(
            f"❌ Failed to publish status update via Redis/dashboard: {publish_error}"
        )
        event = {
            "event": "call_status_update",
            "call_sid": call_sid,
            "status": status,
            "customer_id": customer_id,
            "message": event_message,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Ensure legacy listeners receive a familiar payload
    event.setdefault("event", "call_status_update")

    disconnected: List[WebSocket] = []
    for ws in list(active_connections):
        try:
            await ws.send_text(json.dumps(event))
        except Exception as send_error:
            logger.error.error(f"❌ Failed to send WS message: {send_error}")
            disconnected.append(ws)

    for ws in disconnected:
        try:
            active_connections.remove(ws)
        except ValueError:
            continue

    logger.websocket.info(f"📢 Broadcasted status update: {event}")





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
