import os
import asyncio
import base64
import json
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import httpx
import pandas as pd
import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import (Body, FastAPI, File, HTTPException, Request, UploadFile,
                     WebSocket, Depends, Query)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from requests.auth import HTTPBasicAuth
from starlette.websockets import WebSocketDisconnect
from starlette.middleware.sessions import SessionMiddleware

# Load environment variables at the very beginning
load_dotenv()

# Import project-specific modules
from database.schemas import (CallStatus, Customer,
                              db_manager, init_database, update_call_status, get_call_session_by_sid)
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


# --- Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # Initialize logging system first
    setup_application_logging()
    logger.info("🚀 Starting Voice Assistant Application...")
    
    # Initialize database
    if init_database():
        logger.info("✅ Database initialized successfully")
        logger.database.info("Database connection established")
    else:
        logger.error("❌ Database initialization failed")
        logger.database.error("Failed to establish database connection")
    
    # Initialize Redis
    if init_redis():
        logger.info("✅ Redis initialized successfully")
    else:
        logger.warning("❌ Redis initialization failed - running without session management")
    
    logger.info("🎉 Application startup complete!")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Voice Assistant Application...")

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

# --- Constants ---
BUFFER_DURATION_SECONDS = 5.0  # Wait 5 seconds for user response (increased from 1.0)
AGENT_RESPONSE_BUFFER_DURATION = 7.0  # Wait even longer for user to answer agent connect question
MIN_AUDIO_BYTES = 3200  # ~0.2s at 8kHz 16-bit mono; ignore too-short buffers

# --- Multilingual Prompt Templates with SSML and Pauses ---
GREETING_TEMPLATE = {
    "en-IN": "Hello, this is Priya from South India Finvest Bank. Am I speaking with Mr. {name}?",
    "hi-IN": "नमस्ते, मैं प्रिया हूं, साउथ इंडिया फिनवेस्ट बैंक से। क्या मैं श्री {name} से बात कर रही हूं?",
    "ta-IN": "வணக்கம், நான் பிரியா, சவுத் இந்தியா ஃபின்வெஸ்ட் வங்கியிலிருந்து பேசுகிறேன். நான் திரு {name} அவர்களுடன் பேசுகிறேனா?",
    "te-IN": "నమస్కారం, నేను ప్రియ, సౌత్ ఇండియా ఫిన్‌వెస్ట్ బ్యాంక్ నుండి మాట్లాడుతున్నాను. నేను శ్రీ {name} గారితో మాట్లాడుతున్నానా?",
    "ml-IN": "നമസ്കാരം, ഞാൻ പ്രിയ, സൗത്ത് ഇന്ത്യ ഫിൻവെസ്റ്റ് ബാങ്കിൽ നിന്ന് സംസാരിക്കുന്നു. ഞാൻ ശ്രീ {name}ുമായി സംസാരിക്കുകയാണോ?",
    "gu-IN": "નમસ્તે, હું પ્રિયા, સાઉથ ઇન્ડિયા ફિનવેસ્ટ બેંકમાંથી બોલી રહી છું. શું હું શ્રી {name} સાથે વાત કરી રહી છું?",
    "mr-IN": "नमस्कार, मी प्रिया, साउथ इंडिया फिनवेस्ट बँकेतून बोलत आहे. मी श्री {name} यांच्याशी बोलत आहे का?",
    "bn-IN": "নমস্কার, আমি প্রিয়া, সাউথ ইন্ডিয়া ফিনভেস্ট ব্যাংক থেকে বলছি। আমি কি श्री {name}-এর সঙ্গে কথা বলছি?",
    "kn-IN": "ನಮಸ್ಕಾರ, ನಾನು ಪ್ರಿಯಾ, ಸೌತ್ ಇಂಡಿಯಾ ಫಿನ್‌ವೆಸ್ಟ್ ಬ್ಯಾಂಕ್‌ನಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ. ನಾನು ಶ್ರೀ {name} ಅವರೊಂದಿಗೆ ಮಾತನಾಡುತ್ತಿದ್ದೇನೇ?",
    "pa-IN": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਮੈਂ ਪ੍ਰਿਆ, ਸਾਊਥ ਇੰਡੀਆ ਫਿਨਵੈਸਟ ਬੈਂਕ ਤੋਂ ਗੱਲ ਕਰ ਰਹੀ ਹਾਂ। ਕੀ ਮੈਂ ਸ੍ਰੀ {name} ਨਾਲ ਗੱਲ ਕਰ ਰਹੀ ਹਾਂ?",
    "or-IN": "ନମସ୍କାର, ମୁଁ ପ୍ରିୟା, ସାଉଥ୍ ଇଣ୍ଡିଆ ଫିନଭେଷ୍ଟ ବ୍ୟାଙ୍କରୁ କହୁଛି। ମୁଁ କି ସ୍ରୀ {name} ସହ କଥା କହୁଛି?",
}


EMI_DETAILS_PART1_TEMPLATE = {
    "en-IN": "Your loan ending {loan_id} has an EMI of ₹{amount} due on {due_date}.",
    "hi-IN": "आपके लोन {loan_id} की ईएमआई ₹{amount} {due_date} को देय है।",
    "ta-IN": "உங்கள் கடன் {loan_id} க்கான EMI ₹{amount} {due_date} அன்று செலுத்த வேண்டியுள்ளது.",
    "te-IN": "మీ రుణం {loan_id} కి సంబంధించిన ₹{amount} EMI {due_date} నాటికి చెల్లించవలసి ఉంటుంది.",
    "ml-IN": "നിങ്ങളുടെ വായ്പ {loan_id} ന് ₹{amount} EMI {due_date} ന് അടയ്ക്കേണ്ടതാണ്.",
    "gu-IN": "તમારા લોન {loan_id} ની ₹{amount} EMI {due_date} ના રોજ ચુકવવાની છે.",
    "mr-IN": "तुमच्या कर्ज {loan_id} ची ₹{amount} EMI {due_date} रोजी देय आहे.",
    "bn-IN": "আপনার ঋণ {loan_id} এর ₹{amount} EMI {due_date} তারিখে পরিশোধযোগ্য।",
    "kn-IN": "ನಿಮ್ಮ ಸಾಲ {loan_id} ಗೆ ₹{amount} EMI {due_date} ರಂದು ಪಾವತಿಸಬೇಕಾಗಿದೆ.",
    "pa-IN": "ਤੁਹਾਡੇ ਲੋਨ {loan_id} ਦੀ ₹{amount} EMI {due_date} ਨੂੰ ਅਦਾ ਕਰਨੀ ਹੈ।",
    "or-IN": "ଆପଣଙ୍କର ଋଣ {loan_id} ର ₹{amount} EMI {due_date} ରେ ଦେୟ ଅଟେ।",
}


EMI_DETAILS_PART2_TEMPLATE = {
    "en-IN": "If unpaid, it may affect your credit score and add penalties.",
    "hi-IN": "यदि बकाया रहे तो आपका क्रेडिट स्कोर प्रभावित हो सकता है और पेनल्टी लग सकती है।",
    "ta-IN": "செலுத்தாவிட்டால், உங்கள் கிரெடிட் ஸ்கோர் பாதிக்கப்படலாம் மற்றும் அபராதம் வரலாம்.",
    "te-IN": "చెల్లించకపోతే, మీ క్రెడిట్ స్కోర్ ప్రభావితం కావచ్చు మరియు జరిమానా విధించబడవచ్చు.",
    "ml-IN": "അടയ്ക്കാതിരുന്നാൽ, നിങ്ങളുടെ ക്രെഡിറ്റ് സ്കോർ ബാധിക്കാം, പിഴയും ബാധകമാകും.",
    "gu-IN": "ચુકવવામાં ન આવે તો, તમારો ક્રેડિટ સ્કોર પ્રભાવિત થઈ શકે છે અને દંડ લાગી શકે છે.",
    "mr-IN": "न भरल्यास, तुमचा क्रेडिट स्कोर प्रभावित होऊ शकतो आणि दंड आकारला जाऊ शकतो.",
    "bn-IN": "অপরিশোধিত থাকলে, আপনার ক্রেডিট স্কোর প্রভাবিত হতে পারে এবং জরিমানা আরোপ হতে পারে।",
    "kn-IN": "ಪಾವತಿಯಾಗದಿದ್ದರೆ, ನಿಮ್ಮ ಕ್ರೆಡಿಟ್ ಸ್ಕೋರ್ ಪರಿಣಾಮವಾಗಬಹುದು ಮತ್ತು ದಂಡ ವಿಧಿಸಲಾಗಬಹುದು.",
    "pa-IN": "ਜੇ ਨਹੀਂ ਭਰਿਆ ਤਾਂ, ਤੁਹਾਡਾ ਕਰੈਡਿਟ ਸਕੋਰ ਪ੍ਰਭਾਵਿਤ ਹੋ ਸਕਦਾ ਹੈ ਅਤੇ ਜੁਰਮਾਨਾ ਲੱਗ ਸਕਦਾ ਹੈ।",
    "or-IN": "ଅପରିଶୋଧିତ ରହିଲେ, ଆପଣଙ୍କର କ୍ରେଡିଟ୍ ସ୍କୋର ପ୍ରଭାବିତ ହୋଇପାରେ ଏବଂ ଜରିମାନା ଲାଗିପାରେ।",
}


AGENT_CONNECT_TEMPLATE = {
    "en-IN": "Would you like me to connect you to our agent for assistance?",
    "hi-IN": "क्या मैं आपको सहायता के लिए हमारे एजेंट से जोड़ दूं?",
    "ta-IN": "உதவிக்காக எங்கள் ஏஜெண்டுடன் இணைக்க விரும்புகிறீர்களா?",
    "te-IN": "సహాయం కోసం మిమ్మల్ని మా ఏజెంట్‌తో కలిపించాలనా?",
    "ml-IN": "സഹായത്തിന് നിങ്ങളെ ഞങ്ങളുടെ ഏജന്റുമായി ബന്ധിപ്പിക്കട്ടെയോ?",
    "gu-IN": "શું હું તમને મદદ માટે અમારા એજન્ટ સાથે જોડું?",
    "mr-IN": "मी तुम्हाला मदतीसाठी आमच्या एजंटशी जोडू का?",
    "bn-IN": "আপনাকে সাহায্যের জন্য আমাদের এজেন্টের সাথে যুক্ত করব?",
    "kn-IN": "ಸಹಾಯಕ್ಕಾಗಿ ನಾನು ನಿಮ್ಮನ್ನು ನಮ್ಮ ಏಜೆಂಟ್‌ಗೆ ಸಂಪರ್ಕ ಮಾಡಬೇಕೇ?",
    "pa-IN": "ਕੀ ਮੈਂ ਤੁਹਾਨੂੰ ਮਦਦ ਲਈ ਸਾਡੇ ਏਜੰਟ ਨਾਲ ਜੋੜਾਂ?",
    "or-IN": "ଆପଣଙ୍କୁ ସହାୟତା ପାଇଁ ଆମ ଏଜେଣ୍ଟ ସହିତ ଯୋଗାଯୋଗ କରିଦେବି କି?",
}


GOODBYE_TEMPLATE = {
    "en-IN": "I understand. If you change your mind, please call us back. Thank you. Goodbye.",
    "hi-IN": "मैं समझती हूँ। यदि आप अपना विचार बदलते हैं, तो कृपया हमें दोबारा कॉल करें। धन्यवाद। अलविदा।",
    "ta-IN": "நான் புரிந்துகொள்கிறேன். நீங்கள் உங்கள் எண்ணத்தை மாற்றினால், தயவுசெய்து எங்களை மீண்டும் அழைக்கவும். நன்றி. விடைபெறுகிறேன்.",
    "te-IN": "నాకు అర్థమైంది. మీరు మీ నిర్ణయాన్ని మార్చుకుంటే, దయచేసి మమ్మల్ని తిరిగి కాల్ చేయండి. ధన్యవాదాలు. వీడ్కోలు.",
    "ml-IN": "ഞാൻ മനസ്സിലാക്കുന്നു. നിങ്ങൾ അഭിപ്രായം മാറ്റുകയാണെങ്കിൽ, ദയവായി ഞങ്ങളെ വീണ്ടും വിളിക്കുക. നന്ദി. വിട.",
    "gu-IN": "હું સમજી છું. જો તમે તમારો વિચાર બદલો, તો કૃપા કરીને અમને ફરીથી કોલ કરો. આભાર. અલવિદા.",
    "mr-IN": "मी समजले. तुम्ही तुमचा निर्णय बदलल्यास, कृपया आम्हाला पुन्हा कॉल करा. धन्यवाद. अलविदा.",
    "bn-IN": "আমি বুঝতে পারছি। আপনি যদি মত পরিবর্তন করেন, অনুগ্রহ করে আমাদের আবার কল করুন। ধন্যবাদ। বিদায়।",
    "kn-IN": "ನಾನು ಅರ್ಥಮಾಡಿಕೊಂಡೆ. ನೀವು ನಿಮ್ಮ ನಿರ್ಧಾರವನ್ನು ಬದಲಿಸಿದರೆ, ದಯವಿಟ್ಟು ನಮಗೆ ಮತ್ತೆ ಕರೆ ಮಾಡಿ. ಧನ್ಯವಾದಗಳು. ವಿದಾಯ.",
    "pa-IN": "ਮੈਂ ਸਮਝਦੀ ਹਾਂ। ਜੇ ਤੁਸੀਂ ਆਪਣਾ ਮਨ ਬਦਲੋ, ਤਾਂ ਕਿਰਪਾ ਕਰਕੇ ਸਾਨੂੰ ਦੁਬਾਰਾ ਕਾਲ ਕਰੋ। ਧੰਨਵਾਦ। ਅਲਵਿਦਾ।",
    "or-IN": "ମୁଁ ବୁଝିଲି। ଯଦି ଆପଣ ମନ ବଦଳାନ୍ତି, ଦୟାକରି ଆମକୁ ପୁନି କଲ୍ କରନ୍ତୁ। ଧନ୍ୟବାଦ। ବିଦାୟ।"
}


# --- TTS & Audio Helper Functions ---

async def play_transfer_to_agent(websocket, customer_number: str):
    logger.tts.info("play_transfer_to_agent")
    transfer_text = (
        "Please wait, we are transferring the call to an agent."
    )
    logger.tts.info("🔁 Converting agent transfer prompt")
    # Using 'en-IN' for transfer prompt for consistency, but could be `call_detected_lang`
    audio_bytes = await sarvam_handler.synthesize_tts("Please wait, we are transferring the call to an agent.", "en-IN")
    logger.tts.info("📢 Agent transfer audio generated")

    await stream_audio_to_websocket(websocket, audio_bytes)

    logger.websocket.info("📞 Initiating agent call transfer")
    # The AGENT_NUMBER should be loaded from environment variables
    agent_number = os.getenv("AGENT_PHONE_NUMBER")
    if customer_number and agent_number:
        await trigger_exotel_agent_transfer(customer_number, agent_number)
    else:
        logger.error("Could not initiate agent transfer. Missing customer_number or agent_number.")

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
        # Guard against sending after close
        try:
            state = getattr(getattr(websocket, 'client_state', None), 'name', 'CONNECTED')
            if state not in ['CONNECTED', 'CONNECTING']:
                print(f"[stream_audio_to_websocket] WebSocket not connected (state={state}). Stopping stream.")
                break
            await websocket.send_json(response_msg)
        except Exception as _e:
            print(f"[stream_audio_to_websocket] Send failed: {_e}")
            break
        await asyncio.sleep(0.02)  # simulate real-time playback
    # Provide a tiny cushion only; chunk pacing already matched duration
    print(f"[stream_audio_to_websocket] Streamed ~{duration_ms:.0f}ms of audio (paced)")
    await asyncio.sleep(0.1)

async def stream_audio_to_websocket_not_working(websocket, audio_bytes):
    CHUNK_SIZE = 8000  # Send 1 second of audio at a time
    if not audio_bytes:
        logger.warning("No audio bytes to stream.")
        return
    
    # Check if WebSocket is still connected before streaming
    if websocket.client_state.name not in ['CONNECTED', 'CONNECTING']:
        logger.warning(f"WebSocket not connected (state: {websocket.client_state.name}). Skipping audio stream.")
        return
    
    try:
        logger.websocket.info(f"📡 Starting audio stream: {len(audio_bytes)} bytes in {len(audio_bytes)//CHUNK_SIZE + 1} chunks")
        
        for i in range(0, len(audio_bytes), CHUNK_SIZE):
            # Check connection state before each chunk
            if websocket.client_state.name != 'CONNECTED':
                logger.warning(f"WebSocket disconnected during streaming (state: {websocket.client_state.name}). Stopping audio stream.")
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
        logger.error(f"Error streaming audio to WebSocket: {e}")
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
    """Legacy function - redirects to strict detection"""
    return detect_intent_strict(text)

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

# --- WebSocket Endpoint for Voicebot ---
async def handle_voicebot_websocket(websocket: WebSocket, session_id: str, temp_call_id: str = None, call_sid: str = None, phone: str = None):
    """
    Core voicebot WebSocket handling logic - extracted to be reusable.
    """
    logger.websocket.info(f"✅ Connected to Exotel Voicebot for session: {session_id}")

    # Initialize variables from parameters
    if not call_sid:
        call_sid = session_id  # Use session_id as a fallback for call_sid

    logger.websocket.info(f"Session params: temp_call_id={temp_call_id}, call_sid={call_sid}, phone={phone}")

    # State variable for the conversation stage
    conversation_stage = "INITIAL_GREETING" # States: INITIAL_GREETING, WAITING_FOR_CONFIRMATION, WAITING_FOR_LANG_DETECT, PLAYING_EMI_DETAILS, ASKING_AGENT_CONNECT, WAITING_AGENT_RESPONSE, TRANSFERRING_TO_AGENT, GOODBYE_DECLINE
    call_detected_lang = "en-IN" # Default language, will be updated after first user response
    audio_buffer = bytearray()
    last_transcription_time = time.time()
    interaction_complete = False # Flag to stop processing media after the main flow ends
    customer_info = None # Will be set when we get customer data
    initial_greeting_played = False # Track if initial greeting was played
    agent_question_repeat_count = 0 # Track how many times agent question was repeated
    confirmation_attempts = 0 # Track confirmation attempts

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            logger.log_websocket_message("Received message", msg)

            if msg.get("event") == "start":
                logger.websocket.info("🔁 Got start event")
                
                # Try to get customer info from multiple sources
                if not customer_info:
                    # 1. Try to get from Redis using temp_call_id or call_sid
                    if temp_call_id:
                        logger.database.info(f"Looking up customer data by temp_call_id: {temp_call_id}")
                        redis_data = redis_manager.get_call_session(temp_call_id)
                        if redis_data:
                            customer_info = {
                                'name': redis_data.get('name'),
                                'loan_id': redis_data.get('loan_id'),
                                'amount': redis_data.get('amount'),
                                'due_date': redis_data.get('due_date'),
                                'lang': redis_data.get('language_code', 'en-IN'),
                                'phone': redis_data.get('phone_number', ''),
                                'state': redis_data.get('state', '')
                            }
                            print(f"[WebSocket] ✅ Found customer data in Redis: {customer_info['name']}")
                    
                    elif call_sid:
                        print(f"[WebSocket] Looking up customer data by call_sid: {call_sid}")
                        redis_data = redis_manager.get_call_session(call_sid)
                        if redis_data:
                            customer_info = {
                                'name': redis_data.get('name'),
                                'loan_id': redis_data.get('loan_id'),
                                'amount': redis_data.get('amount'),
                                'due_date': redis_data.get('due_date'),
                                'lang': redis_data.get('language_code', 'en-IN'),
                                'phone': redis_data.get('phone_number', ''),
                                'state': redis_data.get('state', '')
                            }
                            print(f"[WebSocket] ✅ Found customer data in Redis: {customer_info['name']}")
                    
                    elif phone:
                        print(f"[WebSocket] Looking up customer data by phone: {phone}")
                        # Clean phone number for lookup
                        clean_phone = phone.replace('+', '').replace('-', '').replace(' ', '')
                        phone_key = f"customer_phone_{clean_phone}"
                        redis_data = redis_manager.get_temp_data(phone_key)
                        if redis_data:
                            customer_info = {
                                'name': redis_data.get('name'),
                                'loan_id': redis_data.get('loan_id'),
                                'amount': redis_data.get('amount'),
                                'due_date': redis_data.get('due_date'),
                                'lang': redis_data.get('language_code', 'en-IN'),
                                'phone': redis_data.get('phone_number', ''),
                                'state': redis_data.get('state', '')
                            }
                            print(f"[WebSocket] ✅ Found customer data by phone in Redis: {customer_info['name']}")
                
                # 2. Try to parse CustomField data from Exotel start message (if available)
                if not customer_info and 'customField' in msg:
                    print("[WebSocket] Parsing CustomField from Exotel start message")
                    try:
                        custom_field = msg['customField']
                        # Parse the CustomField format: "customer_id=|customer_name=Name|loan_id=LOAN123|..."
                        parts = custom_field.split('|')
                        custom_data = {}
                        for part in parts:
                            if '=' in part:
                                key, value = part.split('=', 1)
                                custom_data[key] = value
                        
                        customer_info = {
                            'name': custom_data.get('customer_name'),
                            'loan_id': custom_data.get('loan_id'),
                            'amount': custom_data.get('amount'),
                            'due_date': custom_data.get('due_date'),
                            'lang': custom_data.get('language_code', 'en-IN'),
                            'phone': '',
                            'state': custom_data.get('state', '')
                        }
                        print(f"[WebSocket] ✅ Parsed customer data from CustomField: {customer_info['name']}")
                    except Exception as e:
                        print(f"[WebSocket] ❌ Error parsing CustomField: {e}")
                
                # 3. Try to get customer data from database by phone number (if available)
                if not customer_info and phone:
                    print(f"[WebSocket] Looking up customer in database by phone: {phone}")
                    try:
                        from database.schemas import get_customer_by_phone
                        session = db_manager.get_session()
                        
                        # Clean phone number for database lookup - more comprehensive approach
                        clean_phone = phone.replace('+', '').replace('-', '').replace(' ', '')
                        
                        # Extract just the 10-digit number if it's an Indian number
                        if len(clean_phone) >= 10:
                            last_10_digits = clean_phone[-10:]
                        else:
                            last_10_digits = clean_phone
                        
                        # Try multiple phone number formats that might be in the database
                        possible_phones = [
                            phone,                      # Original format
                            clean_phone,               # Cleaned format
                            f"+{clean_phone}",         # With + prefix
                            f"+91{last_10_digits}",    # With +91 prefix
                            f"91{last_10_digits}",     # With 91 prefix (no +)
                            last_10_digits             # Just 10 digits
                        ]
                        
                        # Remove duplicates and empty values
                        possible_phones = list(set([p for p in possible_phones if p]))
                        print(f"[WebSocket] Trying phone formats: {possible_phones}")
                        
                        db_customer = None
                        for phone_variant in possible_phones:
                            db_customer = get_customer_by_phone(session, phone_variant)
                            if db_customer:
                                print(f"[WebSocket] ✅ Found customer with phone variant: {phone_variant}")
                                break
                        
                        if db_customer:
                            customer_info = {
                                'name': db_customer.name,
                                'loan_id': db_customer.loan_id,
                                'amount': db_customer.amount,
                                'due_date': db_customer.due_date,
                                'lang': db_customer.language_code or 'en-IN',
                                'phone': db_customer.phone_number,
                                'state': db_customer.state or ''
                            }
                            print(f"[WebSocket] ✅ Found customer in database: {customer_info['name']} (Phone: {customer_info['phone']})")
                        else:
                            print(f"[WebSocket] ❌ Customer not found in database for phone: {phone}")
                        
                        session.close()
                    except Exception as e:
                        print(f"[WebSocket] ❌ Error looking up customer in database: {e}")
                
                # 4. If no customer found anywhere, throw an error instead of using fallback data
                if not customer_info:
                    print("[WebSocket] ❌ No customer data found - cannot proceed without real customer information")
                    await websocket.send_text(json.dumps({
                        "event": "error",
                        "message": "Customer data not found. Please ensure customer information is uploaded and call is triggered properly."
                    }))
                    return
                
                # 5. Validate customer data has required fields (allow placeholder values)
                required_fields = ['name', 'loan_id', 'amount', 'due_date']
                missing_fields = [field for field in required_fields if not customer_info.get(field)]
                if missing_fields:
                    print(f"[WebSocket] ❌ Customer data missing required fields: {missing_fields}")
                    await websocket.send_text(json.dumps({
                        "event": "error",
                        "message": f"Customer data incomplete. Missing fields: {', '.join(missing_fields)}"
                    }))
                    return
                
                # Convert placeholder values to generic terms for speech
                if customer_info.get('loan_id') in ['Unknown', 'N/A', None]:
                    customer_info['loan_id'] = '1234'  # Generic loan ID for speech
                if customer_info.get('amount') in ['Unknown', 'N/A', '₹0', None]:
                    customer_info['amount'] = '5000'  # Generic amount for speech
                if customer_info.get('due_date') in ['Unknown', 'N/A', None]:
                    customer_info['due_date'] = 'this month'  # Generic due date for speech
                
                print(f"[WebSocket] ✅ Customer data validated: {customer_info['name']} - Loan: {customer_info['loan_id']}, Amount: ₹{customer_info['amount']}")
                
                # Determine initial language: prioritize state-based language over CSV language
                customer_state = customer_info.get('state', '').strip()
                state_based_language = get_initial_language_from_state(customer_state)
                csv_language = customer_info.get('lang', 'en-IN')
                
                # Use state language for initial greeting as requested
                initial_greeting_language = state_based_language
                logger.websocket.info(f"State: {customer_state}, State Language: {state_based_language}, CSV Language: {csv_language}")
                logger.websocket.info(f"Using state-based language for initial greeting: {initial_greeting_language}")
                
                # Play initial greeting immediately when WebSocket starts
                if conversation_stage == "INITIAL_GREETING":
                    logger.websocket.info(f"1. Playing initial greeting for {customer_info['name']} in {initial_greeting_language} (state-based)")
                    try:
                        # Use the working template approach with state-based language
                        await greeting_template_play(websocket, customer_info, lang=initial_greeting_language)
                        logger.websocket.info(f"✅ Initial greeting played successfully in {initial_greeting_language}")
                        initial_greeting_played = True
                        conversation_stage = "WAITING_FOR_CONFIRMATION"  # Wait for user to confirm they are the right person
                        logger.websocket.info(f"🎯 Now waiting for user confirmation/response...")
                    except Exception as e:
                        logger.websocket.error(f"❌ Error playing initial greeting: {e}")
                        # Try fallback simple greeting in English
                        try:
                            simple_greeting = f"Hello, this is South India Finvest Bank calling. Am I speaking with {customer_info['name']}?"
                            audio_bytes = await sarvam_handler.synthesize_tts_end(simple_greeting, "en-IN")
                            await stream_audio_to_websocket(websocket, audio_bytes)
                            logger.websocket.info("✅ Fallback greeting sent successfully")
                            initial_greeting_played = True
                            conversation_stage = "WAITING_FOR_CONFIRMATION"  # Wait for user confirmation
                            logger.websocket.info(f"🎯 Now waiting for user confirmation/response...")
                        except Exception as fallback_e:
                            logger.websocket.error(f"❌ Error sending fallback greeting: {fallback_e}")
                continue

            if msg.get("event") == "media":
                payload_b64 = msg["media"]["payload"]
                raw_audio = base64.b64decode(payload_b64)

                if interaction_complete:
                    continue

                if raw_audio and any(b != 0 for b in raw_audio):
                    audio_buffer.extend(raw_audio)
                
                now = time.time()

                # Stage-specific buffer timeout: wait longer for agent response
                buffer_timeout = AGENT_RESPONSE_BUFFER_DURATION if conversation_stage == "WAITING_AGENT_RESPONSE" else BUFFER_DURATION_SECONDS

                if now - last_transcription_time >= buffer_timeout:
                    if len(audio_buffer) == 0:
                        if conversation_stage == "WAITING_FOR_CONFIRMATION":
                            confirmation_attempts += 1
                            if confirmation_attempts <= 2:
                                logger.websocket.info(f"No audio received during confirmation stage. Playing 'didn't hear' prompt (attempt {confirmation_attempts}/2).")
                                logger.log_call_event("NO_AUDIO_CONFIRMATION", call_sid, customer_info['name'], {"attempt": confirmation_attempts})
                                await play_did_not_hear_response(websocket, call_detected_lang)
                                last_transcription_time = time.time()
                            else:
                                logger.websocket.info("Too many no-audio responses during confirmation. Ending call.")
                                logger.log_call_event("CALL_END_NO_CONFIRMATION", call_sid, customer_info['name'])
                                interaction_complete = True
                                break
                        elif conversation_stage == "WAITING_FOR_LANG_DETECT":
                            logger.websocket.info("No audio received during language detection stage. Playing 'didn't hear' prompt.")
                            logger.log_call_event("NO_AUDIO_LANG_DETECT", call_sid, customer_info['name'])
                            await play_did_not_hear_response(websocket, call_detected_lang)
                            # Reset the timer to wait for user response
                            last_transcription_time = time.time()
                        elif conversation_stage == "WAITING_AGENT_RESPONSE":
                            agent_question_repeat_count += 1
                            if agent_question_repeat_count <= 3:  # Increased to 3 repeats for better user experience
                                logger.websocket.info(f"No audio received during agent question stage. Repeating question (attempt {agent_question_repeat_count}/3).")
                                logger.log_call_event("AGENT_QUESTION_REPEAT", call_sid, customer_info['name'], {"attempt": agent_question_repeat_count})
                                await play_agent_connect_question(websocket, call_detected_lang)
                                # Reset the timer to wait for user response
                                last_transcription_time = time.time()
                            else:
                                # After 3 attempts with no response, play a clarifying message and try once more
                                logger.websocket.info("No clear response after 3 attempts. Playing clarification message.")
                                logger.log_call_event("AGENT_QUESTION_CLARIFICATION", call_sid, customer_info['name'])
                                
                                # Play clarifying message asking for clear yes/no response
                                clarification_msg = {
                                    "en-IN": "Please say 'yes' if you want to speak to an agent, or 'no' if you don't need assistance.",
                                    "hi-IN": "कृपया 'हां' कहें यदि आप एजेंट से बात करना चाहते हैं, या 'नहीं' कहें यदि आपको सहायता की आवश्यकता नहीं है।",
                                    "ta-IN": "நீங்கள் ஒரு முகவரிடம் பேச விரும்பினால் 'ஆம்' என்று சொல்லுங்கள், அல்லது உங்களுக்கு உதவி தேவையில்லை என்றால் 'இல்லை' என்று சொல்லுங்கள்।"
                                }
                                clarify_text = clarification_msg.get(call_detected_lang, clarification_msg["en-IN"])
                                audio_bytes = await sarvam_handler.synthesize_tts(clarify_text, call_detected_lang)
                                await stream_audio_to_websocket(websocket, audio_bytes)
                                
                                # Reset counter for final attempt
                                agent_question_repeat_count = 0
                                last_transcription_time = time.time()
                        audio_buffer.clear()
                        last_transcription_time = now
                        continue

                    try:
                        # Ignore too-short buffers that yield empty transcripts
                        if len(audio_buffer) < MIN_AUDIO_BYTES:
                            audio_buffer.clear()
                            last_transcription_time = now
                            continue
                        transcript = await sarvam_handler.transcribe_from_payload(audio_buffer)
                        if isinstance(transcript, tuple):
                            transcript_text, detected_language = transcript
                            # Update the detected language if it was determined during transcription
                            if detected_language and detected_language != "en-IN":
                                call_detected_lang = detected_language
                                logger.websocket.info(f"🌐 Language updated from transcription: {call_detected_lang}")
                            transcript = transcript_text
                        elif isinstance(transcript, str):
                            # Fallback for older handler compatibility
                            pass
                        else:
                            transcript = ""
                        logger.websocket.info(f"📝 Transcript: {transcript}")
                        logger.log_call_event("TRANSCRIPT_RECEIVED", call_sid, customer_info['name'], {"transcript": transcript, "stage": conversation_stage})

                        if transcript:
                            if conversation_stage == "WAITING_FOR_CONFIRMATION":
                                # FIXED: User responded to initial greeting - process confirmation and detect language
                                user_detected_lang = detect_language(transcript)
                                logger.websocket.info(f"🎯 User Confirmation Response:")
                                logger.websocket.info(f"   📍 State-mapped language: {initial_greeting_language}")  
                                logger.websocket.info(f"   🗣️  User response language: {user_detected_lang}")
                                logger.websocket.info(f"   💬 User said: '{transcript}'")
                                logger.log_call_event("USER_CONFIRMATION_RECEIVED", call_sid, customer_info['name'], {
                                    "transcript": transcript,
                                    "detected_lang": user_detected_lang,
                                    "initial_lang": initial_greeting_language
                                })
                                
                                # Set final language and proceed to EMI details
                                call_detected_lang = user_detected_lang
                                logger.websocket.info(f"🎉 Final Conversation Language: {call_detected_lang}")
                                logger.log_call_event("FINAL_LANGUAGE_SET", call_sid, customer_info['name'], {"final_lang": call_detected_lang})
                                
                                # Now play EMI details since user has confirmed
                                try:
                                    logger.websocket.info(f"🎪 User confirmed - playing EMI details in {call_detected_lang}")
                                    await play_emi_details_part1(websocket, customer_info, call_detected_lang)
                                    await play_emi_details_part2(websocket, customer_info, call_detected_lang)
                                    await play_agent_connect_question(websocket, call_detected_lang)
                                    conversation_stage = "WAITING_AGENT_RESPONSE"
                                    logger.websocket.info(f"✅ EMI details and agent question sent successfully")
                                    logger.websocket.info(f"🎯 CONVERSATION STAGE SET TO: WAITING_AGENT_RESPONSE - Now waiting for user response to agent connect question")
                                    logger.log_call_event("EMI_DETAILS_SENT", call_sid, customer_info['name'], {"language": call_detected_lang})
                                    # Clear audio buffer to ensure fresh start for agent response detection
                                    audio_buffer.clear()
                                    last_transcription_time = time.time()
                                except Exception as e:
                                    logger.websocket.error(f"❌ Error playing EMI details: {e}")
                                    logger.log_call_event("EMI_DETAILS_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                            
                            elif conversation_stage == "WAITING_FOR_LANG_DETECT":
                                # Detect user's preferred language from their response
                                user_detected_lang = detect_language(transcript)
                                logger.websocket.info(f"🎯 User Response Language Detection:")
                                logger.websocket.info(f"   📍 State-mapped language: {initial_greeting_language}")
                                logger.websocket.info(f"   🗣️  User detected language: {user_detected_lang}")
                                logger.websocket.info(f"   📄 CSV language: {csv_language}")
                                logger.log_call_event("LANGUAGE_DETECTED", call_sid, customer_info['name'], {
                                    "detected_lang": user_detected_lang, 
                                    "state_lang": initial_greeting_language,
                                    "csv_lang": csv_language,
                                    "transcript": transcript
                                })
                                
                                # Enhanced Language Switching Logic
                                if user_detected_lang != initial_greeting_language:
                                    logger.websocket.info(f"🔄 Language Mismatch Detected!")
                                    logger.websocket.info(f"   Initial greeting was in: {initial_greeting_language}")
                                    logger.websocket.info(f"   User responded in: {user_detected_lang}")
                                    logger.websocket.info(f"   🔄 Switching entire conversation to: {user_detected_lang}")
                                    logger.log_call_event("LANGUAGE_SWITCH_DETECTED", call_sid, customer_info['name'], {
                                        "from_lang": initial_greeting_language,
                                        "to_lang": user_detected_lang,
                                        "reason": "user_preference"
                                    })
                                    
                                    # Replay greeting in user's preferred language
                                    try:
                                        logger.websocket.info(f"🔁 Replaying greeting in user's language: {user_detected_lang}")
                                        await greeting_template_play(websocket, customer_info, lang=user_detected_lang)
                                        logger.websocket.info(f"✅ Successfully replayed greeting in {user_detected_lang}")
                                        logger.log_call_event("GREETING_REPLAYED_NEW_LANG", call_sid, customer_info['name'], {"new_lang": user_detected_lang})
                                        
                                        # Update the conversation language to user's preference
                                        call_detected_lang = user_detected_lang
                                        
                                        # Give user a moment to acknowledge the language switch
                                        await asyncio.sleep(1)
                                        
                                    except Exception as e:
                                        logger.websocket.error(f"❌ Error replaying greeting in {user_detected_lang}: {e}")
                                        logger.log_call_event("GREETING_REPLAY_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                                        # Fallback to user's detected language anyway
                                        call_detected_lang = user_detected_lang
                                        
                                else:
                                    logger.websocket.info(f"✅ Language Consistency Confirmed!")
                                    logger.websocket.info(f"   User responded in same language as greeting: {user_detected_lang}")
                                    logger.log_call_event("LANGUAGE_CONSISTENT", call_sid, customer_info['name'], {"language": user_detected_lang})
                                    call_detected_lang = user_detected_lang
                                
                                # Final language confirmation
                                logger.websocket.info(f"🎉 Final Conversation Language: {call_detected_lang}")
                                logger.log_call_event("FINAL_LANGUAGE_SET", call_sid, customer_info['name'], {"final_lang": call_detected_lang})
                                
                                # Play EMI details in final determined language
                                try:
                                    await play_emi_details_part1(websocket, customer_info or {}, call_detected_lang)
                                    await play_emi_details_part2(websocket, customer_info or {}, call_detected_lang)
                                    await play_agent_connect_question(websocket, call_detected_lang)
                                    conversation_stage = "WAITING_AGENT_RESPONSE"
                                    logger.tts.info(f"✅ EMI details and agent question sent successfully in {call_detected_lang}")
                                    logger.websocket.info(f"🎯 CONVERSATION STAGE SET TO: WAITING_AGENT_RESPONSE - Now waiting for user response to agent connect question")
                                    logger.log_call_event("EMI_DETAILS_SENT", call_sid, customer_info['name'], {"language": call_detected_lang})
                                    # Clear audio buffer to ensure fresh start for agent response detection
                                    audio_buffer.clear()
                                    last_transcription_time = time.time()
                                except Exception as e:
                                    logger.tts.error(f"❌ Error playing EMI details: {e}")
                                    logger.log_call_event("EMI_DETAILS_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                            
                            elif conversation_stage == "WAITING_AGENT_RESPONSE":
                                # ⚠️ CRITICAL: Validate transcript before intent detection to prevent false agent transfers
                                transcript_clean = transcript.strip()
                                
                                # Skip intent detection for empty, too short, or invalid transcripts
                                if not transcript_clean or len(transcript_clean) < 2:
                                    logger.websocket.info(f"🚫 Skipping intent detection - transcript too short: '{transcript_clean}'")
                                    logger.log_call_event("TRANSCRIPT_TOO_SHORT", call_sid, customer_info['name'], {"transcript": transcript_clean, "length": len(transcript_clean)})
                                    audio_buffer.clear()
                                    last_transcription_time = now
                                    continue
                                
                                # Additional validation: Check for meaningful content (at least one alphabetic character)
                                if not any(c.isalpha() for c in transcript_clean):
                                    logger.websocket.info(f"🚫 Skipping intent detection - no alphabetic content: '{transcript_clean}'")
                                    logger.log_call_event("TRANSCRIPT_NO_LETTERS", call_sid, customer_info['name'], {"transcript": transcript_clean})
                                    audio_buffer.clear()
                                    last_transcription_time = now
                                    continue
                                
                                logger.websocket.info(f"🎯 Processing valid transcript for intent: '{transcript_clean}'")
                                
                                # Use Claude for intent detection
                                try:
                                    intent = detect_intent_with_claude(transcript_clean, call_detected_lang)
                                    logger.websocket.info(f"Claude detected intent: {intent}")
                                    logger.log_call_event("INTENT_DETECTED_CLAUDE", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript_clean})
                                except Exception as e:
                                    logger.websocket.error(f"❌ Error in Claude intent detection: {e}")
                                    # Fallback to keyword-based detection
                                    intent = detect_intent_fur(transcript_clean, call_detected_lang)
                                    logger.websocket.info(f"Fallback intent detection: {intent}")
                                    logger.log_call_event("INTENT_DETECTED_FALLBACK", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript_clean})

                                # 🛡️ STRICT INTENT HANDLING - Only process clear, confident intents
                                if intent == "affirmative" or intent == "agent_transfer":
                                    if conversation_stage != "TRANSFERRING_TO_AGENT":  # Prevent multiple transfers
                                        logger.websocket.info(f"✅ CONFIRMED: User affirmed agent transfer. Intent: {intent}, Transcript: '{transcript_clean}'")
                                        logger.log_call_event("AGENT_TRANSFER_INITIATED", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript_clean})
                                        customer_number = customer_info.get('phone', '08438019383') if customer_info else "08438019383"
                                        await play_transfer_to_agent(websocket, customer_number=customer_number) 
                                        conversation_stage = "TRANSFERRING_TO_AGENT"
                                        interaction_complete = True
                                        # Wait for a moment before closing to ensure transfer message is sent
                                        await asyncio.sleep(2)
                                        break
                                    else:
                                        logger.websocket.warning("⚠️ Agent transfer already in progress, ignoring duplicate request")
                                elif intent == "negative":
                                    if conversation_stage != "GOODBYE_DECLINE":  # Prevent multiple goodbyes
                                        logger.websocket.info(f"✅ CONFIRMED: User declined agent transfer. Intent: {intent}, Transcript: '{transcript_clean}'")
                                        logger.log_call_event("AGENT_TRANSFER_DECLINED", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript_clean})
                                        await play_goodbye_after_decline(websocket, call_detected_lang)
                                        conversation_stage = "GOODBYE_DECLINE"
                                        interaction_complete = True
                                        # Wait for goodbye message to be sent before closing
                                        await asyncio.sleep(3)
                                        break
                                    else:
                                        logger.websocket.warning("⚠️ Goodbye already sent, ignoring duplicate request")
                                elif intent == "confused":
                                    # User seems confused, repeat the question
                                    logger.websocket.info(f"🔄 User seems confused. Repeating agent question. Transcript: '{transcript_clean}'")
                                    logger.log_call_event("AGENT_QUESTION_CONFUSED_REPEAT", call_sid, customer_info['name'], {"transcript": transcript_clean})
                                    await play_agent_connect_question(websocket, call_detected_lang)
                                    last_transcription_time = time.time()
                                elif intent == "unclear" or intent == "unknown":
                                    # Handle unclear responses more carefully
                                    agent_question_repeat_count += 1
                                    logger.websocket.info(f"⚠️ Unclear response '{transcript_clean}' (intent: {intent}). Attempt {agent_question_repeat_count}/2")
                                    
                                    if agent_question_repeat_count <= 2:  # Limit to 2 repeats
                                        logger.websocket.info(f"🔄 Repeating agent question due to unclear response (attempt {agent_question_repeat_count}/2).")
                                        logger.log_call_event("AGENT_QUESTION_UNCLEAR_REPEAT", call_sid, customer_info['name'], {"attempt": agent_question_repeat_count, "transcript": transcript_clean, "intent": intent})
                                        await play_agent_connect_question(websocket, call_detected_lang)
                                        # Reset the timer to wait for user response
                                        last_transcription_time = time.time()
                                    else:
                                        logger.websocket.info("Too many unclear responses. Assuming user wants agent transfer.")
                                        logger.log_call_event("AUTO_AGENT_TRANSFER_UNCLEAR", call_sid, customer_info['name'])
                                        customer_number = customer_info.get('phone', '08438019383') if customer_info else "08438019383"
                                        await play_transfer_to_agent(websocket, customer_number=customer_number) 
                                        conversation_stage = "TRANSFERRING_TO_AGENT"
                                        interaction_complete = True
                                        # Wait for transfer message to be sent before closing
                                        await asyncio.sleep(2)
                                        break
                            # Add more elif conditions here for additional conversation stages if your flow extends
                    except Exception as e:
                        logger.websocket.error(f"❌ Error processing transcript: {e}")
                        logger.log_call_event("TRANSCRIPT_PROCESSING_ERROR", call_sid, customer_info['name'] if customer_info else 'Unknown', {"error": str(e)})

                    audio_buffer.clear()
                    last_transcription_time = now

    except Exception as e:
        logger.error(f"WebSocket compatibility error: {e}")
        logger.log_call_event("WEBSOCKET_COMPATIBILITY_ERROR", call_sid or 'unknown', customer_info['name'] if customer_info else 'Unknown', {"error": str(e)})
    finally:
        # Ensure the websocket is closed gracefully only after conversation is complete
        try:
            if not interaction_complete:
                # If we're exiting due to an error before conversation completion, wait a bit
                await asyncio.sleep(1)
            
            if websocket.client_state.name not in ['DISCONNECTED']:
                await websocket.close()
                logger.websocket.info("🔒 WebSocket connection closed gracefully")
            else:
                logger.websocket.info("🔒 WebSocket already disconnected")
        except Exception as close_error:
            logger.error(f"Error closing WebSocket: {close_error}")
        logger.log_call_event("WEBSOCKET_CLOSED_GRACEFUL", call_sid or 'unknown', customer_info['name'] if customer_info else 'Unknown')


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
    Requires authentication.
    """
    print(f"🚀 [CHECKPOINT] /api/trigger-single-call endpoint hit by user: testing-mode")
    print(f"🚀 [CHECKPOINT] Customer ID: {customer_id}")
    
    try:
        result = await call_service.trigger_single_call(customer_id)
        print(f"🚀 [CHECKPOINT] Call service result: {result}")
        
        # Log the action with user information
        logger.info(f"User testing-mode triggered single call for customer: {customer_id}")
        
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in trigger_single_call endpoint: {e}")
        logger.error(f"Trigger single call error for user testing-mode: {str(e)}")
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

# This is a catch-all for the old websocket endpoint, redirecting or handling as needed.
@app.websocket("/stream")
async def old_websocket_endpoint(websocket: WebSocket):
    """
    Handles the old /stream endpoint.
    For backward compatibility, we'll redirect this to the new voicebot endpoint.
    """
    await websocket.accept()
    print("[Compatibility] Old /stream endpoint connected. Using voicebot logic...")
    
    # Initialize variables - we'll get the real CallSid from the start message
    query_params = dict(websocket.query_params)
    temp_call_id = query_params.get('temp_call_id')
    call_sid = query_params.get('call_sid')
    phone = query_params.get('phone')
    
    print(f"[Compatibility] Initial query params: temp_call_id={temp_call_id}, call_sid={call_sid}, phone={phone}")
    
    # State variable for the conversation stage
    conversation_stage = "WAITING_FOR_START" # Wait for the start message to get CallSid
    call_detected_lang = "en-IN" # Default language, will be updated after first user response
    audio_buffer = bytearray()
    last_transcription_time = time.time()
    interaction_complete = False # Flag to stop processing media after the main flow ends
    customer_info = None # Will be set when we get customer data
    initial_greeting_played = False # Track if initial greeting was played
    agent_question_repeat_count = 0 # Track how many times agent question was repeated
    emi_delivery_in_progress = False # Flag to prevent premature WebSocket closure during EMI delivery
    session_id = None # Will be set from the start message
    
    # Call timeout mechanism
    call_start_time = time.time()
    max_call_duration = 600  # 10 minutes maximum call duration
    
    try:
        while True:
            # Check for call timeout
            if time.time() - call_start_time > max_call_duration:
                logger.websocket.warning(f"⏰ Call timeout reached ({max_call_duration}s) - ending call gracefully")
                logger.log_call_event("CALL_TIMEOUT", call_sid or 'unknown', customer_info['name'] if customer_info else 'Unknown')
                if customer_info and not interaction_complete:
                    # Play a quick timeout message
                    try:
                        timeout_msg = GOODBYE_TEMPLATE.get(call_detected_lang, GOODBYE_TEMPLATE["en-IN"])
                        audio_bytes = await sarvam_handler.synthesize_tts(timeout_msg, call_detected_lang)
                        await stream_audio_to_websocket(websocket, audio_bytes)
                        await asyncio.sleep(2)  # Wait for message to play
                    except Exception as e:
                        logger.tts.error(f"❌ Error playing timeout message: {e}")
                interaction_complete = True
                break
            data = await websocket.receive_text()
            msg = json.loads(data)
            event_type = msg.get('event', 'unknown')
            
            # Log WebSocket message using the new logging system
            logger.websocket.info(f"📨 Received message: {event_type}")
            logger.log_websocket_message(event_type, msg, call_sid=call_sid, session_id=session_id)
            
            # Debug: Log complete message for troubleshooting
            logger.websocket.debug(f"🔍 FULL MESSAGE DEBUG: {json.dumps(msg, indent=2)}")

            if msg.get("event") == "start":
                logger.websocket.info("🔁 Got start event - extracting CallSid and customer data")
                logger.log_call_event("START_MESSAGE_RECEIVED", call_sid or "unknown")
                
                # Debug: Log the full start message to see what Exotel is actually sending
                logger.websocket.debug(f"🔍 FULL START MESSAGE DEBUG: {json.dumps(msg, indent=2)}")
                
                # Extract CallSid from the start message - this is how Exotel sends it
                call_sid = None
                # CRITICAL: Check the nested start structure first - this is where Exotel actually sends it
                if 'start' in msg and 'call_sid' in msg['start']:
                    call_sid = msg['start']['call_sid']  # CRITICAL: This is where Exotel sends it!
                    logger.websocket.info(f"🎯 FOUND CallSid in start.call_sid: {call_sid}")
                elif 'start' in msg and 'callSid' in msg['start']:
                    call_sid = msg['start']['callSid']
                    logger.websocket.info(f"🎯 FOUND CallSid in start.callSid: {call_sid}")
                elif 'callSid' in msg:
                    call_sid = msg['callSid']
                elif 'CallSid' in msg:
                    call_sid = msg['CallSid']
                elif 'call_sid' in msg:
                    call_sid = msg['call_sid']
                elif 'streamSid' in msg:
                    call_sid = msg['streamSid']
                elif 'stream' in msg and 'callSid' in msg['stream']:
                    call_sid = msg['stream']['callSid']
                
                # Debug: Check all possible locations for CallSid
                logger.websocket.debug("🔍 Checking for CallSid in message fields:")
                logger.websocket.debug(f"🔍 msg.get('callSid'): {msg.get('callSid')}")
                logger.websocket.debug(f"🔍 msg.get('CallSid'): {msg.get('CallSid')}")
                logger.websocket.debug(f"🔍 msg.get('call_sid'): {msg.get('call_sid')}")
                logger.websocket.debug(f"🔍 msg.get('streamSid'): {msg.get('streamSid')}")
                logger.websocket.debug(f"🔍 msg.get('stream'): {msg.get('stream')}")
                logger.websocket.debug(f"🔍 msg.get('start'): {msg.get('start')}")
                logger.websocket.debug(f"🔍 All msg keys: {list(msg.keys())}")
                
                logger.websocket.info(f"✅ Extracted CallSid from start message: {call_sid}")
                
                # Use CallSid as session_id
                session_id = call_sid or generate_websocket_session_id()
                
                logger.websocket.info(f"Using session_id: {session_id}")
                
                # Now that we have the CallSid, try to get customer info from multiple sources
                if not customer_info:
                    # 1. Try to get from Redis using CallSid
                    if call_sid:
                        logger.database.info(f"Looking up customer data by CallSid: {call_sid}")
                        redis_data = redis_manager.get_call_session(call_sid)
                        if redis_data:
                            customer_info = {
                                'name': redis_data.get('name'),
                                'loan_id': redis_data.get('loan_id'),
                                'amount': redis_data.get('amount'),
                                'due_date': redis_data.get('due_date'),
                                'lang': redis_data.get('language_code', 'en-IN'),
                                'phone': redis_data.get('phone_number', ''),
                                'state': redis_data.get('state', '')
                            }
                            logger.database.info(f"✅ Found customer data in Redis: {customer_info['name']}")
                            logger.log_call_event("CUSTOMER_DATA_FOUND_REDIS", call_sid, customer_info['name'], customer_info)
                    
                    # 2. Try to get customer data from database by CallSid
                    if not customer_info and call_sid:
                        logger.database.info(f"Looking up call session in database by CallSid: {call_sid}")
                        try:
                            session_db = db_manager.get_session()
                            call_session = get_call_session_by_sid(session_db, call_sid)
                            if call_session and call_session.customer_id:
                                # Get customer from database
                                customer = session_db.query(Customer).filter(Customer.id == call_session.customer_id).first()
                                if customer:
                                    customer_info = {
                                        'name': customer.name,
                                        'loan_id': customer.loan_id,
                                        'amount': customer.amount,
                                        'due_date': customer.due_date,
                                        'lang': customer.language_code or 'en-IN',
                                        'phone': customer.phone_number,
                                        'state': customer.state or ''
                                    }
                                    logger.database.info(f"✅ Found customer in database: {customer_info['name']}")
                                    logger.log_call_event("CUSTOMER_DATA_FOUND_DATABASE", call_sid, customer_info['name'], customer_info)
                            session_db.close()
                        except Exception as e:
                            logger.database.error(f"❌ Error looking up customer in database: {e}")
                
                # 3. If no customer found, this is an error
                if not customer_info:
                    logger.database.error("❌ No customer data found - cannot proceed without real customer information")
                    logger.log_call_event("CUSTOMER_DATA_NOT_FOUND", call_sid)
                    await websocket.send_text(json.dumps({
                        "event": "error",
                        "message": "Customer data not found. Please ensure customer information is uploaded and call is triggered properly."
                    }))
                    return
                
                # 4. Validate customer data has required fields (allow placeholder values)
                required_fields = ['name', 'loan_id', 'amount', 'due_date']
                missing_fields = [field for field in required_fields if not customer_info.get(field) or customer_info.get(field) in ['None', 'null', 'undefined']]
                if missing_fields:
                    logger.database.error(f"❌ Customer data missing required fields: {missing_fields}")
                    logger.log_call_event("CUSTOMER_DATA_INCOMPLETE", call_sid, customer_info['name'] if customer_info else 'Unknown', {"missing_fields": missing_fields})
                    await websocket.send_text(json.dumps({
                        "event": "error",
                        "message": f"Customer data incomplete. Missing fields: {', '.join(missing_fields)}"
                    }))
                    return

                # Convert placeholder values to generic terms for speech
                if customer_info.get('loan_id') in ['Unknown', 'N/A', None, 'None', 'null']:
                    customer_info['loan_id'] = '1234'  # Generic loan ID for speech
                if customer_info.get('amount') in ['Unknown', 'N/A', '₹0', None, 'None', 'null']:
                    customer_info['amount'] = '5000'  # Generic amount for speech
                if customer_info.get('due_date') in ['Unknown', 'N/A', None, 'None', 'null']:
                    customer_info['due_date'] = 'this month'  # Generic due date for speech                print(f"[Compatibility] ✅ Customer data validated: {customer_info['name']} - Loan: {customer_info['loan_id']}, Amount: ₹{customer_info['amount']}")
                
                # Initialize language variables for enhanced language detection
                csv_language = customer_info.get('lang', 'en-IN')
                state_language = get_initial_language_from_state(customer_info.get('state', ''))
                initial_greeting_language = csv_language if csv_language and csv_language != 'en-IN' else state_language
                call_detected_lang = initial_greeting_language
                
                logger.websocket.info(f"🌐 Language Configuration:")
                logger.websocket.info(f"   📄 CSV Language: {csv_language}")
                logger.websocket.info(f"   📍 State Language: {state_language}")
                logger.websocket.info(f"   🎯 Initial Greeting Language: {initial_greeting_language}")
                
                # Play initial greeting immediately when WebSocket starts
                logger.tts.info(f"1. Playing initial greeting for {customer_info['name']} in {initial_greeting_language}")
                logger.log_call_event("INITIAL_GREETING_START", call_sid, customer_info['name'], {"language": initial_greeting_language})
                try:
                    await greeting_template_play(websocket, customer_info, lang=initial_greeting_language)
                    logger.tts.info(f"✅ Initial greeting played successfully in {initial_greeting_language}")
                    logger.log_call_event("INITIAL_GREETING_SUCCESS", call_sid, customer_info['name'], {"language": initial_greeting_language})
                    initial_greeting_played = True
                    conversation_stage = "WAITING_FOR_LANG_DETECT"
                except Exception as e:
                    logger.tts.error(f"❌ Error playing initial greeting: {e}")
                    logger.log_call_event("INITIAL_GREETING_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                    # Try fallback simple greeting
                    try:
                        simple_greeting = f"Hello, this is South India Finvest Bank calling. Am I speaking with {customer_info['name']}?"
                        audio_bytes = await sarvam_handler.synthesize_tts(simple_greeting, "en-IN")
                        await stream_audio_to_websocket(websocket, audio_bytes)
                        logger.tts.info("✅ Fallback greeting sent successfully")
                        logger.log_call_event("FALLBACK_GREETING_SUCCESS", call_sid, customer_info['name'])
                        initial_greeting_played = True
                        conversation_stage = "WAITING_FOR_LANG_DETECT"
                    except Exception as fallback_e:
                        logger.tts.error(f"❌ Error sending fallback greeting: {fallback_e}")
                        logger.log_call_event("FALLBACK_GREETING_ERROR", call_sid, customer_info['name'], {"error": str(fallback_e)})
                continue

            if msg.get("event") == "stop":
                logger.websocket.info("🛑 Received stop event from Twilio/Exotel")
                # Don't break the loop immediately - only if conversation is complete
                if interaction_complete:
                    logger.websocket.info("✅ Conversation already complete, processing stop event")
                    break
                else:
                    logger.websocket.info("⚠️ Stop event received but conversation not complete - ignoring for now")
                    # Log the stop event but continue processing
                    logger.log_call_event("STOP_EVENT_IGNORED", call_sid, customer_info['name'] if customer_info else 'Unknown', 
                                        {"reason": "conversation_not_complete", "stage": conversation_stage})
                    continue

            if msg.get("event") == "media":
                payload_b64 = msg["media"]["payload"]
                raw_audio = base64.b64decode(payload_b64)

                if interaction_complete:
                    continue

                if raw_audio and any(b != 0 for b in raw_audio):
                    audio_buffer.extend(raw_audio)
                
                now = time.time()

                if now - last_transcription_time >= BUFFER_DURATION_SECONDS:
                    if len(audio_buffer) == 0:
                        if conversation_stage == "WAITING_FOR_LANG_DETECT":
                            logger.websocket.info("No audio received during language detection stage. Playing 'didn't hear' prompt.")
                            logger.log_call_event("NO_AUDIO_LANG_DETECT", call_sid, customer_info['name'])
                            await play_did_not_hear_response(websocket, call_detected_lang)
                            last_transcription_time = time.time()
                        elif conversation_stage == "WAITING_AGENT_RESPONSE":
                            agent_question_repeat_count += 1
                            if agent_question_repeat_count <= 3:  # Increased to 3 repeats for better user experience
                                logger.websocket.info(f"No audio received during agent question stage. Repeating question (attempt {agent_question_repeat_count}/3).")
                                logger.log_call_event("AGENT_QUESTION_REPEAT", call_sid, customer_info['name'], {"attempt": agent_question_repeat_count})
                                await play_agent_connect_question(websocket, call_detected_lang)
                                last_transcription_time = time.time()
                            else:
                                # After 3 attempts with no response, play a clarifying message and try once more
                                logger.websocket.info("No clear response after 3 attempts. Playing clarification message.")
                                logger.log_call_event("AGENT_QUESTION_CLARIFICATION", call_sid, customer_info['name'])
                                
                                # Play clarifying message asking for clear yes/no response
                                clarification_msg = {
                                    "en-IN": "Please say 'yes' if you want to speak to an agent, or 'no' if you don't need assistance.",
                                    "hi-IN": "कृपया 'हां' कहें यदि आप एजेंट से बात करना चाहते हैं, या 'नहीं' कहें यदि आपको सहायता की आवश्यकता नहीं है।",
                                    "ta-IN": "நீங்கள் ஒரு முகவரிடம் பேச விரும்பினால் 'ஆம்' என்று சொல்லுங்கள், அல்லது உங்களுக்கு உதவி தேவையில்லை என்றால் 'இல்லை' என்று சொல்லுங்கள்।"
                                }
                                clarify_text = clarification_msg.get(call_detected_lang, clarification_msg["en-IN"])
                                audio_bytes = await sarvam_handler.synthesize_tts(clarify_text, call_detected_lang)
                                await stream_audio_to_websocket(websocket, audio_bytes)
                                
                                # Reset counter for final attempt
                                agent_question_repeat_count = 0
                                last_transcription_time = time.time()
                        audio_buffer.clear()
                        last_transcription_time = now
                        continue

                    try:
                        transcript = await sarvam_handler.transcribe_from_payload(audio_buffer)
                        if isinstance(transcript, tuple):
                            transcript_text, detected_language = transcript
                            if detected_language and detected_language != "en-IN":
                                call_detected_lang = detected_language
                                logger.websocket.info(f"🌐 Language updated from transcription: {call_detected_lang}")
                            transcript = transcript_text
                        elif isinstance(transcript, str):
                            pass
                        else:
                            transcript = ""
                        
                        logger.websocket.info(f"📝 Transcript: {transcript}")
                        logger.log_call_event("TRANSCRIPT_RECEIVED", call_sid, customer_info['name'], {"transcript": transcript, "stage": conversation_stage})

                        if transcript:
                            if conversation_stage == "WAITING_FOR_LANG_DETECT":
                                # Detect user's preferred language from their response
                                user_detected_lang = detect_language(transcript)
                                logger.websocket.info(f"🎯 User Response Language Detection:")
                                logger.websocket.info(f"   📍 State-mapped language: {initial_greeting_language}")
                                logger.websocket.info(f"   🗣️  User detected language: {user_detected_lang}")
                                logger.websocket.info(f"   📄 CSV language: {csv_language}")
                                logger.log_call_event("LANGUAGE_DETECTED", call_sid, customer_info['name'], {
                                    "detected_lang": user_detected_lang, 
                                    "state_lang": initial_greeting_language,
                                    "csv_lang": csv_language,
                                    "transcript": transcript
                                })
                                
                                # Enhanced Language Switching Logic
                                if user_detected_lang != initial_greeting_language:
                                    logger.websocket.info(f"🔄 Language Mismatch Detected!")
                                    logger.websocket.info(f"   Initial greeting was in: {initial_greeting_language}")
                                    logger.websocket.info(f"   User responded in: {user_detected_lang}")
                                    logger.websocket.info(f"   🔄 Switching entire conversation to: {user_detected_lang}")
                                    logger.log_call_event("LANGUAGE_SWITCH_DETECTED", call_sid, customer_info['name'], {
                                        "from_lang": initial_greeting_language,
                                        "to_lang": user_detected_lang,
                                        "reason": "user_preference"
                                    })
                                    
                                    # Replay greeting in user's preferred language
                                    try:
                                        logger.websocket.info(f"🔁 Replaying greeting in user's language: {user_detected_lang}")
                                        await greeting_template_play(websocket, customer_info, lang=user_detected_lang)
                                        logger.websocket.info(f"✅ Successfully replayed greeting in {user_detected_lang}")
                                        logger.log_call_event("GREETING_REPLAYED_NEW_LANG", call_sid, customer_info['name'], {"new_lang": user_detected_lang})
                                        
                                        # Update the conversation language to user's preference
                                        call_detected_lang = user_detected_lang
                                        
                                        # Give user a moment to acknowledge the language switch
                                        await asyncio.sleep(1)
                                        
                                    except Exception as e:
                                        logger.websocket.error(f"❌ Error replaying greeting in {user_detected_lang}: {e}")
                                        logger.log_call_event("GREETING_REPLAY_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                                        # Fallback to user's detected language anyway
                                        call_detected_lang = user_detected_lang
                                        
                                else:
                                    logger.websocket.info(f"✅ Language Consistency Confirmed!")
                                    logger.websocket.info(f"   User responded in same language as greeting: {user_detected_lang}")
                                    logger.log_call_event("LANGUAGE_CONSISTENT", call_sid, customer_info['name'], {"language": user_detected_lang})
                                    call_detected_lang = user_detected_lang
                                
                                # Final language confirmation
                                logger.websocket.info(f"🎉 Final Conversation Language: {call_detected_lang}")
                                logger.log_call_event("FINAL_LANGUAGE_SET", call_sid, customer_info['name'], {"final_lang": call_detected_lang})
                                
                                try:
                                    await play_emi_details_part1(websocket, customer_info or {}, call_detected_lang)
                                    await play_emi_details_part2(websocket, customer_info or {}, call_detected_lang)
                                    await play_agent_connect_question(websocket, call_detected_lang)
                                    conversation_stage = "WAITING_AGENT_RESPONSE"
                                    logger.tts.info(f"✅ EMI details and agent question sent successfully in {call_detected_lang}")
                                    logger.websocket.info(f"🎯 CONVERSATION STAGE SET TO: WAITING_AGENT_RESPONSE - Now waiting for user response to agent connect question")
                                    logger.log_call_event("EMI_DETAILS_SENT", call_sid, customer_info['name'], {"language": call_detected_lang})
                                    # Clear audio buffer to ensure fresh start for agent response detection
                                    audio_buffer.clear()
                                    last_transcription_time = time.time()
                                except Exception as e:
                                    logger.tts.error(f"❌ Error playing EMI details: {e}")
                                    logger.log_call_event("EMI_DETAILS_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                            
                            elif conversation_stage == "WAITING_AGENT_RESPONSE":
                                # ⚠️ CRITICAL: Validate transcript before intent detection to prevent false agent transfers
                                transcript_clean = transcript.strip()
                                
                                # Skip intent detection for empty, too short, or invalid transcripts
                                if not transcript_clean or len(transcript_clean) < 2:
                                    logger.websocket.info(f"🚫 Skipping intent detection - transcript too short: '{transcript_clean}'")
                                    logger.log_call_event("TRANSCRIPT_TOO_SHORT", call_sid, customer_info['name'], {"transcript": transcript_clean, "length": len(transcript_clean)})
                                    audio_buffer.clear()
                                    last_transcription_time = now
                                    continue
                                
                                # Additional validation: Check for meaningful content (at least one alphabetic character)
                                if not any(c.isalpha() for c in transcript_clean):
                                    logger.websocket.info(f"🚫 Skipping intent detection - no alphabetic content: '{transcript_clean}'")
                                    logger.log_call_event("TRANSCRIPT_NO_LETTERS", call_sid, customer_info['name'], {"transcript": transcript_clean})
                                    audio_buffer.clear()
                                    last_transcription_time = now
                                    continue
                                
                                logger.websocket.info(f"🎯 Processing valid transcript for intent: '{transcript_clean}'")
                                
                                try:
                                    intent = detect_intent_with_claude(transcript_clean, call_detected_lang)
                                    logger.websocket.info(f"Claude detected intent: {intent}")
                                    logger.log_call_event("INTENT_DETECTED_CLAUDE", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript_clean})
                                except Exception as e:
                                    logger.websocket.error(f"❌ Error in Claude intent detection: {e}")
                                    intent = detect_intent_fur(transcript_clean, call_detected_lang)
                                    logger.websocket.info(f"Fallback intent detection: {intent}")
                                    logger.log_call_event("INTENT_DETECTED_FALLBACK", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript_clean})

                                # 🛡️ STRICT INTENT HANDLING - Only process clear, confident intents
                                if intent == "affirmative" or intent == "agent_transfer":
                                    if conversation_stage != "TRANSFERRING_TO_AGENT":
                                        logger.websocket.info(f"✅ CONFIRMED: User affirmed agent transfer. Intent: {intent}, Transcript: '{transcript_clean}'")
                                        logger.log_call_event("AGENT_TRANSFER_INITIATED", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript_clean})
                                        customer_number = customer_info.get('phone', '08438019383') if customer_info else "08438019383"
                                        await play_transfer_to_agent(websocket, customer_number=customer_number) 
                                        conversation_stage = "TRANSFERRING_TO_AGENT"
                                        interaction_complete = True
                                        await asyncio.sleep(2)
                                        break
                                    else:
                                        logger.websocket.warning("⚠️ Agent transfer already in progress, ignoring duplicate request")
                                elif intent == "negative":
                                    if conversation_stage != "GOODBYE_DECLINE":
                                        logger.websocket.info(f"✅ CONFIRMED: User declined agent transfer. Intent: {intent}, Transcript: '{transcript_clean}'")
                                        logger.log_call_event("AGENT_TRANSFER_DECLINED", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript_clean})
                                        await play_goodbye_after_decline(websocket, call_detected_lang)
                                        conversation_stage = "GOODBYE_DECLINE"
                                        interaction_complete = True
                                        await asyncio.sleep(3)
                                        break
                                    else:
                                        logger.websocket.warning("⚠️ Goodbye already sent, ignoring duplicate request")
                                elif intent == "confused":
                                    # User seems confused, repeat the question
                                    logger.websocket.info(f"🔄 User seems confused. Repeating agent question. Transcript: '{transcript_clean}'")
                                    logger.log_call_event("AGENT_QUESTION_CONFUSED_REPEAT", call_sid, customer_info['name'], {"transcript": transcript_clean})
                                    await play_agent_connect_question(websocket, call_detected_lang)
                                    last_transcription_time = time.time()
                                elif intent == "unclear" or intent == "unknown":
                                    # Handle unclear responses more carefully
                                    agent_question_repeat_count += 1
                                    logger.websocket.info(f"⚠️ Unclear response '{transcript_clean}' (intent: {intent}). Attempt {agent_question_repeat_count}/2")
                                    
                                    if agent_question_repeat_count <= 2:  # Limit to 2 repeats
                                        logger.websocket.info(f"🔄 Repeating agent question due to unclear response (attempt {agent_question_repeat_count}/2).")
                                        logger.log_call_event("AGENT_QUESTION_UNCLEAR_REPEAT", call_sid, customer_info['name'], {"attempt": agent_question_repeat_count, "transcript": transcript_clean, "intent": intent})
                                        await play_agent_connect_question(websocket, call_detected_lang)
                                        # Reset the timer to wait for user response
                                        last_transcription_time = time.time()
                                    else:
                                        logger.websocket.warning("⚠️ Too many unclear responses. NOT automatically transferring - waiting for clear intent.")
                                        logger.log_call_event("MAX_UNCLEAR_RESPONSES_REACHED", call_sid, customer_info['name'], {"final_transcript": transcript_clean})
                                        # Reset counter and continue waiting instead of auto-transferring
                                        agent_question_repeat_count = 0
                                        await play_agent_connect_question(websocket, call_detected_lang)
                                        last_transcription_time = time.time()
                                else:
                                    # Catch any other unexpected intents
                                    logger.websocket.warning(f"⚠️ Unexpected intent '{intent}' for transcript '{transcript_clean}' - treating as unclear")
                                    agent_question_repeat_count += 1
                                    if agent_question_repeat_count <= 2:
                                        await play_agent_connect_question(websocket, call_detected_lang)
                                        last_transcription_time = time.time()
                    except Exception as e:
                        logger.websocket.error(f"❌ Error processing transcript: {e}")
                        logger.log_call_event("TRANSCRIPT_PROCESSING_ERROR", call_sid, customer_info['name'] if customer_info else 'Unknown', {"error": str(e)})

                    audio_buffer.clear()
                    last_transcription_time = now

    except Exception as e:
        logger.error(f"WebSocket compatibility error: {e}")
        logger.log_call_event("WEBSOCKET_COMPATIBILITY_ERROR", call_sid or 'unknown', customer_info['name'] if customer_info else 'Unknown', {"error": str(e)})
    finally:
        # Ensure the websocket is closed gracefully only after conversation is complete
        try:
            if not interaction_complete:
                # If we're exiting due to an error before conversation completion, wait a bit
                await asyncio.sleep(1)
            
            if websocket.client_state.name not in ['DISCONNECTED']:
                await websocket.close()
                logger.websocket.info("🔒 WebSocket connection closed gracefully")
            else:
                logger.websocket.info("🔒 WebSocket already disconnected")
        except Exception as close_error:
            logger.error(f"Error closing WebSocket: {close_error}")
        logger.log_call_event("WEBSOCKET_CLOSED_GRACEFUL", call_sid or 'unknown', customer_info['name'] if customer_info else 'Unknown')


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