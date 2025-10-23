#!/usr/bin/env python3
"""
Test script to verify CALL_IN_PROGRESS status updates work correctly.
"""

import requests
import json
import time

def test_call_in_progress():
    """Test the call-in-progress functionality"""
    
    # Test endpoints
    base_url = "http://localhost:8000"
    
    print("🧪 Testing Call-In-Progress Status Updates")
    print("=" * 50)
    
    # Test 1: Test endpoint
    print("\n1. Testing /api/test-call-in-progress endpoint...")
    test_data = {
        "call_sid": "test_call_123"
    }
    
    try:
        response = requests.post(
            f"{base_url}/api/test-call-in-progress",
            json=test_data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Test endpoint response: {result}")
        else:
            print(f"❌ Test endpoint failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Test endpoint error: {e}")
    
    # Test 2: Force endpoint
    print("\n2. Testing /api/force-call-in-progress endpoint...")
    force_data = {
        "call_sid": "test_call_456"
    }
    
    try:
        response = requests.post(
            f"{base_url}/api/force-call-in-progress",
            json=force_data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Force endpoint response: {result}")
        else:
            print(f"❌ Force endpoint failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Force endpoint error: {e}")
    
    # Test 3: Manual status update
    print("\n3. Testing /api/update-call-status endpoint...")
    manual_data = {
        "call_sid": "test_call_789",
        "status": "call_in_progress",
        "message": "Manual test - Call in progress"
    }
    
    try:
        response = requests.post(
            f"{base_url}/api/update-call-status",
            json=manual_data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Manual update response: {result}")
        else:
            print(f"❌ Manual update failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Manual update error: {e}")
    
    print("\n" + "=" * 50)
    print("🎯 Test Summary:")
    print("- All endpoints should return success responses")
    print("- Check your server logs for status update messages")
    print("- Use these endpoints to manually trigger CALL_IN_PROGRESS status")
    print("\n💡 Usage:")
    print("1. When a call is answered, use /api/force-call-in-progress")
    print("2. Or use /api/update-call-status with status='call_in_progress'")
    print("3. Check the dashboard to see 'In Progress' status")

if __name__ == "__main__":
    test_call_in_progress()
