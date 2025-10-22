#!/usr/bin/env python3
"""
Environment Test Script for Voice Bot Agent Transfer Issue
Run this to verify your environment setup before testing the main application
"""

import os
import sys
from dotenv import load_dotenv

def test_environment():
    """Test environment variables and basic functionality"""
    print("🧪 [ENV_TEST] Testing Voice Bot Environment Setup")
    print("=" * 60)
    
    # Load environment variables
    load_dotenv()
    
    # Test 1: Check critical environment variables
    print("\n1. 🔍 Checking Environment Variables:")
    critical_vars = [
        "CLAUDE_INTENT_MODEL_ID",
        "AWS_ACCESS_KEY_ID", 
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "SARVAM_API_KEY",
        "EXOTEL_SID",
        "EXOTEL_TOKEN"
    ]
    
    missing_vars = []
    for var in critical_vars:
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if "KEY" in var or "TOKEN" in var:
                masked_value = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
                print(f"   ✅ {var}: {masked_value}")
            else:
                print(f"   ✅ {var}: {value}")
        else:
            print(f"   ❌ {var}: NOT SET")
            missing_vars.append(var)
    
    if missing_vars:
        print(f"\n⚠️  WARNING: Missing environment variables: {', '.join(missing_vars)}")
        print("   Please check your .env file!")
    else:
        print("\n✅ All critical environment variables are set!")
    
    # Test 2: Test intent detection functions
    print("\n2. 🔍 Testing Intent Detection Functions:")
    
    try:
        # Import the functions (adjust import path as needed)
        sys.path.append('.')
        from main import detect_intent
        
        test_cases = [
            ("Yes", "affirmative"),
            ("yes", "affirmative"), 
            ("Yeah", "affirmative"),
            ("Sure", "affirmative"),
            ("Okay", "affirmative"),
            ("No", "negative"),
            ("Not now", "negative"),
            ("Agent", "agent_transfer"),
            ("Transfer me", "agent_transfer"),
            ("What", "confused"),
            ("Random text", "unknown")
        ]
        
        print("   Testing fallback intent detection:")
        all_passed = True
        for test_input, expected in test_cases:
            result = detect_intent(test_input)
            status = "✅" if result == expected else "❌"
            print(f"   {status} '{test_input}' -> '{result}' (expected: '{expected}')")
            if result != expected:
                all_passed = False
        
        if all_passed:
            print("   ✅ All fallback intent detection tests passed!")
        else:
            print("   ⚠️  Some fallback intent detection tests failed!")
            
    except ImportError as e:
        print(f"   ❌ Could not import intent detection functions: {e}")
        print("   Make sure you're running this from the voice_bot directory")
    
    # Test 3: Test Claude connection
    print("\n3. 🔍 Testing Claude/Bedrock Connection:")
    
    try:
        from utils.bedrock_client import invoke_claude_model
        
        test_messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Classify this user response to 'Would you like to connect to an agent?': 'Yes'. Respond with only: affirmative, negative, or unclear."
                    }
                ]
            }
        ]
        
        print("   Attempting Claude API call...")
        response = invoke_claude_model(test_messages)
        print(f"   ✅ Claude API call successful!")
        print(f"   Response: '{response.strip()}'")
        
        if "affirmative" in response.lower():
            print("   ✅ Claude correctly identified 'Yes' as affirmative!")
        else:
            print("   ⚠️  Claude response unexpected - check the model configuration")
            
    except Exception as e:
        print(f"   ❌ Claude API call failed: {e}")
        print("   Check your AWS credentials and CLAUDE_INTENT_MODEL_ID")
    
    # Test 4: Summary and recommendations
    print("\n4. 📋 Summary and Recommendations:")
    
    if not missing_vars:
        print("   ✅ Environment setup looks good!")
        print("   ✅ Ready to test the voice bot with debug logging")
        print("\n   Next steps:")
        print("   1. Apply the debug patches from debug_patch_main.py")
        print("   2. Start your voice bot application")
        print("   3. Make a test call and say 'Yes' when asked about agent transfer")
        print("   4. Check the console logs for debug output")
    else:
        print("   ❌ Environment setup needs attention!")
        print("   Please fix the missing environment variables first")
    
    print("\n" + "=" * 60)
    print("🧪 [ENV_TEST] Environment test completed!")

if __name__ == "__main__":
    test_environment()
