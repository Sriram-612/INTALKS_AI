#!/usr/bin/env python3
"""
Quick TTS test to verify the fixes work correctly
"""
import asyncio
import os
from dotenv import load_dotenv
from utils.production_asr import ProductionSarvamHandler
from utils.logger import setup_application_logging, logger

# Load environment variables
load_dotenv()

async def test_tts():
    """Test TTS functionality with the fixed code"""
    
    # Setup logging
    setup_application_logging()
    
    # Initialize Sarvam handler
    sarvam_api_key = os.getenv("SARVAM_API_KEY")
    if not sarvam_api_key:
        print("❌ SARVAM_API_KEY not found in environment variables")
        return
    
    print(f"🔑 Using API key: {sarvam_api_key[:8]}...")
    
    handler = ProductionSarvamHandler(sarvam_api_key)
    
    # Test TTS with Hindi text
    test_text = "नमस्ते, मैं प्रिया हूं। क्या आप से बात कर सकते हैं?"
    test_lang = "hi-IN"
    
    print(f"🔊 Testing TTS with text: '{test_text}' in language: {test_lang}")
    
    try:
        # Call the TTS function
        audio_bytes = await handler.synthesize_tts(test_text, test_lang)
        
        if audio_bytes and len(audio_bytes) > 0:
            print(f"✅ TTS SUCCESS! Generated {len(audio_bytes)} bytes of audio")
            print(f"📊 Audio preview: {audio_bytes[:20].hex()}...")
            
            # Save to file for testing
            with open("test_tts_output.raw", "wb") as f:
                f.write(audio_bytes)
            print("💾 Audio saved to test_tts_output.raw")
            
        else:
            print("❌ TTS FAILED! No audio data returned")
            
    except Exception as e:
        print(f"❌ TTS ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_tts())
