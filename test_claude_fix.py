#!/usr/bin/env python3
"""
Quick test to verify Claude message formatting fix
"""

import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from test_speech_to_speech_pipeline import SpeechToSpeechTester

async def test_claude_fix():
    """Test Claude message formatting fix"""
    print("🧪 Testing Claude Message Format Fix")
    print("=" * 50)
    
    try:
        tester = SpeechToSpeechTester()
        
        # Test with a simple input
        test_input = "Hello, I need help with my loan payment"
        print(f"🎯 Testing input: '{test_input}'")
        
        # Run just the Claude processing part
        transcript = test_input  # Simulate transcript
        
        print("🤖 Testing Claude LLM processing...")
        response = await tester.process_with_claude(transcript)
        
        if response:
            print(f"✅ Claude Response: '{response}'")
            print("✅ Test PASSED - Claude message formatting works!")
        else:
            print("❌ Test FAILED - No response from Claude")
            
    except Exception as e:
        print(f"❌ Test FAILED with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_claude_fix())
