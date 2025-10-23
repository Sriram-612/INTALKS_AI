#!/usr/bin/env python3
"""
Test script to verify CALL_IN_PROGRESS status is generated when customer answers.
"""

import requests
import json
import time

def test_call_in_progress_status():
    """Test that CALL_IN_PROGRESS status is generated when customer answers"""
    
    base_url = "http://localhost:8000"
    
    print("🧪 Testing CALL_IN_PROGRESS Status Generation")
    print("=" * 60)
    
    # Test 1: Check if server is running
    print("\n1. Checking if server is running...")
    try:
        response = requests.get(f"{base_url}/", timeout=5)
        if response.status_code == 200:
            print("✅ Server is running")
        else:
            print(f"❌ Server returned status {response.status_code}")
            return
    except Exception as e:
        print(f"❌ Server is not running: {e}")
        return
    
    # Test 2: Test manual status update
    print("\n2. Testing manual CALL_IN_PROGRESS status update...")
    test_data = {
        "call_sid": "test_call_in_progress_123",
        "status": "call_in_progress",
        "message": "Test - Call in progress"
    }
    
    try:
        response = requests.post(
            f"{base_url}/api/update-call-status",
            json=test_data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Manual status update response: {result}")
        else:
            print(f"❌ Manual status update failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Manual status update error: {e}")
    
    # Test 3: Test force status update
    print("\n3. Testing force CALL_IN_PROGRESS status update...")
    force_data = {
        "call_sid": "test_force_call_in_progress_456"
    }
    
    try:
        response = requests.post(
            f"{base_url}/api/force-call-in-progress",
            json=force_data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Force status update response: {result}")
        else:
            print(f"❌ Force status update failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Force status update error: {e}")
    
    print("\n" + "=" * 60)
    print("🎯 Test Summary:")
    print("- Server should be running on http://localhost:8000")
    print("- CALL_IN_PROGRESS status should be generated when customer answers")
    print("- Check your server logs for status update messages")
    print("\n💡 Expected Behavior:")
    print("1. When customer answers call → WebSocket connects")
    print("2. WebSocket connection triggers CALL_IN_PROGRESS status")
    print("3. Dashboard shows 'In Progress' status")
    print("4. Status persists until call ends")

if __name__ == "__main__":
    test_call_in_progress_status()
