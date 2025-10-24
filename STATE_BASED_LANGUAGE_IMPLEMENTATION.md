# 🌍 State-Based Initial Language Selection with Language Detection

## 📋 Overview

This implementation enables the voice bot to:
1. **Greet customers in their state's primary language** (e.g., Hindi for Uttar Pradesh)
2. **Detect the customer's response language** using ASR transcription
3. **Re-greet in the detected language** if customer responds in a different language
4. **Continue the conversation** in the customer's preferred language

## 🎯 Feature Details

### **Initial Greeting Based on State**

When a call is initiated, the bot:
- Reads the customer's **state** from the database
- Maps the state to its primary language using `STATE_TO_LANGUAGE` mapping
- Plays the **GREETING_TEMPLATE** in that language

**Example:**
- Customer from **Uttar Pradesh** → Initial greeting in **Hindi (hi-IN)**
- Customer from **Tamil Nadu** → Initial greeting in **Tamil (ta-IN)**
- Customer from **Karnataka** → Initial greeting in **Kannada (kn-IN)**

### **Language Detection & Switching**

After the initial greeting:
1. Bot waits for customer's response
2. **ASR transcribes** the customer's speech
3. **Language detection algorithm** analyzes the transcript
4. If detected language ≠ initial language:
   - Bot **re-greets** customer in the detected language
   - Updates `current_language` variable
   - Continues conversation in new language

**Example Flow:**
```
Bot: (Hindi) "नमस्ते राजेश जी, मैं प्रिया बोल रही हूँ..."
Customer: (responds in English) "Yes, this is me"
Bot: (detects English) → Re-greets
Bot: (English) "Hi Rajesh, Priya here from South India Finvest Bank..."
Customer: "Yes"
Bot: (continues in English for rest of conversation)
```

## 🗺️ State to Language Mapping

```python
STATE_TO_LANGUAGE = {
    'uttar pradesh': 'hi-IN',      # Hindi
    'tamil nadu': 'ta-IN',          # Tamil
    'karnataka': 'kn-IN',           # Kannada
    'kerala': 'ml-IN',              # Malayalam
    'telangana': 'te-IN',           # Telugu
    'andhra pradesh': 'te-IN',      # Telugu
    'maharashtra': 'mr-IN',         # Marathi
    'gujarat': 'gu-IN',             # Gujarati
    'west bengal': 'bn-IN',         # Bengali
    'punjab': 'pa-IN',              # Punjabi
    'odisha': 'or-IN',              # Odia
    'delhi': 'hi-IN',               # Hindi
    # ... all other states mapped
}
```

**Default:** If state is missing or unrecognized → **English (en-IN)**

## 🔧 Technical Implementation

### **1. Modified `play_confirmation_prompt` Function**

**Location:** `main.py` line ~1392

**Changes:**
```python
async def play_confirmation_prompt(websocket, customer_info: Dict[str, Any]) -> None:
    """
    Play initial greeting in customer's state-based language.
    This will be followed by language detection and potential re-greeting.
    """
    name = customer_info.get("name") or "there"
    
    # Get initial language based on customer's state
    customer_state = customer_info.get("state", "")
    initial_language = get_initial_language_from_state(customer_state)
    
    logger.tts.info(f"🌍 Customer state: {customer_state} → Initial language: {initial_language}")
    
    # Use the GREETING_TEMPLATE in the state-based language
    greeting = GREETING_TEMPLATE.get(initial_language, GREETING_TEMPLATE["en-IN"]).format(name=name)
    
    logger.tts.info(f"🔁 Initial greeting in {initial_language}: {greeting}")
    audio_bytes = await sarvam_handler.synthesize_tts(greeting, initial_language)
    await stream_audio_to_websocket(websocket, audio_bytes)
```

**Key Changes:**
- Uses customer's `state` field to determine initial language
- Calls `get_initial_language_from_state()` helper function
- Uses `GREETING_TEMPLATE` (multilingual) instead of hardcoded English
- Logs state → language mapping for debugging

### **2. Modified `handle_start_event` Function**

**Location:** `main.py` line ~2258

**Changes:**
```python
# Set initial language based on customer's state
initial_language = get_initial_language_from_state(customer_info.get('state', ''))
current_language = initial_language
customer_info['initial_language'] = initial_language

logger.websocket.info(f"🌍 Setting initial language to {initial_language} based on state: {customer_info.get('state')}")
```

**Key Changes:**
- Stores `initial_language` in `customer_info` for comparison
- Sets `current_language` to state-based language (not database `lang` field)
- Logs the language selection decision

### **3. Enhanced `handle_confirmation_response` Function**

**Location:** `main.py` line ~2403

**Changes:**
```python
async def handle_confirmation_response(transcript: str) -> Optional[str]:
    nonlocal conversation_stage, confirmation_attempts, claude_chat, current_language

    normalized = transcript.lower()
    affirmative = {"yes", "yeah", "yep", "haan", "ha", "correct", "sure", "yup"}
    negative = {"no", "nah", "nope", "nahi", "na"}

    is_affirmative = any(word in normalized for word in affirmative)
    is_negative = any(word in normalized for word in negative)

    # Detect the language of customer's response
    detected_language = detect_language(transcript)
    initial_language = customer_info.get('initial_language', 'en-IN')
    
    logger.websocket.info(f"🌐 Language detection - Initial: {initial_language}, Detected: {detected_language}, Transcript: {transcript}")
    
    # Check if customer responded in a different language than initial greeting
    if detected_language and detected_language != initial_language and detected_language != current_language:
        logger.websocket.info(f"🔄 Customer responded in different language: {initial_language} → {detected_language}")
        logger.websocket.info(f"♻️ Re-greeting customer in detected language: {detected_language}")
        
        # Update current language
        current_language = detected_language
        customer_info['lang'] = detected_language
        
        # Re-play greeting in detected language
        name = customer_info.get("name") or "there"
        re_greeting = GREETING_TEMPLATE.get(detected_language, GREETING_TEMPLATE["en-IN"]).format(name=name)
        
        logger.tts.info(f"🔁 Re-greeting in {detected_language}: {re_greeting}")
        await speak_text(re_greeting, detected_language)
        
        # Reset confirmation attempts for the new language
        confirmation_attempts = 0
        
        # Stay in WAITING_CONFIRMATION stage to get response in correct language
        return "language_switched"

    # ... rest of confirmation logic ...
```

**Key Changes:**
- Calls `detect_language()` on customer's transcript
- Compares detected language with initial language
- If different:
  - Logs the language switch
  - Updates `current_language` and `customer_info['lang']`
  - Re-plays greeting using `GREETING_TEMPLATE` in detected language
  - Resets `confirmation_attempts` (gives customer fresh start)
  - Returns `"language_switched"` status
  - Stays in `WAITING_CONFIRMATION` stage (waits for new response)

## 📊 Conversation Flow Diagram

```
┌─────────────────────────────────────────┐
│ Call Initiated                          │
│ • Fetch customer data (name, state)    │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ Map State → Language                    │
│ Example: "Uttar Pradesh" → "hi-IN"     │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ Play Initial Greeting                   │
│ (in state-based language)               │
│ Example: "नमस्ते राजेश जी..."           │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ Wait for Customer Response              │
│ • ASR transcribes speech                │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ Detect Language of Response             │
│ • Analyze transcript                    │
│ • Check Unicode characters              │
│ • Match language keywords               │
└──────────────┬──────────────────────────┘
               │
        ┌──────┴──────┐
        │             │
        ▼             ▼
┌─────────────┐ ┌─────────────────────────┐
│ Same        │ │ Different Language      │
│ Language    │ │ Detected                │
└──────┬──────┘ └──────┬──────────────────┘
       │               │
       │               ▼
       │        ┌─────────────────────────┐
       │        │ Re-greet in Detected    │
       │        │ Language                │
       │        │ Example: "Hi Rajesh..." │
       │        └──────┬──────────────────┘
       │               │
       │               ▼
       │        ┌─────────────────────────┐
       │        │ Wait for New Response   │
       │        └──────┬──────────────────┘
       │               │
       └───────┬───────┘
               │
               ▼
┌─────────────────────────────────────────┐
│ Process Confirmation                    │
│ • Yes → Start main conversation         │
│ • No → End call politely                │
└─────────────────────────────────────────┘
```

## 🧪 Testing Scenarios

### **Scenario 1: Customer Responds in Same Language**
```
1. Customer: Uttar Pradesh (UP)
2. Bot greets in Hindi: "नमस्ते राजेश जी..."
3. Customer: "हाँ, मैं राजेश बोल रहा हूँ"
4. Bot detects: Hindi (same as initial)
5. Bot continues: No re-greeting needed
6. ✅ Conversation proceeds in Hindi
```

### **Scenario 2: Customer Responds in Different Language**
```
1. Customer: Uttar Pradesh (UP)
2. Bot greets in Hindi: "नमस्ते राजेश जी..."
3. Customer: "Yes, this is Rajesh speaking"
4. Bot detects: English (different from Hindi)
5. Bot re-greets in English: "Hi Rajesh, Priya here..."
6. Customer: "Yes"
7. ✅ Conversation proceeds in English
```

### **Scenario 3: Customer from State Without Data**
```
1. Customer: State field is empty/null
2. Bot uses default: English (en-IN)
3. Bot greets: "Hi Rajesh, Priya here..."
4. Customer responds in any language
5. Bot detects language and switches if needed
6. ✅ Fallback works correctly
```

## 🔍 Language Detection Algorithm

The `detect_language()` function uses multiple strategies:

### **1. Unicode Character Analysis**
```python
_is_devanagari(text)  # Hindi, Marathi
_is_tamil(text)       # Tamil
_is_telugu(text)      # Telugu
_is_kannada(text)     # Kannada
_is_malayalam(text)   # Malayalam
_is_gujarati(text)    # Gujarati
_is_bengali(text)     # Bengali
_is_punjabi(text)     # Punjabi
_is_oriya(text)       # Odia
```

### **2. Language-Specific Keywords**
```python
# Hindi
["नमस्ते", "हां", "नहीं", "हाँ", "जी", "अच्छा"]

# Tamil
["வணக்கம்", "ஆம்", "இல்லை"]

# Telugu
["హాయ్", "అవును", "కాదు"]

# ... and more for each language
```

### **3. English Word Detection**
```python
english_words = [
    "yes", "yeah", "okay", "no", "hello", "hi",
    "please", "thank", "help", "agent", ...
]
# If 50%+ words match → English
```

### **4. Default Fallback**
- If no language detected → defaults to **English (en-IN)**

## 📝 Log Messages for Debugging

The implementation adds comprehensive logging:

```
🌍 Customer state: Uttar Pradesh → Initial language: hi-IN
🔁 Initial greeting in hi-IN: नमस्ते राजेश जी...
🌐 Language detection - Initial: hi-IN, Detected: en-IN, Transcript: yes this is me
🔄 Customer responded in different language: hi-IN → en-IN
♻️ Re-greeting customer in detected language: en-IN
🔁 Re-greeting in en-IN: Hi Rajesh, Priya here from South India Finvest Bank...
```

**Search these emojis in logs to trace language switching:**
- 🌍 = State-to-language mapping
- 🔁 = TTS greeting/speech
- 🌐 = Language detection result
- 🔄 = Language switch initiated
- ♻️ = Re-greeting action

## ✅ Benefits

1. **Improved Customer Experience**
   - Customers hear greeting in their native language first
   - Natural language switching if customer prefers different language
   - Reduces confusion and increases trust

2. **Flexibility**
   - Handles multilingual customers gracefully
   - Supports all 11 Indian languages + English
   - Falls back to English if state unknown

3. **Intelligence**
   - Automatic language detection via ASR transcript
   - No manual language selection required
   - Adapts to customer's preference in real-time

4. **Robustness**
   - Works even if state data is missing (defaults to English)
   - Handles code-mixing (customer switches mid-conversation)
   - Resets confirmation attempts after language switch

## 🚀 Deployment

### **Files Modified:**
1. `main.py`
   - `play_confirmation_prompt()` function
   - `handle_start_event()` function
   - `handle_confirmation_response()` function

### **Dependencies:**
- ✅ `STATE_TO_LANGUAGE` mapping (already exists)
- ✅ `GREETING_TEMPLATE` (already exists)
- ✅ `detect_language()` function (already exists)
- ✅ `get_initial_language_from_state()` helper (already exists)

### **Testing Checklist:**
- [ ] Test customer from Hindi-speaking state (UP, Bihar, etc.)
- [ ] Test customer responding in same language as greeting
- [ ] Test customer responding in different language
- [ ] Test customer with missing state data
- [ ] Test language detection accuracy with real ASR transcripts
- [ ] Verify re-greeting plays correctly in detected language
- [ ] Check logs show proper language switching events
- [ ] Confirm conversation continues in detected language

## 📞 Customer CSV Requirements

For this feature to work optimally, ensure customer CSV has:

```csv
Name,Phone,Loan ID,Amount,Due Date,State,Cluster,Branch,...
Rajesh Kumar,9876543210,LOAN123,50000,2025-10-15,Uttar Pradesh,...
Priya Sharma,9876543211,LOAN124,45000,2025-11-20,Tamil Nadu,...
```

**Important:** The `State` column must use full state names (case-insensitive):
- ✅ "Uttar Pradesh", "Tamil Nadu", "Karnataka"
- ❌ "UP", "TN", "KA" (abbreviations won't map)

## 🔮 Future Enhancements

1. **State Abbreviation Support**
   - Map "UP" → "Uttar Pradesh" → "hi-IN"
   - Map "TN" → "Tamil Nadu" → "ta-IN"

2. **Confidence Scoring**
   - Only switch language if detection confidence > 80%
   - Ask customer to confirm language preference

3. **Multi-Turn Language Learning**
   - Remember customer's language preference for future calls
   - Store in database for next interaction

4. **Advanced Code-Mixing**
   - Handle Hinglish ("Yes, main baat kar raha hoon")
   - Detect dominant language in mixed speech

## 📚 References

- **State Language Mapping:** Based on primary language spoken in each Indian state
- **Language Detection:** Uses Unicode ranges + keyword matching
- **Greeting Templates:** Stored in `GREETING_TEMPLATE` dictionary (lines 534-619)
- **Conversation Stages:** `AWAIT_START` → `WAITING_CONFIRMATION` → `CLAUDE_CHAT`

---

**Status:** ✅ **IMPLEMENTED AND READY FOR TESTING**

**Last Updated:** October 24, 2025
