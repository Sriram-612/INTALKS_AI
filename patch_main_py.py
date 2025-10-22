#!/usr/bin/env python3
"""
Patch Script for main.py
========================
This script will make the necessary changes to integrate enhanced voice processing
into your existing main.py file.

Usage:
    python patch_main_py.py
"""

import os
import shutil
from pathlib import Path

def patch_main_py():
    """Apply patches to main.py"""
    print("🔧 Patching main.py for Enhanced Voice Processing")
    print("=" * 60)
    
    main_py_path = Path("main.py")
    
    if not main_py_path.exists():
        print("❌ main.py not found in current directory")
        return False
    
    # Create backup
    backup_path = Path("main.py.backup")
    shutil.copy2(main_py_path, backup_path)
    print(f"✅ Backup created: {backup_path}")
    
    # Read current content
    with open(main_py_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Patch 1: Add import (if not already present)
    import_line = "from enhanced_main_integration import enhanced_audio_processing, get_enhanced_greeting"
    if import_line not in content:
        # Find the line with redis_session import
        redis_import = "from utils.redis_session import (init_redis, redis_manager,"
        if redis_import in content:
            content = content.replace(
                "from utils.redis_session import (init_redis, redis_manager,\n                                 generate_websocket_session_id)",
                "from utils.redis_session import (init_redis, redis_manager,\n                                 generate_websocket_session_id)\nfrom enhanced_main_integration import enhanced_audio_processing, get_enhanced_greeting"
            )
            print("✅ Added enhanced processing import")
        else:
            print("⚠️ Could not find redis_session import to add enhanced import after")
    else:
        print("✅ Enhanced processing import already present")
    
    # Patch 2: Enhance AI Agent Mode processing
    original_ai_code = '''                                # Handle AI agent conversation
                                should_continue = await handle_ai_agent_conversation(
                                    websocket, transcript, call_sid, customer_info, call_detected_lang
                                )'''
    
    enhanced_ai_code = '''                                # Enhanced AI agent conversation with improved processing
                                try:
                                    logger.websocket.info("🎙️ Using Enhanced AI Agent Processing")
                                    
                                    # Use enhanced audio processing for AI agent mode
                                    result = await enhanced_audio_processing(
                                        audio_bytes=audio_buffer,
                                        customer_info=customer_info,
                                        conversation_stage="AI_AGENT_MODE"
                                    )
                                    
                                    if result["success"]:
                                        enhanced_transcript = result["transcript"]
                                        response_text = result["response_text"]
                                        response_audio = result["response_audio"]
                                        
                                        logger.websocket.info(f"🎤 Enhanced STT: '{enhanced_transcript}'")
                                        logger.websocket.info(f"🤖 Enhanced Response: '{response_text}'")
                                        
                                        # Send enhanced response audio to WebSocket
                                        if response_audio:
                                            import base64
                                            audio_b64 = base64.b64encode(response_audio).decode()
                                            await websocket.send_text(json.dumps({
                                                "type": "media",
                                                "media": {"payload": audio_b64}
                                            }))
                                            logger.websocket.info("🔊 Enhanced audio response sent")
                                        
                                        should_continue = True
                                        # Check if conversation should end
                                        if "goodbye" in response_text.lower() or "transfer" in response_text.lower():
                                            should_continue = False
                                    else:
                                        logger.websocket.error(f"Enhanced processing failed: {result['error']}")
                                        # Fallback to original AI agent handler
                                        should_continue = await handle_ai_agent_conversation(
                                            websocket, transcript, call_sid, customer_info, call_detected_lang
                                        )
                                        
                                except Exception as e:
                                    logger.websocket.error(f"❌ Enhanced AI processing error: {e}")
                                    # Fallback to original handler
                                    should_continue = await handle_ai_agent_conversation(
                                        websocket, transcript, call_sid, customer_info, call_detected_lang
                                    )'''
    
    if original_ai_code in content:
        content = content.replace(original_ai_code, enhanced_ai_code)
        print("✅ Enhanced AI agent processing code")
    else:
        print("⚠️ Could not find exact AI agent code to replace")
        print("   You may need to manually integrate the enhanced processing")
    
    # Write patched content
    with open(main_py_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("\n🎉 Patching completed!")
    print("=" * 60)
    print("✅ main.py has been enhanced with:")
    print("   - Enhanced voice processing import")
    print("   - Improved AI agent conversation handling")
    print("   - Anushka voice (female) integration")
    print("   - Better Claude conversation management")
    print()
    print("🚀 Your enhanced voice system is ready!")
    print("   Run: python main.py")
    print("   The AI agent mode will now use enhanced processing")
    print()
    print(f"📁 Backup saved as: {backup_path}")
    print("   (Restore with: cp main.py.backup main.py)")
    
    return True

def show_manual_instructions():
    """Show manual integration instructions"""
    print("\n📋 Manual Integration Instructions")
    print("=" * 60)
    print("If the automatic patching didn't work, follow these steps:")
    print()
    print("1. Add this import near the top of main.py (around line 67):")
    print("   from enhanced_main_integration import enhanced_audio_processing, get_enhanced_greeting")
    print()
    print("2. Find the AI_AGENT_MODE section (around line 1440) and replace:")
    print("   # Handle AI agent conversation")
    print("   should_continue = await handle_ai_agent_conversation(...)")
    print()
    print("3. With enhanced processing code (see enhanced_main_integration.py for details)")
    print()
    print("🎯 The key benefit: AI agent mode will use enhanced voice processing")
    print("   with Anushka voice and better conversation management!")

if __name__ == "__main__":
    try:
        success = patch_main_py()
        if not success:
            show_manual_instructions()
    except Exception as e:
        print(f"❌ Error during patching: {e}")
        show_manual_instructions()
