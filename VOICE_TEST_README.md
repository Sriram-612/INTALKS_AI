# Voice-based Testing System

This system enables **real voice call testing** with your existing voice bot infrastructure. It triggers actual calls and monitors the complete voice pipeline in real-time.

## 🎯 Complete Voice Flow

```
Call Trigger → Customer Answers → Greeting → Voice Input → Sarvam STT → Claude LLM → Sarvam TTS → Customer
```

## 📁 Files Created

### 1. `voice_call_tester.py` - Call Triggering System
- Triggers real calls using existing Exotel infrastructure
- Creates test customers in database
- Integrates with existing call management service
- Monitors call status and progression

### 2. `voice_websocket_monitor.py` - Real-time Voice Monitoring
- Monitors WebSocket connections for voice interactions
- Tracks STT, Claude, and TTS pipeline stages
- Real-time statistics and activity logging
- Dashboard and voicebot WebSocket monitoring

### 3. `run_voice_test.py` - Complete Test Runner
- Combines call triggering with voice monitoring
- Interactive testing interface
- Automated voice test scenarios
- Command-line interface for quick testing

## 🚀 Quick Start

### 1. Environment Setup
Ensure your `.env` file contains all required variables:
```bash
SARVAM_API_KEY=your_sarvam_key
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
CLAUDE_MODEL_ID=your_claude_model_arn
EXOTEL_SID=your_exotel_sid
EXOTEL_TOKEN=your_exotel_token
BASE_URL=https://your_ngrok_url.ngrok-free.app
```

### 2. Run Voice Tests

#### Interactive Mode (Recommended)
```bash
python run_voice_test.py
```

#### Quick Voice Test
```bash
# Test with Vijay
python run_voice_test.py --test vijay

# Test with Priya
python run_voice_test.py --test priya
```

#### Trigger Call Only
```bash
python run_voice_test.py --call vijay
```

#### Monitor Mode Only
```bash
python run_voice_test.py --monitor
```

## 🎮 Interactive Commands

When running in interactive mode:

```bash
🎙️ Voice> test vijay          # Complete voice test
🎙️ Voice> call priya          # Trigger call only
🎙️ Voice> monitor <call_sid>  # Monitor specific call
🎙️ Voice> status              # Show system status
🎙️ Voice> help                # Show help
🎙️ Voice> quit                # Exit
```

## 👥 Test Customers

### Customer 1 - Vijay
- **Name**: Vijay
- **Phone**: +919384531725
- **Loan ID**: LOAN123456
- **Amount**: ₹15,000
- **Language**: English (en-IN)

### Customer 2 - Priya
- **Name**: Priya Sharma
- **Phone**: +919876543210
- **Loan ID**: LOAN789012
- **Amount**: ₹25,000
- **Language**: Hindi (hi-IN)

## 🎧 Voice Pipeline Monitoring

The system monitors these voice pipeline stages:

### 1. Call Connection
- Exotel call status updates
- WebSocket connection establishment
- Customer answer detection

### 2. Voice Input Processing
```
Customer Speech → Audio Capture → Sarvam STT → Text Transcript
```

### 3. AI Processing
```
Text Transcript → Claude LLM → AI Response Generation
```

### 4. Voice Output
```
AI Response → Sarvam TTS → Audio Generation → Customer Playback
```

## 📊 Real-time Monitoring

### Dashboard WebSocket
- Call status updates
- Session management
- Error tracking

### Voicebot WebSocket
- Audio input/output
- STT transcriptions
- Claude responses
- TTS audio generation
- Pipeline statistics

## 🔍 Expected Voice Interaction Flow

### 1. Initial Contact
```
System: "Hello Vijay, this is South India Finvest Bank calling. 
         Am I speaking with Vijay regarding loan LOAN123456?"

Customer: "Yes, this is Vijay"
```

### 2. Language Detection & Greeting
```
System: [Detects language, plays personalized greeting]
        "Thank you. I'm calling about your loan with outstanding 
         amount ₹15,000 due on 2024-01-15..."
```

### 3. Voice Conversation
```
Customer: "I need help with payment options"

System: [STT] → [Claude processes] → [TTS] →
        "I understand you need payment assistance. We have several 
         flexible options available..."
```

### 4. Agent Transfer (if requested)
```
Customer: "I want to speak to an agent"

System: "I'll connect you to our specialist agent..."
        [Switches to AI Agent mode or human transfer]
```

## 🧪 Testing Scenarios

### Scenario 1: Basic Interaction
1. Trigger call to Vijay
2. Customer answers and responds to greeting
3. System detects language and continues conversation
4. Monitor STT → Claude → TTS pipeline

### Scenario 2: Language Switching
1. Trigger call to Priya (Hindi preference)
2. Customer responds in different language
3. System adapts and switches language
4. Conversation continues in customer's preferred language

### Scenario 3: Agent Transfer
1. Customer requests to speak with agent
2. System processes intent via Claude
3. Transfers to AI agent mode
4. Enhanced conversation with payment solutions

## 🔧 Troubleshooting

### Common Issues

#### 1. Call Not Connecting
- Check Exotel credentials in `.env`
- Verify BASE_URL is accessible
- Ensure phone number format is correct

#### 2. WebSocket Connection Failed
- Check if ngrok tunnel is active
- Verify BASE_URL in environment
- Ensure WebSocket endpoints are accessible

#### 3. Voice Pipeline Errors
- Check Sarvam API key and limits
- Verify AWS/Claude credentials
- Monitor logs for specific error messages

#### 4. No Audio Response
- Check TTS configuration
- Verify audio format compatibility
- Monitor WebSocket audio streaming

### Debug Commands
```bash
# Check system status
python run_voice_test.py
🎙️ Voice> status

# Monitor specific call
python run_voice_test.py
🎙️ Voice> monitor <call_sid>

# Test individual components
python voice_call_tester.py
python voice_websocket_monitor.py
```

## 📈 Monitoring Output

### Call Status Updates
```
📞 Call Status Update:
   Call SID: abc123def456
   Customer: Vijay
   Status: call_in_progress
🎯 Call is now active - voice pipeline should be starting!
```

### Voice Pipeline Activity
```
🎤 Audio received: 1024 bytes (base64)
📝 STT Result:
   Transcript: 'Hello, I need help with my loan'
   Language: en-IN
🤖 Claude Response:
   Response: 'I understand you need assistance...'
🔊 TTS Audio Generated:
   Length: 45632 bytes
```

### Pipeline Statistics
```
📊 Voice Pipeline Statistics:
   Total Interactions: 15
   STT Calls: 8
   Claude Calls: 7
   TTS Calls: 6
   Errors: 0
   Active Sessions: 1
```

## 🔗 Integration with Main System

This testing system uses your existing components:
- **Call Management Service** - For triggering calls
- **WebSocket Handlers** - For voice interactions
- **Sarvam Handler** - For STT/TTS processing
- **Claude Integration** - For AI responses
- **Database & Redis** - For session management

## 🎯 Success Criteria

A successful voice test should show:
1. ✅ Call triggered and connected
2. ✅ Customer answers and WebSocket established
3. ✅ Greeting played successfully
4. ✅ Customer speech captured and transcribed
5. ✅ Claude generates appropriate response
6. ✅ Response converted to speech and played
7. ✅ Conversation flows naturally
8. ✅ Agent transfer works if requested

## 📝 Next Steps

1. **Run Initial Test**: Start with `python run_voice_test.py --test vijay`
2. **Monitor Pipeline**: Watch for STT → Claude → TTS flow
3. **Test Scenarios**: Try different customer interactions
4. **Verify Quality**: Check response relevance and audio quality
5. **Scale Testing**: Test with multiple concurrent calls
6. **Production Ready**: Deploy with confidence knowing voice pipeline works

This voice testing system ensures your speech-to-speech pipeline works correctly before production deployment!
