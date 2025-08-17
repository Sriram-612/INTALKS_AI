# 🎙️ Voice Assistant Call Management System - Comprehensive Documentation

## 📋 System Overview
An advanced voice assistant application with comprehensive call management, multi-language support, Redis-based session handling, real-time status tracking, and PostgreSQL database integration for automated loan collection calls.

## 🚀 Core Features

### ✨ Enhanced Language Detection System
- **State-Based Initial Greeting**: Plays greeting in language mapped to customer's geographic state
- **User Language Detection**: Detects user's preferred language from their response
- **Automatic Language Switching**: If user responds in different language, replays greeting and continues entire conversation in user's preferred language
- **Comprehensive Language Support**: English, Hindi, Tamil, Telugu, Malayalam, Gujarati, Marathi, Bengali, Kannada, Punjabi, Odia

### 🔄 Advanced Call Management
- **Real-time Call Tracking**: Monitor calls from initiation to completion
- **Redis Session Management**: Robust session handling for parallel calls with unique CallSids
- **Database Integration**: PostgreSQL for persistent customer data and call history
- **Status Management**: Track call states (initiated, ringing, in-progress, agent transfer, completed, failed)
- **Agent Transfer**: Seamless handoff to human agents when needed

## 🗂️ Project Structure

```
voice/
├── main.py                     # Main FastAPI application with WebSocket endpoints
├── database/
│   ├── __init__.py
│   └── schemas.py              # Database models and connection management
├── services/
│   ├── __init__.py
│   └── call_management.py      # Call lifecycle management service
├── utils/
│   ├── __init__.py
│   ├── production_asr.py       # Sarvam TTS/STT handler with rate limiting
│   ├── logger.py              # Comprehensive logging system
│   ├── agent_transfer.py      # Exotel agent transfer functionality
│   ├── bedrock_client.py      # AWS Bedrock Claude integration
│   ├── redis_session.py       # Redis session management
│   └── connect_customer.py    # Customer call initiation
├── static/
│   ├── enhanced_dashboard.html # Main dashboard UI
│   └── index.html             # Original dashboard
├── logs/                      # Application logs directory
├── requirements.txt           # Python dependencies
├── .env                      # Environment configuration
└── README files...           # Documentation
```

## 🔌 WebSocket Endpoints & API Reference

### WebSocket Endpoints

| Endpoint | Purpose | Primary Use | Key Features |
|----------|---------|-------------|--------------|
| `/ws/voicebot/{session_id}` | **Main Voice Bot** | Real-time voice conversation | ✅ Enhanced language detection<br/>✅ Language switching<br/>✅ Full conversation flow |
| `/ws/voicebot-compatibility/{session_id}` | **Legacy Compatibility** | Backward compatibility | ✅ Basic conversation flow<br/>✅ Simple language detection |
| `/ws/dashboard/{websocket_id}` | **Dashboard Updates** | Real-time UI updates | ✅ Call status updates<br/>✅ Live statistics<br/>✅ Progress tracking |

### HTTP API Endpoints

| Method | Endpoint | Purpose | Request Body | Response |
|--------|----------|---------|---------------|----------|
| `GET` | `/` | **Main Dashboard** | - | HTML Dashboard |
| `GET` | `/original` | **Legacy Dashboard** | - | Original HTML Dashboard |
| `GET` | `/ws-url` | **WebSocket URL Generator** | Query params: `CallSid`, `CustomField`, `From` | WebSocket URL for Exotel |
| `POST` | `/passthru-handler` | **Exotel Passthru** | Exotel flow data | JSON response |
| `POST` | `/upload-customers` | **Bulk Customer Upload** | CSV/Excel file | Upload status |
| `POST` | `/trigger-call/{customer_id}` | **Single Call Trigger** | Customer ID | Call initiation status |
| `POST` | `/trigger-bulk-calls` | **Bulk Call Trigger** | `{"customer_ids": [...]}` | Bulk call status |
| `GET` | `/customers` | **Customer List** | - | JSON customer data |
| `PUT` | `/customers/{customer_id}/status` | **Update Call Status** | `{"status": "status"}` | Update confirmation |

## 🔄 Language Detection Flow

### Enhanced Language Detection Process

| Stage | Description | Action | Language Used |
|-------|-------------|--------|---------------|
| **1. Initial Greeting** | System plays greeting based on customer's state | `greeting_template_play()` | State-mapped language |
| **2. User Response** | User responds in their preferred language | `detect_language()` | Detect from speech |
| **3. Language Comparison** | Compare state language vs detected language | Enhanced logic | Analysis |
| **4. Language Switch (if needed)** | If different, replay greeting in user's language | `greeting_template_play()` | User's detected language |
| **5. Conversation Flow** | Continue entire conversation in final language | All templates | Final determined language |

### Language Detection Functions

| Function | Purpose | Input | Output | Dependencies |
|----------|---------|-------|--------|--------------|
| `detect_language()` | Detect language from transcript | `str` transcript | Language code (e.g., `en-IN`) | English word list, language patterns |
| `get_initial_language_from_state()` | Map state to language | State name | Default language for state | `STATE_TO_LANGUAGE` mapping |
| `greeting_template_play()` | Play greeting in specific language | Customer info, language | Audio output | `GREETING_TEMPLATE`, TTS |
| `play_emi_details_part1/2()` | Play EMI details | Customer info, language | Audio output | Template + TTS |
| `play_agent_connect_question()` | Ask about agent transfer | Language | Audio output | `AGENT_CONNECT_TEMPLATE` |

## 🎯 Conversation Flow States

| State | Description | Next States | Audio Played | User Input Expected |
|-------|-------------|-------------|--------------|-------------------|
| `INITIAL_GREETING` | Play welcome message | `WAITING_FOR_LANG_DETECT` | State-mapped greeting | User acknowledgment |
| `WAITING_FOR_LANG_DETECT` | Detect user's language | `WAITING_AGENT_RESPONSE` | Language switch replay (if needed) | Language preference confirmation |
| `PLAYING_EMI_PART1` | First EMI details | `PLAYING_EMI_PART2` | Loan amount, due date | - |
| `PLAYING_EMI_PART2` | EMI consequences | `ASKING_AGENT_CONNECT` | Credit score impact | - |
| `ASKING_AGENT_CONNECT` | Agent transfer offer | `WAITING_AGENT_RESPONSE` | Transfer question | Yes/No response |
| `WAITING_AGENT_RESPONSE` | Wait for transfer decision | `TRANSFERRING_TO_AGENT` or `GOODBYE_DECLINE` | - | Affirmative/Negative |
| `TRANSFERRING_TO_AGENT` | Initiate agent transfer | `END` | Transfer message | - |
| `GOODBYE_DECLINE` | End call politely | `END` | Goodbye message | - |

## 🗃️ Database Schema

### Tables Structure

| Table | Purpose | Key Fields | Relationships |
|-------|---------|------------|---------------|
| `customers` | Customer master data | `id`, `name`, `phone_number`, `state`, `loan_id`, `amount`, `due_date`, `language_code`, `call_status` | One-to-many with `call_sessions` |
| `call_sessions` | Individual call tracking | `id`, `call_sid`, `customer_id`, `status`, `start_time`, `end_time`, `language_used` | Many-to-one with `customers` |
| `call_status_updates` | Call status history | `id`, `call_session_id`, `status`, `timestamp`, `details` | Many-to-one with `call_sessions` |
| `file_uploads` | Upload tracking | `id`, `filename`, `upload_time`, `status`, `processed_count` | Standalone |

### Call Status Values

| Status | Description | When Set | Next Possible States |
|--------|-------------|----------|---------------------|
| `ready` | Ready for calling | Customer uploaded | `initiated`, `calling` |
| `initiated` | Call triggered | API call made | `ringing`, `failed` |
| `ringing` | Phone ringing | Exotel callback | `in_progress`, `not_picked`, `failed` |
| `in_progress` | Call connected | WebSocket active | `agent_transfer`, `completed`, `failed` |
| `agent_transfer` | Transferred to agent | Agent transfer triggered | `completed`, `failed` |
| `completed` | Call ended successfully | Conversation complete | - |
| `failed` | Call failed | Error occurred | `ready` (for retry) |
| `not_picked` | Customer didn't answer | Timeout/decline | `ready` (for retry) |

## 🔧 Redis Session Management

### Session Types

| Session Type | Key Pattern | Purpose | TTL | Data Stored |
|--------------|-------------|---------|-----|-------------|
| **WebSocket Session** | `websocket:session:{id}` | Dashboard connections | 1 hour | Connection info, client data |
| **Call Session** | `call:session:{call_sid}` | Active call data | 2 hours | Customer info, call state, language |
| **Temp Call** | `temp:call:{temp_id}` | Pre-call setup | 30 minutes | Customer data before CallSid assignment |
| **Rate Limit** | `rate:limit:{api}:{key}` | API rate limiting | 1 minute | Request counts, timestamps |

### Redis Operations

| Function | Purpose | Key Pattern | Return Value |
|----------|---------|-------------|--------------|
| `create_call_session()` | Start new call session | `call:session:{call_sid}` | Session ID |
| `get_call_session()` | Retrieve call data | `call:session:{call_sid}` | Customer info dict |
| `update_call_session()` | Update call state | `call:session:{call_sid}` | Success boolean |
| `create_websocket_session()` | New dashboard connection | `websocket:session:{id}` | Session ID |
| `cleanup_expired_sessions()` | Remove old sessions | Multiple patterns | Cleanup count |

## 🎵 Audio Processing Pipeline

### TTS (Text-to-Speech) Flow

| Stage | Function | Input | Output | Provider |
|-------|----------|-------|--------|----------|
| **1. Text Preparation** | `synthesize_tts()` | Text + Language code | Formatted request | - |
| **2. API Call** | Sarvam TTS API | Text + Language | Raw audio bytes | Sarvam AI |
| **3. Format Conversion** | Audio processing | Raw bytes | PCM 8kHz 16-bit | pydub |
| **4. Streaming** | `stream_audio_to_websocket()` | Audio bytes | WebSocket chunks | Custom |

### STT (Speech-to-Text) Flow

| Stage | Function | Input | Output | Provider |
|-------|----------|-------|--------|----------|
| **1. Audio Collection** | WebSocket media events | Base64 audio | Raw audio buffer | Exotel |
| **2. Format Conversion** | `_slin_to_wav_file()` | SLIN bytes | WAV file | pydub |
| **3. Transcription** | `transcribe_with_fallback()` | Audio file | Text transcript | Sarvam AI |
| **4. Language Detection** | `detect_language()` | Transcript text | Language code | Custom logic |

## 🌐 Language Support Matrix

### Supported Languages

| Language | Code | Script | TTS Support | STT Support | Template Coverage |
|----------|------|--------|-------------|-------------|------------------|
| English | `en-IN` | Latin | ✅ | ✅ | ✅ Complete |
| Hindi | `hi-IN` | Devanagari | ✅ | ✅ | ✅ Complete |
| Tamil | `ta-IN` | Tamil | ✅ | ✅ | ✅ Complete |
| Telugu | `te-IN` | Telugu | ✅ | ✅ | ✅ Complete |
| Malayalam | `ml-IN` | Malayalam | ✅ | ✅ | ✅ Complete |
| Gujarati | `gu-IN` | Gujarati | ✅ | ✅ | ✅ Complete |
| Marathi | `mr-IN` | Devanagari | ✅ | ✅ | ✅ Complete |
| Bengali | `bn-IN` | Bengali | ✅ | ✅ | ✅ Complete |
| Kannada | `kn-IN` | Kannada | ✅ | ✅ | ✅ Complete |
| Punjabi | `pa-IN` | Gurmukhi | ✅ | ✅ | ✅ Complete |
| Odia | `or-IN` | Odia | ✅ | ✅ | ✅ Complete |

### State-to-Language Mapping

| State/UT | Mapped Language | Code | Fallback |
|----------|-----------------|------|----------|
| Maharashtra | Marathi | `mr-IN` | Hindi |
| Karnataka | Kannada | `kn-IN` | English |
| Tamil Nadu | Tamil | `ta-IN` | English |
| Kerala | Malayalam | `ml-IN` | English |
| Gujarat | Gujarati | `gu-IN` | Hindi |
| West Bengal | Bengali | `bn-IN` | Hindi |
| Telangana | Telugu | `te-IN` | English |
| Punjab | Punjabi | `pa-IN` | Hindi |
| Odisha | Odia | `or-IN` | Hindi |
| Others | Hindi | `hi-IN` | English |

## 📊 Logging System

### Log Files

| Log File | Purpose | Level | Rotation | Content |
|----------|---------|-------|----------|---------|
| `application.log` | General app logs | INFO+ | 10MB/5 files | Startup, configuration, general flow |
| `errors.log` | Error tracking | ERROR only | 10MB/5 files | Exceptions, failures, critical issues |
| `websocket.log` | WebSocket events | INFO+ | 10MB/5 files | Connections, messages, disconnections |
| `tts.log` | Audio processing | INFO+ | 10MB/5 files | TTS requests, audio generation, streaming |
| `database.log` | DB operations | INFO+ | 10MB/5 files | Queries, connections, migrations |
| `calls.log` | Call events | INFO+ | 10MB/5 files | Call lifecycle, status changes |

### JSON Logs

| JSON Log | Purpose | Structure | Usage |
|----------|---------|-----------|-------|
| `calls.json` | Structured call data | Call events with metadata | Analytics, debugging, reporting |
| `websocket.json` | WebSocket message logs | Message events with payload | Real-time monitoring |

### Log Event Types

| Event Type | Logger | Purpose | Metadata Included |
|------------|--------|---------|-------------------|
| `CALL_INITIATED` | calls | Call started | Customer ID, phone, language |
| `LANGUAGE_DETECTED` | calls | Language identified | Detected language, transcript |
| `LANGUAGE_SWITCH_DETECTED` | calls | Language change | From/to languages, reason |
| `GREETING_REPLAYED_NEW_LANG` | calls | Greeting in new language | New language code |
| `AGENT_TRANSFER_INITIATED` | calls | Transfer to human | Agent number, reason |
| `WEBSOCKET_CONNECTED` | websocket | New connection | Session ID, client info |
| `TTS_SYNTHESIS_SUCCESS` | tts | Audio generated | Text length, language, duration |
| `DATABASE_OPERATION` | database | DB queries | Operation type, affected rows |

## 🔧 Function Dependencies

### Core Function Dependency Map

```mermaid
graph TD
    A[main.py WebSocket] --> B[greeting_template_play]
    A --> C[detect_language]
    A --> D[play_emi_details]
    A --> E[play_agent_connect_question]
    
    B --> F[synthesize_tts]
    D --> F
    E --> F
    
    F --> G[stream_audio_to_websocket]
    
    C --> H[English word detection]
    C --> I[Language pattern matching]
    
    A --> J[transcribe_with_fallback]
    J --> K[Sarvam STT API]
    
    A --> L[detect_intent_with_claude]
    L --> M[AWS Bedrock Claude]
    
    A --> N[trigger_exotel_agent_transfer]
    N --> O[Exotel API]
    
    A --> P[redis_manager]
    A --> Q[db_manager]
```

### Template System Dependencies

| Template | Depends On | Purpose | Language Support |
|----------|------------|---------|------------------|
| `GREETING_TEMPLATE` | Customer name, language | Welcome message | 11 languages |
| `EMI_DETAILS_PART1_TEMPLATE` | Loan ID, amount, due date | Loan information | 11 languages |
| `EMI_DETAILS_PART2_TEMPLATE` | Language only | Consequences warning | 11 languages |
| `AGENT_CONNECT_TEMPLATE` | Language only | Transfer offer | 11 languages |
| `GOODBYE_TEMPLATE` | Language only | Farewell message | 11 languages |

## 🚀 Deployment & Configuration

### Environment Variables

| Variable | Purpose | Example | Required |
|----------|---------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection | `postgresql://user:pass@host:port/db` | ✅ |
| `REDIS_URL` | Redis connection | `redis://localhost:6379/0` | ✅ |
| `SARVAM_API_KEY` | Audio processing | `sk_...` | ✅ |
| `EXOTEL_SID` | Exotel account | `your_sid` | ✅ |
| `EXOTEL_TOKEN` | Exotel auth | `your_token` | ✅ |
| `EXOTEL_API_KEY` | Exotel API | `your_api_key` | ✅ |
| `EXOTEL_VIRTUAL_NUMBER` | Caller ID | `+919876543210` | ✅ |
| `AGENT_PHONE_NUMBER` | Transfer target | `+919876543210` | ✅ |
| `BASE_URL` | WebSocket URL | `https://your-domain.com` | ✅ |
| `CLAUDE_INTENT_MODEL_ID` | AWS Bedrock model | `arn:aws:bedrock:...` | ✅ |

### Installation Steps

1. **Clone Repository**
   ```bash
   git clone <repository-url>
   cd voice
   ```

2. **Setup Virtual Environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   .venv\Scripts\activate     # Windows
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

5. **Initialize Database**
   ```bash
   python migrate_database.py
   ```

6. **Start Services**
   ```bash
   # Start Redis (if not running)
   redis-server
   
   # Start application
   python main.py
   ```

7. **Setup Tunneling (Development)**
   ```bash
   # Install ngrok
   ngrok http 8000
   # Update BASE_URL in .env with ngrok URL
   ```

## 🔍 Troubleshooting

### Common Issues

| Issue | Symptoms | Solution | Prevention |
|-------|----------|----------|------------|
| **Language Detection Fails** | Always defaults to Hindi | Check `detect_language()` function, verify English word list | Test with various inputs |
| **TTS Not Working** | No audio generated | Verify Sarvam API key, check rate limits | Monitor API usage |
| **WebSocket Disconnects** | Frequent connection drops | Check network stability, increase timeouts | Use connection pooling |
| **Database Errors** | Connection failures | Verify DATABASE_URL, check PostgreSQL service | Connection retry logic |
| **Redis Connection Issues** | Session data lost | Check Redis service, verify REDIS_URL | Redis clustering |

### Debug Commands

```bash
# Test language detection
python test_language_fix.py

# Test TTS functionality
python test_production_api.py

# Check database connection
python migrate_database.py

# Monitor logs
tail -f logs/application.log

# Test full audio pipeline
python debug_audio_streaming.py
```

## 📈 Performance Optimization

### Recommended Settings

| Component | Setting | Value | Reasoning |
|-----------|---------|-------|-----------|
| **WebSocket Buffer** | Audio chunk size | 320 bytes (20ms) | Optimal for telephony |
| **Redis TTL** | Call sessions | 2 hours | Prevent memory leak |
| **Database Pool** | Connection pool size | 10 connections | Handle concurrent calls |
| **TTS Rate Limit** | Requests per minute | 60 | Prevent API throttling |
| **Audio Quality** | Sample rate | 8kHz 16-bit mono | Telephony standard |

### Monitoring Metrics

| Metric | Target | Alert Threshold | Action |
|--------|-------|-----------------|--------|
| **Response Time** | <2s | >5s | Scale resources |
| **Success Rate** | >95% | <90% | Check error logs |
| **Memory Usage** | <80% | >90% | Clear sessions |
| **WebSocket Connections** | Stable | Frequent drops | Network investigation |
| **Database Query Time** | <100ms | >500ms | Optimize queries |

---

## 📝 License & Support

This is a proprietary voice assistant system for automated loan collection calls. For support, check the logs directory and refer to the troubleshooting section above.

**Last Updated**: August 17, 2025  
**Version**: 2.0 (Enhanced Language Detection)  
**Maintained By**: Voice Assistant Development Team
