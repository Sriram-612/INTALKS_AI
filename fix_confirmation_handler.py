#!/usr/bin/env python3
"""
Fix the missing WAITING_FOR_CONFIRMATION handler in main.py

This adds the critical missing transcript processing logic for when users respond to the initial greeting.
"""

def apply_confirmation_handler_fix():
    """Apply the fix for missing WAITING_FOR_CONFIRMATION handler."""
    
    with open('/home/cyberdude/Documents/Projects/voice/main.py', 'r') as f:
        content = f.read()
    
    # Find the pattern where we need to insert the WAITING_FOR_CONFIRMATION handler
    pattern = '''                        if transcript:
                            if conversation_stage == "WAITING_FOR_LANG_DETECT":'''
    
    # Replacement with the new confirmation handler
    replacement = '''                        if transcript:
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
                                    logger.log_call_event("EMI_DETAILS_SENT", call_sid, customer_info['name'], {"language": call_detected_lang})
                                except Exception as e:
                                    logger.websocket.error(f"❌ Error playing EMI details: {e}")
                                    logger.log_call_event("EMI_DETAILS_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                            
                            elif conversation_stage == "WAITING_FOR_LANG_DETECT":'''
    
    # Apply the fix to the first occurrence only
    if pattern in content:
        content = content.replace(pattern, replacement, 1)  # Replace only first occurrence
        print("✅ Applied WAITING_FOR_CONFIRMATION handler fix")
        
        # Write the fixed content back
        with open('/home/cyberdude/Documents/Projects/voice/main.py', 'w') as f:
            f.write(content)
        
        print("✅ File updated successfully")
        return True
    else:
        print("❌ Pattern not found - fix may have already been applied")
        return False

if __name__ == "__main__":
    print("🚀 Applying WebSocket confirmation handler fix...")
    
    success = apply_confirmation_handler_fix()
    
    if success:
        print("🎉 Fix applied successfully!")
        print("📋 What was fixed:")
        print("   • Added missing WAITING_FOR_CONFIRMATION transcript handler")
        print("   • User responses to initial greeting are now processed")
        print("   • EMI details will only play after user confirms")
        print("   • Language detection happens during confirmation")
        print("")
        print("🔄 Please restart the server to test the fix")
    else:
        print("⚠️  Fix not applied - check if it's already been applied")
