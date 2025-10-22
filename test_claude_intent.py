#!/usr/bin/env python3
"""
Test Claude Intent Detection
Tests the AWS Bedrock Claude integration for intent classification
"""

import os
import sys
from dotenv import load_dotenv

# Add the current directory to path so we can import utils
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.bedrock_client import get_intent_from_text

# Load environment variables
load_dotenv()

def test_intent_detection():
    """Test Claude intent detection with sample messages"""
    
    print("🧠 Testing Claude Intent Detection")
    print("=" * 50)
    
    # Test cases for different intents
    test_cases = [
        {
            "message": "What is my EMI amount?",
            "expected": "emi",
            "chat_history": [{"sender": "user", "message": "What is my EMI amount?"}]
        },
        {
            "message": "When is my next payment due?",
            "expected": "emi", 
            "chat_history": [{"sender": "user", "message": "When is my next payment due?"}]
        },
        {
            "message": "What is my account balance?",
            "expected": "balance",
            "chat_history": [{"sender": "user", "message": "What is my account balance?"}]
        },
        {
            "message": "How much loan amount do I have?",
            "expected": "loan",
            "chat_history": [{"sender": "user", "message": "How much loan amount do I have?"}]
        },
        {
            "message": "What is the weather today?",
            "expected": "unclear",
            "chat_history": [{"sender": "user", "message": "What is the weather today?"}]
        },
        {
            "message": "I want to pay my installment",
            "expected": "emi",
            "chat_history": [{"sender": "user", "message": "I want to pay my installment"}]
        },
        {
            "message": "Check my available credit",
            "expected": "balance",
            "chat_history": [{"sender": "user", "message": "Check my available credit"}]
        },
        {
            "message": "What is my loan interest rate?",
            "expected": "loan",
            "chat_history": [{"sender": "user", "message": "What is my loan interest rate?"}]
        }
    ]
    
    print(f"Testing {len(test_cases)} intent classification scenarios...\n")
    
    passed = 0
    failed = 0
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test {i}: '{test_case['message']}'")
        
        try:
            # Call the Claude intent detection
            detected_intent = get_intent_from_text(test_case['chat_history'])
            
            # Check if it matches expected
            if detected_intent == test_case['expected']:
                print(f"✅ PASS - Detected: '{detected_intent}' (Expected: '{test_case['expected']}')")
                passed += 1
            else:
                print(f"❌ FAIL - Detected: '{detected_intent}' (Expected: '{test_case['expected']}')")
                failed += 1
                
        except Exception as e:
            print(f"❌ ERROR - Exception occurred: {e}")
            failed += 1
            
        print()
    
    # Summary
    print("=" * 50)
    print("🎯 Test Results Summary:")
    print(f"✅ Passed: {passed}/{len(test_cases)}")
    print(f"❌ Failed: {failed}/{len(test_cases)}")
    print(f"📊 Success Rate: {(passed/len(test_cases)*100):.1f}%")
    
    if passed == len(test_cases):
        print("🎉 All tests passed! Claude intent detection is working correctly.")
        return True
    else:
        print("⚠️  Some tests failed. Please check AWS Bedrock configuration.")
        return False

def check_aws_credentials():
    """Check if AWS credentials are configured"""
    print("🔑 Checking AWS Credentials...")
    
    # Check environment variables
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    aws_region = os.getenv('AWS_DEFAULT_REGION', 'eu-north-1')
    
    if aws_access_key and aws_secret_key:
        print(f"✅ AWS credentials found (Region: {aws_region})")
        return True
    else:
        print("❌ AWS credentials not found in environment variables")
        print("Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
        return False

def main():
    """Main test function"""
    print("🧪 Claude Intent Detection Test Suite")
    print("=" * 50)
    
    # Check AWS credentials first
    if not check_aws_credentials():
        print("❌ Cannot run tests without AWS credentials")
        return False
    
    print()
    
    # Run intent detection tests
    return test_intent_detection()

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
