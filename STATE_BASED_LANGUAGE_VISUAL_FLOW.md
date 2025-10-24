# 🎯 State-Based Language Selection - Visual Flow

## 📞 Call Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    📞 CALL INITIATED                            │
│  Customer: Rajesh Kumar                                         │
│  Phone: +919876543210                                           │
│  State: Uttar Pradesh                                           │
│  Loan ID: LOAN12345                                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              🗺️  STATE → LANGUAGE MAPPING                       │
│                                                                 │
│  Input: "Uttar Pradesh"                                         │
│  Lookup: STATE_TO_LANGUAGE dict                                 │
│  Output: "hi-IN" (Hindi)                                        │
│                                                                 │
│  Log: 🌍 Customer state: Uttar Pradesh → Initial language: hi-IN│
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│           🎤 INITIAL GREETING (State Language)                  │
│                                                                 │
│  Language: Hindi (hi-IN)                                        │
│  Template: GREETING_TEMPLATE['hi-IN']                           │
│  Text: "नमस्ते राजेश जी, मैं प्रिया बोल रही हूँ,               │
│         साउथ इंडिया फिनवेस्ट बैंक से.                          │
│         क्या आप अभी बात कर सकते हैं?"                          │
│                                                                 │
│  TTS: Sarvam AI (voice: manisha, lang: hi-IN)                  │
│  Audio: Streamed to customer via WebSocket                      │
│                                                                 │
│  Log: 🔁 Initial greeting in hi-IN: नमस्ते राजेश जी...         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              👂 WAIT FOR CUSTOMER RESPONSE                      │
│                                                                 │
│  Stage: WAITING_CONFIRMATION                                    │
│  Listening for: Yes/No confirmation                             │
│  ASR: Sarvam Speech-to-Text                                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              🎙️  CUSTOMER SPEAKS                                │
│                                                                 │
│  Audio captured → ASR processes                                 │
│  Transcript: "Yes, this is me"                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              🔍 LANGUAGE DETECTION                              │
│                                                                 │
│  Function: detect_language(transcript)                          │
│  Input: "Yes, this is me"                                       │
│  Analysis:                                                      │
│    • Check Unicode characters: None (ASCII)                     │
│    • Check keywords: "yes" (English)                            │
│    • English word count: 4/4 = 100%                             │
│  Result: "en-IN" (English)                                      │
│                                                                 │
│  Comparison:                                                    │
│    Initial Language: hi-IN (Hindi)                              │
│    Detected Language: en-IN (English)                           │
│    Match: ❌ NO - Languages are different!                      │
│                                                                 │
│  Log: 🌐 Language detection - Initial: hi-IN,                   │
│       Detected: en-IN, Transcript: yes this is me               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              🔄 LANGUAGE SWITCH TRIGGERED                       │
│                                                                 │
│  Decision: Customer prefers English                             │
│  Action: Re-greet in detected language                          │
│                                                                 │
│  Updates:                                                       │
│    current_language: hi-IN → en-IN                              │
│    customer_info['lang']: hi-IN → en-IN                         │
│    confirmation_attempts: Reset to 0                            │
│                                                                 │
│  Log: 🔄 Customer responded in different language: hi-IN → en-IN│
│  Log: ♻️ Re-greeting customer in detected language: en-IN       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│           🎤 RE-GREETING (Detected Language)                    │
│                                                                 │
│  Language: English (en-IN)                                      │
│  Template: GREETING_TEMPLATE['en-IN']                           │
│  Text: "Hi Rajesh, Priya here from South India Finvest Bank.   │
│         Is this you on the line?"                               │
│                                                                 │
│  TTS: Sarvam AI (voice: anushka, lang: en-IN)                  │
│  Audio: Streamed to customer via WebSocket                      │
│                                                                 │
│  Stage: Stays in WAITING_CONFIRMATION                           │
│  Reason: Give customer chance to respond in correct language    │
│                                                                 │
│  Log: 🔁 Re-greeting in en-IN: Hi Rajesh, Priya here...         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              👂 WAIT FOR CONFIRMATION (Again)                   │
│                                                                 │
│  Stage: WAITING_CONFIRMATION                                    │
│  Current Language: en-IN (English)                              │
│  Listening for: Yes/No in English                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              🎙️  CUSTOMER CONFIRMS                              │
│                                                                 │
│  Transcript: "Yes"                                              │
│  Language: en-IN (matches current_language)                     │
│  Intent: Affirmative                                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              ✅ PROCEED TO MAIN CONVERSATION                    │
│                                                                 │
│  Stage: WAITING_CONFIRMATION → CLAUDE_CHAT                      │
│  Language: en-IN (locked for entire conversation)               │
│                                                                 │
│  Bot: "Thank you for confirming your identity.                  │
│        Please wait a second."                                   │
│                                                                 │
│  Claude AI: "Hi Rajesh! This is Priya from South India          │
│             Finvest Bank. I'm calling about your loan ending    │
│             in 2345. Your EMI of ₹50,000 was due on             │
│             October 15th. When can you make the payment?"       │
│                                                                 │
│  [Rest of conversation continues in English]                    │
└─────────────────────────────────────────────────────────────────┘
```

## 🔄 Alternative Flow: Same Language Response

```
┌─────────────────────────────────────────────────────────────────┐
│                    📞 CALL INITIATED                            │
│  Customer: Priya Sharma                                         │
│  State: Tamil Nadu                                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  🗺️  STATE → LANGUAGE MAPPING                                   │
│  "Tamil Nadu" → "ta-IN" (Tamil)                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  🎤 INITIAL GREETING (Tamil)                                    │
│  "ஹாய் பிரியா அவர்களே, நான் பிரியா.                           │
│   சவுத் இந்தியா ஃபின்வெஸ்ட் வங்கியிலிருந்து பேசுகிறேன்.         │
│   நீங்கள்தானே பேசுறது?"                                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  👂 WAIT FOR RESPONSE                                           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  🎙️  CUSTOMER SPEAKS                                            │
│  Transcript: "ஆம், நான்தான்"                                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  🔍 LANGUAGE DETECTION                                          │
│  Detected: "ta-IN" (Tamil)                                      │
│  Initial: "ta-IN" (Tamil)                                       │
│  Match: ✅ YES - Same language!                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  ✅ NO RE-GREETING NEEDED                                       │
│  Action: Continue directly to CLAUDE_CHAT                       │
│  Language: ta-IN (Tamil throughout)                             │
└─────────────────────────────────────────────────────────────────┘
```

## 🎨 Code Flow in Functions

```python
# 1. Call Starts
async def handle_start_event(msg):
    # ... get customer data ...
    customer_state = customer_info.get('state', '')
    
    # Map state to language
    initial_language = get_initial_language_from_state(customer_state)
    #   "Uttar Pradesh" → "hi-IN"
    
    current_language = initial_language
    customer_info['initial_language'] = initial_language
    
    # Play greeting in state language
    await play_confirmation_prompt(websocket, customer_info)
    conversation_stage = "WAITING_CONFIRMATION"


# 2. Play Greeting
async def play_confirmation_prompt(websocket, customer_info):
    customer_state = customer_info.get("state", "")
    initial_language = get_initial_language_from_state(customer_state)
    
    # Get greeting template in state language
    greeting = GREETING_TEMPLATE[initial_language].format(
        name=customer_info.get('name')
    )
    # "नमस्ते राजेश जी, मैं प्रिया बोल रही हूँ..."
    
    # Convert to speech in that language
    audio_bytes = await sarvam_handler.synthesize_tts(greeting, initial_language)
    await stream_audio_to_websocket(websocket, audio_bytes)


# 3. Customer Responds
async def handle_confirmation_response(transcript):
    # Detect language of customer's response
    detected_language = detect_language(transcript)
    #   "Yes, this is me" → "en-IN"
    
    initial_language = customer_info.get('initial_language', 'en-IN')
    #   "hi-IN" (from state mapping)
    
    # Compare languages
    if detected_language != initial_language:
        # Customer responded in different language!
        current_language = detected_language
        customer_info['lang'] = detected_language
        
        # Re-greet in detected language
        re_greeting = GREETING_TEMPLATE[detected_language].format(
            name=customer_info.get('name')
        )
        # "Hi Rajesh, Priya here from South India Finvest Bank..."
        
        await speak_text(re_greeting, detected_language)
        
        confirmation_attempts = 0  # Reset
        return "language_switched"  # Stay in WAITING_CONFIRMATION
    
    # Same language - proceed normally
    if is_affirmative:
        conversation_stage = "CLAUDE_CHAT"
        # ... continue ...
```

## 📊 State Language Statistics

| State Category | Language | States Count |
|----------------|----------|--------------|
| Hindi Belt | hi-IN | 11 states |
| South India | ta-IN, te-IN, kn-IN, ml-IN | 8 states |
| Western India | gu-IN, mr-IN | 2 states |
| Eastern India | bn-IN, or-IN | 2 states |
| Northern India | pa-IN | 1 state |
| **Total** | **11 languages** | **28+ states/UTs** |

## 🎯 Key Benefits Visualized

```
WITHOUT State-Based Language:
┌──────────────────┐
│ Every customer   │
│ gets English     │ → ❌ Low engagement
│ greeting         │ → ❌ Confusion
└──────────────────┘ → ❌ Trust issues

WITH State-Based Language:
┌──────────────────┐
│ UP customer gets │
│ Hindi greeting   │ → ✅ Immediate connection
├──────────────────┤ → ✅ Better understanding
│ TN customer gets │ → ✅ Higher trust
│ Tamil greeting   │ → ✅ Smooth conversation
└──────────────────┘
```

## 🧪 Testing Checklist

- [ ] **Test 1:** Customer from Hindi state responds in Hindi
  - Expected: ✅ No re-greeting, continues in Hindi
  
- [ ] **Test 2:** Customer from Hindi state responds in English
  - Expected: ✅ Re-greets in English, continues in English
  
- [ ] **Test 3:** Customer from Tamil state responds in Tamil
  - Expected: ✅ No re-greeting, continues in Tamil
  
- [ ] **Test 4:** Customer with missing state data
  - Expected: ✅ Greets in English (default)
  
- [ ] **Test 5:** Customer from unknown state
  - Expected: ✅ Greets in English (fallback)

---

**Status:** ✅ LIVE AND RUNNING

**Monitor Logs:** `tail -f logs/app.log | grep -E "🌍|🔄|♻️"`
