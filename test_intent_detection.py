#!/usr/bin/env python3
"""
Debug Intent Detection in Production
Tests the complete intent detection pipeline
"""

import sys
import os
sys.path.append('/home/cyberdude/Documents/Projects/voice')

from utils.bedrock_client import invoke_claude_model

def test_intent_detection():
    print("🔍 Testing Intent Detection in Production")
    print("=" * 50)
    
    # Test Claude bedrock client directly
    try:
        print("\n1. Testing Claude Bedrock Client...")
        
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are classifying a user's short reply to this question: "
                            "'Would you like me to connect you to one of our agents to assist you better?'\n\n"
                            "User reply (language=hi-IN): 'जी हाँ'\n\n"
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
        
        result = invoke_claude_model(messages)
        print(f"✅ Claude Response: '{result}'")
        
    except Exception as e:
        print(f"❌ Claude Test Failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Test the main.py function
    try:
        print("\n2. Testing detect_intent_with_claude function...")
        
        from main import detect_intent_with_claude
        
        test_cases = [
            ("हाँ", "hi-IN", "affirmative"),
            ("जी हाँ", "hi-IN", "affirmative"),
            ("नहीं", "hi-IN", "negative"),
            ("yes", "en-IN", "affirmative"),
            ("no", "en-IN", "negative"),
            ("okay", "en-IN", "affirmative"),
            ("sure", "en-IN", "affirmative"),
        ]
        
        for transcript, lang, expected in test_cases:
            result = detect_intent_with_claude(transcript, lang)
            status = "✅" if result == expected else "❌"
            print(f"{status} '{transcript}' ({lang}) -> {result} (expected: {expected})")
            
    except Exception as e:
        print(f"❌ detect_intent_with_claude Test Failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Test empty transcript handling
    try:
        print("\n3. Testing Empty Transcript Handling...")
        
        empty_transcripts = ["", " ", "  ", None]
        
        for transcript in empty_transcripts:
            if transcript is None:
                print(f"None transcript -> Skipped (validation)")
            else:
                transcript_clean = transcript.strip() if transcript else ""
                if not transcript_clean or len(transcript_clean) < 2:
                    print(f"'{transcript}' -> Skipped (validation: too short)")
                else:
                    result = detect_intent_with_claude(transcript_clean, "hi-IN")
                    print(f"'{transcript}' -> {result}")
                    
    except Exception as e:
        print(f"❌ Empty Transcript Test Failed: {e}")

    print("\n" + "=" * 50)
    print("🎯 DIAGNOSIS:")
    print("If Claude tests pass but production fails, the issue is:")
    print("1. Empty/invalid transcripts from Sarvam ASR")
    print("2. Audio quality issues")
    print("3. Network connectivity to Sarvam API")
    print("\nCheck your production logs for 'TRANSCRIPT_TOO_SHORT' or 'TRANSCRIPT_NO_LETTERS'")

if __name__ == "__main__":
    test_intent_detection()
