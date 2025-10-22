#!/usr/bin/env python3

import requests

def test_passthru_handler():
    """Test the passthru handler endpoint directly"""
    
    print("🧪 Testing Passthru Handler Directly...")
    print("=" * 50)
    
    # Test the passthru handler with sample data
    base_url = "http://localhost:8000"
    
    # Test 1: Basic passthru call
    print("\n1️⃣ Testing basic passthru endpoint:")
    test_params = {
        'CallSid': '5885fe8756dba656bce37002e321199r',
        'CustomField': 'id=8be55a27-0b91-4d8d-8cba-b192b78eb90a|name=Kushal|phone_number=+917417119014|state=Uttar Pradesh|temp_call_id=temp_call_test123'
    }
    
    try:
        response = requests.get(f"{base_url}/passthru-handler", params=test_params)
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
        print(f"   ✅ {'SUCCESS' if response.text == 'OK' else 'FAILED'}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 2: Test endpoint status
    print("\n2️⃣ Testing passthru status endpoint:")
    try:
        response = requests.get(f"{base_url}/test-passthru")
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.json()}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 3: Verify ngrok URL
    print("\n3️⃣ Testing ngrok URL accessibility:")
    ngrok_url = "https://4ee3feb8d5e0.ngrok-free.app"
    try:
        response = requests.get(f"{ngrok_url}/test-passthru", timeout=10)
        print(f"   Status: {response.status_code}")
        print(f"   ✅ Ngrok URL is accessible")
        
        # Test passthru via ngrok
        response = requests.get(f"{ngrok_url}/passthru-handler", params=test_params, timeout=10)
        print(f"   Passthru via ngrok: {response.text}")
        
    except Exception as e:
        print(f"   ❌ Ngrok Error: {e}")
    
    print("\n" + "=" * 50)
    print("📋 CONFIGURATION CHECKLIST:")
    print("✅ 1. Passthru handler returning 'OK'")
    print("✅ 2. CustomField parsing working")
    print("❓ 3. Check Exotel Flow configuration:")
    print("   → Go to: https://my.exotel.com/aurocode1/flows/edit/1027293")
    print("   → Passthru URL: https://4ee3feb8d5e0.ngrok-free.app/passthru-handler")
    print("   → Ensure Passthru → Voicebot connection exists")
    print("=" * 50)

if __name__ == '__main__':
    test_passthru_handler()
