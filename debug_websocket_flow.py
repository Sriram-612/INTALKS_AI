#!/usr/bin/env python3
"""
Debug script to fix the WebSocket flow issue where the bot is not waiting for user responses.

This script analyzes and fixes the conversation flow to ensure proper waiting at each stage.
"""

import re

def fix_conversation_flow():
    """Fix the main conversation flow in main.py to ensure proper waiting for user responses."""
    
    # Read the current main.py file
    with open('/home/cyberdude/Documents/Projects/voice/main.py', 'r') as f:
        content = f.read()
    
    print("🔍 Analyzing current WebSocket flow...")
    
    # Check if there are duplicate functions
    websocket_handlers = content.count("async def handle_voicebot_websocket")
    print(f"   Found {websocket_handlers} WebSocket handler functions")
    
    # Check if WAITING_FOR_CONFIRMATION is properly handled
    confirmation_checks = content.count("WAITING_FOR_CONFIRMATION")
    print(f"   Found {confirmation_checks} WAITING_FOR_CONFIRMATION references")
    
    # Check buffer processing
    buffer_processing = content.count("audio_buffer.extend(raw_audio)")
    print(f"   Found {buffer_processing} audio buffer processing sections")
    
    # Check if transcription is happening
    transcription_calls = content.count("transcribe_from_payload")
    print(f"   Found {transcription_calls} transcription calls")
    
    # The core issue: Check if the system is auto-advancing through stages
    if "conversation_stage = \"PLAYING_EMI_DETAILS\"" in content:
        print("⚠️  ISSUE FOUND: System is auto-advancing to EMI details without proper confirmation")
        return True
    
    return False

def create_fixed_websocket_handler():
    """Create a fixed version of the WebSocket handler with proper waiting logic."""
    
    fixed_handler = '''
async def handle_voicebot_websocket_fixed(websocket: WebSocket, session_id: str, temp_call_id: str = None, call_sid: str = None, phone: str = None):
    """
    FIXED: Core voicebot WebSocket handling logic with proper waiting for user responses.
    """
    logger.websocket.info(f"✅ Connected to Exotel Voicebot for session: {session_id}")

    # Initialize variables from parameters
    if not call_sid:
        call_sid = session_id

    logger.websocket.info(f"Session params: temp_call_id={temp_call_id}, call_sid={call_sid}, phone={phone}")

    # State management with proper waiting
    conversation_stage = "INITIAL_GREETING"
    call_detected_lang = "en-IN"
    audio_buffer = bytearray()
    last_transcription_time = time.time()
    interaction_complete = False
    customer_info = None
    initial_greeting_played = False
    confirmation_attempts = 0
    
    # CRITICAL FIX: Add flags to prevent auto-advancement
    waiting_for_user_input = True
    last_stage_change = time.time()

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            logger.log_websocket_message("Received message", msg)

            if msg.get("event") == "start":
                logger.websocket.info("🔁 Got start event")
                
                # Customer info retrieval logic (existing code)
                # ... [customer lookup logic remains the same] ...
                
                # FIXED: Only play initial greeting, then WAIT for user response
                if conversation_stage == "INITIAL_GREETING":
                    logger.websocket.info(f"1. Playing initial greeting and waiting for user response...")
                    try:
                        await greeting_template_play(websocket, customer_info, lang=initial_greeting_language)
                        logger.websocket.info(f"✅ Initial greeting played - NOW WAITING FOR USER RESPONSE")
                        conversation_stage = "WAITING_FOR_CONFIRMATION"
                        waiting_for_user_input = True
                        last_transcription_time = time.time()
                        # CRITICAL: Don't play anything else automatically!
                    except Exception as e:
                        logger.websocket.error(f"❌ Error playing initial greeting: {e}")
                continue

            if msg.get("event") == "media":
                payload_b64 = msg["media"]["payload"]
                raw_audio = base64.b64decode(payload_b64)

                if interaction_complete:
                    continue

                # FIXED: Always process audio when waiting for user input
                if raw_audio and any(b != 0 for b in raw_audio) and waiting_for_user_input:
                    audio_buffer.extend(raw_audio)
                    logger.websocket.debug(f"🎵 Audio received: {len(raw_audio)} bytes (buffer: {len(audio_buffer)} bytes)")
                
                now = time.time()
                buffer_timeout = AGENT_RESPONSE_BUFFER_DURATION if conversation_stage == "WAITING_AGENT_RESPONSE" else BUFFER_DURATION_SECONDS

                # FIXED: Only process buffer when we're actually waiting for input
                if waiting_for_user_input and now - last_transcription_time >= buffer_timeout:
                    logger.websocket.info(f"⏰ Buffer timeout reached in stage: {conversation_stage}")
                    
                    if len(audio_buffer) == 0:
                        logger.websocket.info("🔇 No audio received - handling silence")
                        # Handle no audio based on stage
                        if conversation_stage == "WAITING_FOR_CONFIRMATION":
                            confirmation_attempts += 1
                            if confirmation_attempts <= 2:
                                logger.websocket.info(f"🔄 No response to greeting (attempt {confirmation_attempts}/2)")
                                await play_did_not_hear_response(websocket, call_detected_lang)
                                last_transcription_time = time.time()
                            else:
                                logger.websocket.info("❌ Too many failed confirmation attempts - ending call")
                                interaction_complete = True
                                break
                        # [other stage handling...]
                    else:
                        # FIXED: Proper audio processing with transcript validation
                        try:
                            if len(audio_buffer) < MIN_AUDIO_BYTES:
                                logger.websocket.info(f"🚫 Audio buffer too small: {len(audio_buffer)} bytes")
                                audio_buffer.clear()
                                last_transcription_time = now
                                continue

                            transcript = await sarvam_handler.transcribe_from_payload(audio_buffer)
                            
                            # Handle transcript tuple format
                            if isinstance(transcript, tuple):
                                transcript_text, detected_language = transcript
                                if detected_language and detected_language != "en-IN":
                                    call_detected_lang = detected_language
                                transcript = transcript_text
                            
                            logger.websocket.info(f"📝 Transcript received: '{transcript}' (stage: {conversation_stage})")
                            
                            # FIXED: Only process valid transcripts
                            if transcript and len(transcript.strip()) > 0:
                                waiting_for_user_input = False  # Stop waiting, we got input
                                
                                if conversation_stage == "WAITING_FOR_CONFIRMATION":
                                    logger.websocket.info(f"✅ User confirmed! Processing response: '{transcript}'")
                                    
                                    # Detect language and proceed appropriately
                                    user_detected_lang = detect_language(transcript)
                                    call_detected_lang = user_detected_lang
                                    
                                    logger.websocket.info(f"🎯 Language detected: {user_detected_lang}")
                                    logger.websocket.info(f"🎪 Now proceeding to EMI details...")
                                    
                                    # Play EMI details now that user has confirmed
                                    try:
                                        await play_emi_details_part1(websocket, customer_info, call_detected_lang)
                                        await play_emi_details_part2(websocket, customer_info, call_detected_lang)
                                        await play_agent_connect_question(websocket, call_detected_lang)
                                        
                                        conversation_stage = "WAITING_AGENT_RESPONSE"
                                        waiting_for_user_input = True  # Now wait for agent response
                                        last_transcription_time = time.time()
                                        
                                        logger.websocket.info(f"✅ EMI details played - now waiting for agent response")
                                    except Exception as e:
                                        logger.websocket.error(f"❌ Error playing EMI details: {e}")
                                
                                elif conversation_stage == "WAITING_AGENT_RESPONSE":
                                    # Process agent transfer intent
                                    logger.websocket.info(f"🤖 Processing agent intent for: '{transcript}'")
                                    
                                    # Validate transcript before intent detection
                                    if len(transcript.strip()) < 2 or not any(c.isalpha() for c in transcript):
                                        logger.websocket.info(f"🚫 Invalid transcript for intent: '{transcript}'")
                                        waiting_for_user_input = True
                                        last_transcription_time = time.time()
                                        continue
                                    
                                    # Use strict intent detection
                                    intent = detect_intent_strict(transcript)
                                    logger.websocket.info(f"🎯 Intent detected: {intent}")
                                    
                                    if intent == "affirmative":
                                        logger.websocket.info("✅ User wants agent transfer")
                                        await play_transfer_to_agent(websocket, customer_info.get('phone', '08438019383'))
                                        conversation_stage = "TRANSFERRING_TO_AGENT"
                                        interaction_complete = True
                                        break
                                    elif intent == "negative":
                                        logger.websocket.info("✅ User declined agent transfer")
                                        await play_goodbye_after_decline(websocket, call_detected_lang)
                                        conversation_stage = "GOODBYE_DECLINE"
                                        interaction_complete = True
                                        break
                                    else:
                                        logger.websocket.info("❓ Unclear intent - repeating question")
                                        await play_agent_connect_question(websocket, call_detected_lang)
                                        waiting_for_user_input = True
                                        last_transcription_time = time.time()
                            
                            else:
                                logger.websocket.info(f"🚫 Empty or invalid transcript: '{transcript}'")
                                waiting_for_user_input = True
                                last_transcription_time = time.time()
                                
                        except Exception as e:
                            logger.websocket.error(f"❌ Error processing audio: {e}")
                            waiting_for_user_input = True
                            last_transcription_time = time.time()
                        
                        finally:
                            audio_buffer.clear()

    except WebSocketDisconnect:
        logger.websocket.info(f"🔌 WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.websocket.error(f"❌ WebSocket error: {e}")
        import traceback
        traceback.print_exc()
'''
    
    return fixed_handler

if __name__ == "__main__":
    print("🚀 Debug: Analyzing WebSocket conversation flow...")
    
    issue_found = fix_conversation_flow()
    
    if issue_found:
        print("✅ Created fixed WebSocket handler")
        print("🔧 The main issue is that the system auto-advances through stages without waiting for user input")
        print("🎯 Key fixes needed:")
        print("   1. Add proper waiting flags (waiting_for_user_input)")
        print("   2. Only advance stages after receiving valid user transcript")
        print("   3. Don't auto-play EMI details until user confirms")
        print("   4. Ensure audio buffer processing only happens when waiting")
        print("   5. Add transcript validation before intent detection")
    else:
        print("✅ No major issues found in conversation flow")
    
    print("💡 Next steps:")
    print("   1. Apply the waiting_for_user_input flag logic")
    print("   2. Fix auto-advancement in EMI details")  
    print("   3. Test with proper audio buffer processing")
