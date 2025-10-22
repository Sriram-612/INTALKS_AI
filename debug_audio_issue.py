#!/usr/bin/env python3
"""
Debug script to identify the exact audio streaming issue
Run this to test the TTS and WebSocket streaming components separately
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.production_asr import ProductionSarvamHandler

async def test_tts_generation():
    """Test if TTS generation is working"""
    print("🧪 Testing TTS Generation...")
    
    try:
        SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
        if not SARVAM_API_KEY:
            print("❌ SARVAM_API_KEY not found in environment")
            return False
            
        handler = ProductionSarvamHandler(SARVAM_API_KEY)
        
        # Test text
        test_text = "If you are facing difficulties, we have options like part payments or revised EMI plans. Would you like me to connect you to one of our agents to assist you better?"
        
        print(f"🔤 Testing TTS for: {test_text[:50]}...")
        
        # Generate TTS
        audio_bytes = await handler.synthesize_tts(test_text, "en-IN")
        
        if audio_bytes:
            print(f"✅ TTS Generation SUCCESS: {len(audio_bytes)} bytes generated")
            return True
        else:
            print("❌ TTS Generation FAILED: No audio bytes returned")
            return False
            
    except Exception as e:
        print(f"❌ TTS Generation ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_websocket_simulation():
    """Simulate WebSocket message creation"""
    print("\n🧪 Testing WebSocket Message Creation...")
    
    try:
        import base64
        
        # Create dummy audio data
        dummy_audio = b'\x00\x01' * 1600  # 3200 bytes of dummy audio
        
        # Test base64 encoding
        b64_chunk = base64.b64encode(dummy_audio).decode("utf-8")
        
        # Create WebSocket message
        response_msg = {
            "event": "media",
            "media": {"payload": b64_chunk}
        }
        
        print(f"✅ WebSocket Message Creation SUCCESS")
        print(f"   - Audio bytes: {len(dummy_audio)}")
        print(f"   - Base64 length: {len(b64_chunk)}")
        print(f"   - Message structure: {list(response_msg.keys())}")
        
        return True
        
    except Exception as e:
        print(f"❌ WebSocket Message Creation ERROR: {e}")
        return False

def analyze_current_issue():
    """Analyze the current issue based on symptoms"""
    print("\n🔍 ISSUE ANALYSIS:")
    print("==================")
    print("SYMPTOM: 'Converting agent connect question...' shows in terminal but no voice plays")
    print()
    print("POSSIBLE CAUSES:")
    print("1. ✅ TTS Generation: Working (text appears in logs)")
    print("2. ❓ Audio Streaming: Likely failing silently")
    print("3. ❓ WebSocket Connection: May be disconnected")
    print("4. ❓ Audio Format: May be incompatible with Exotel")
    print()
    print("RECOMMENDED FIXES:")
    print("1. Remove WebSocket state checking in stream_audio_to_websocket()")
    print("2. Add more detailed logging to audio streaming")
    print("3. Use 'continue' instead of 'break' on send failures")
    print("4. Test with simpler audio streaming function")

async def main():
    """Run all diagnostic tests"""
    print("🚀 VOICE BOT AUDIO DIAGNOSTIC TOOL")
    print("===================================")
    
    # Test TTS generation
    tts_success = await test_tts_generation()
    
    # Test WebSocket message creation
    ws_success = await test_websocket_simulation()
    
    # Analyze the issue
    analyze_current_issue()
    
    print("\n📋 SUMMARY:")
    print(f"   TTS Generation: {'✅ WORKING' if tts_success else '❌ FAILED'}")
    print(f"   WebSocket Messages: {'✅ WORKING' if ws_success else '❌ FAILED'}")
    
    if tts_success and ws_success:
        print("\n🎯 CONCLUSION: The issue is likely in the WebSocket streaming logic in main.py")
        print("   Recommended: Apply the fix from audio_stream_fix.py")
    else:
        print("\n🎯 CONCLUSION: There are fundamental issues with TTS or message creation")

if __name__ == "__main__":
    asyncio.run(main())
