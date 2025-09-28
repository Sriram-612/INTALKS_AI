#!/usr/bin/env python3
"""
Comprehensive Passthru Handler Test
Tests various scenarios to ensure the passthru handler is working correctly
"""
import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"

def test_passthru_scenarios():
    """Test different passthru handler scenarios"""
    
    print("🧪 PASSTHRU HANDLER COMPREHENSIVE TEST")
    print("=" * 60)
    
    test_cases = [
        {
            "name": "✅ Normal Call with All Parameters",
            "params": {
                "CallSid": "test_call_001",
                "CustomField": "id=customer-123|name=John Doe|phone_number=+919876543210|loan_id=LN001|amount=50000|due_date=2025-10-15|temp_call_id=temp_abc123"
            }
        },
        {
            "name": "⚠️ Call with Missing CustomField",
            "params": {
                "CallSid": "test_call_002"
            }
        },
        {
            "name": "❌ Call with No Parameters",
            "params": {}
        },
        {
            "name": "🔧 Call with Malformed CustomField", 
            "params": {
                "CallSid": "test_call_003",
                "CustomField": "invalid|format|no=equals"
            }
        },
        {
            "name": "📱 Call with Partial CustomField",
            "params": {
                "CallSid": "test_call_004", 
                "CustomField": "name=Jane Smith|temp_call_id=temp_def456"
            }
        }
    ]
    
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. {test_case['name']}")
        print("-" * 50)
        
        # Make the request
        try:
            response = requests.get(f"{BASE_URL}/passthru-handler", params=test_case['params'])
            
            # Check response
            status_code = response.status_code
            content = response.text
            
            print(f"   📡 Request: {response.url}")
            print(f"   📊 Status Code: {status_code}")
            print(f"   📝 Response: '{content}'")
            
            # Verify expected behavior
            if status_code == 200 and content.strip() == "OK":
                print(f"   ✅ PASS: Correctly returned 'OK'")
                results.append(True)
            else:
                print(f"   ❌ FAIL: Expected '200 OK', got '{status_code} {content}'")
                results.append(False)
                
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            results.append(False)
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    print(f"✅ Tests Passed: {passed}/{total}")
    print(f"❌ Tests Failed: {total - passed}/{total}")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED! Passthru handler is working correctly.")
    else:
        print("⚠️ Some tests failed. Check the implementation.")
    
    return passed == total

def test_passthru_response_format():
    """Test that the response format is correct for Exotel"""
    print("\n🔍 TESTING RESPONSE FORMAT FOR EXOTEL COMPATIBILITY")
    print("=" * 60)
    
    response = requests.get(f"{BASE_URL}/passthru-handler?CallSid=format_test")
    
    print(f"Response Status: {response.status_code}")
    print(f"Response Headers: {dict(response.headers)}")
    print(f"Response Content: '{response.text}'")
    print(f"Content Type: {response.headers.get('content-type', 'Not specified')}")
    
    # Check if it's plain text
    content_type = response.headers.get('content-type', '')
    is_plain_text = 'text/plain' in content_type
    
    print(f"\n✅ Status Code 200: {'✓' if response.status_code == 200 else '✗'}")
    print(f"✅ Content is 'OK': {'✓' if response.text.strip() == 'OK' else '✗'}")
    print(f"✅ Content-Type is plain text: {'✓' if is_plain_text else '✗'}")
    
    return response.status_code == 200 and response.text.strip() == "OK" and is_plain_text

def main():
    print(f"🕐 Test started at: {datetime.now()}")
    
    try:
        # Test basic connectivity
        response = requests.get(f"{BASE_URL}/test-passthru")
        if response.status_code != 200:
            print("❌ Server not responding or not running")
            return
        
        print("✅ Server is running and accessible")
        
        # Run comprehensive tests
        basic_tests_passed = test_passthru_scenarios()
        format_tests_passed = test_passthru_response_format()
        
        print("\n" + "=" * 60)
        print("🎯 FINAL RESULT")
        print("=" * 60)
        
        if basic_tests_passed and format_tests_passed:
            print("🎉 PASSTHRU HANDLER IS WORKING PERFECTLY!")
            print("✅ All scenarios handled correctly")
            print("✅ Response format is Exotel-compatible")
            print("✅ Ready for production use")
        else:
            print("⚠️ Some issues found with passthru handler")
            if not basic_tests_passed:
                print("❌ Basic functionality tests failed")
            if not format_tests_passed:
                print("❌ Response format tests failed")
        
    except requests.exceptions.ConnectionError:
        print("❌ ERROR: Cannot connect to server. Make sure it's running on port 8000")
    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    main()
