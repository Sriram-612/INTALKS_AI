# 🔧 Debug Fixes for Agent Transfer Issue

Follow these steps to apply debug logging to track the "Yes" transcript issue:

## Step 1: Add Import (if not already present)

At the top of `main.py`, make sure you have this import:
```python
from utils import bedrock_client
```

## Step 2: Add Debug Function

Add this function after the existing functions in `main.py` (around line 700):

```python
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
```

## Step 3: Replace detect_intent_with_claude Function

Replace the existing `detect_intent_with_claude` function with this debug version:

```python
def detect_intent_with_claude(transcript: str, lang: str) -> str:
    """Detect intent for agent handoff using Claude via Bedrock. Returns 'affirmative'|'negative'|'unclear'."""
    print(f"🎯 [CLAUDE_INTENT_DEBUG] Input transcript: '{transcript}'")
    print(f"🎯 [CLAUDE_INTENT_DEBUG] Language: {lang}")
    
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

        print(f"🎯 [CLAUDE_INTENT_DEBUG] Calling bedrock_client.invoke_claude_model...")
        # bedrock_client.invoke_claude_model returns a plain string
        response_text = bedrock_client.invoke_claude_model(messages)
        intent = (response_text or "").strip().lower()
        
        print(f"🎯 [CLAUDE_INTENT_DEBUG] Raw Claude response: '{response_text}'")
        print(f"🎯 [CLAUDE_INTENT_DEBUG] Processed intent: '{intent}'")

        # Normalize and validate
        if intent in ("affirmative", "negative", "unclear"):
            print(f"🎯 [CLAUDE_INTENT_DEBUG] Final intent (exact match): {intent}")
            return intent
        # Try to infer if Claude returned a phrase
        if "affirmative" in intent:
            print(f"🎯 [CLAUDE_INTENT_DEBUG] Final intent (contains affirmative): affirmative")
            return "affirmative"
        if "negative" in intent:
            print(f"🎯 [CLAUDE_INTENT_DEBUG] Final intent (contains negative): negative")
            return "negative"
        
        print(f"🎯 [CLAUDE_INTENT_DEBUG] Claude returned unexpected text: '{intent}'; defaulting to 'unclear'")
        return "unclear"
        
    except Exception as e:
        print(f"❌ [CLAUDE_INTENT_DEBUG] Error detecting intent with Claude: {e}")
        import traceback
        print(f"❌ [CLAUDE_INTENT_DEBUG] Full traceback: {traceback.format_exc()}")
        return "unclear"
```

## Step 4: Replace detect_intent Function

Replace the existing `detect_intent` function with this debug version:

```python
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
```

## Step 5: Replace WebSocket Handler

Find this section in your `main.py` (around line 2713):
```python
elif conversation_stage == "WAITING_AGENT_RESPONSE":
```

Replace the entire `elif conversation_stage == "WAITING_AGENT_RESPONSE":` block with:

```python
elif conversation_stage == "WAITING_AGENT_RESPONSE":
    # 🔍 DEBUG: Enhanced logging for agent response stage
    print(f"🎯 [AGENT_RESPONSE_DEBUG] Processing transcript: '{transcript}' in WAITING_AGENT_RESPONSE stage")
    print(f"🎯 [AGENT_RESPONSE_DEBUG] Language: {call_detected_lang}, Repeat count: {agent_question_repeat_count}")
    
    # Use debug intent detection
    intent = debug_intent_detection(transcript, call_detected_lang)
    
    print(f"🎯 [AGENT_RESPONSE_DEBUG] Final detected intent: '{intent}'")
    logger.log_call_event("INTENT_DETECTED_WITH_DEBUG", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript})

    if intent == "affirmative" or intent == "agent_transfer":
        if conversation_stage != "TRANSFERRING_TO_AGENT":
            print(f"🎯 [AGENT_RESPONSE_DEBUG] Intent '{intent}' matches affirmative/agent_transfer - initiating transfer")
            logger.websocket.info("User affirmed agent transfer. Initiating transfer.")
            logger.log_call_event("AGENT_TRANSFER_INITIATED", call_sid, customer_info['name'], {"intent": intent})
            customer_number = customer_info.get('phone', '08438019383') if customer_info else "08438019383"
            ai_agent = await play_transfer_to_agent(websocket, customer_number=customer_number, customer_data=customer_info, session_id=call_sid, language=call_detected_lang) 
            conversation_stage = "AI_AGENT_MODE" if ai_agent else "TRANSFERRING_TO_AGENT"
            if not ai_agent:
                interaction_complete = True
                await asyncio.sleep(2)
                break
            # If AI agent started successfully, continue conversation
            await asyncio.sleep(1)  # Brief pause for agent introduction
        else:
            logger.websocket.warning("⚠️ Agent transfer already in progress, ignoring duplicate request")
    elif intent == "negative":
        if conversation_stage != "GOODBYE_DECLINE":
            print(f"🎯 [AGENT_RESPONSE_DEBUG] Intent '{intent}' matches negative - saying goodbye")
            logger.websocket.info("User declined agent transfer. Saying goodbye.")
            logger.log_call_event("AGENT_TRANSFER_DECLINED", call_sid, customer_info['name'])
            await play_goodbye_after_decline(websocket, call_detected_lang)
            conversation_stage = "GOODBYE_DECLINE"
            interaction_complete = True
            await asyncio.sleep(3)
            break
        else:
            logger.websocket.warning("⚠️ Goodbye already sent, ignoring duplicate request")
    else:
        print(f"🎯 [AGENT_RESPONSE_DEBUG] Intent '{intent}' is unclear - repeating question or auto-transferring")
        agent_question_repeat_count += 1
        if agent_question_repeat_count <= 2:
            logger.websocket.info(f"Unclear response to agent connect. Repeating question (attempt {agent_question_repeat_count}/2).")
            logger.log_call_event("AGENT_QUESTION_UNCLEAR_REPEAT", call_sid, customer_info['name'], {"attempt": agent_question_repeat_count})
            await play_agent_connect_question(websocket, call_detected_lang)
            last_transcription_time = time.time()
        else:
            logger.websocket.info("Too many unclear responses. Assuming user wants agent transfer.")
            logger.log_call_event("AUTO_AGENT_TRANSFER_UNCLEAR", call_sid, customer_info['name'])
            customer_number = customer_info.get('phone', '08438019383') if customer_info else "08438019383"
            ai_agent = await play_transfer_to_agent(websocket, customer_number=customer_number, customer_data=customer_info, session_id=call_sid, language=call_detected_lang) 
            conversation_stage = "AI_AGENT_MODE" if ai_agent else "TRANSFERRING_TO_AGENT"
            if not ai_agent:
                interaction_complete = True
                await asyncio.sleep(2)
                break
            # If AI agent started successfully, continue conversation
            await asyncio.sleep(1)  # Brief pause for agent introduction
```

## Step 6: Test the Fix

1. **First, test your environment:**
   ```bash
   python test_environment.py
   ```

2. **Start your voice bot application**

3. **Make a test call and say "Yes" when asked about agent transfer**

4. **Watch the console for debug output like:**
   ```
   🎯 [AGENT_RESPONSE_DEBUG] Processing transcript: 'Yes' in WAITING_AGENT_RESPONSE stage
   🔍 [DEBUG_INTENT] Testing intent detection for transcript: 'Yes'
   🔄 [FALLBACK_INTENT_DEBUG] Matched 'affirmative' keywords
   🤖 [CLAUDE_DEBUG] Generated text: 'affirmative'
   🎯 [AGENT_RESPONSE_DEBUG] Final detected intent: 'affirmative'
   User affirmed agent transfer. Initiating transfer.
   ```

## Expected Results

With these debug changes, you'll see exactly:
- What transcript is received
- How the fallback intent detection works
- Whether Claude is working or failing
- What the final intent decision is
- Whether the agent transfer logic is triggered

This will pinpoint exactly where the "Yes" transcript issue is occurring!
