#!/usr/bin/env python3
"""
Comprehensive test script to verify CALL_IN_PROGRESS status generation.
This script tests all the mechanisms for generating the call-in-progress status.
"""

import requests
import json
import time
import sys

def test_server_connection():
    """Test if server is running"""
    try:
        response = requests.get("http://localhost:8000/", timeout=5)
        return response.status_code == 200
    except:
        return False

def test_manual_status_update():
    """Test manual status update endpoint"""
    print("\n🧪 Testing Manual Status Update...")
    
    test_data = {
        "call_sid": "test_manual_call_123",
        "status": "call_in_progress",
        "message": "Manual test - Call in progress"
    }
    
    try:
        response = requests.post(
            "http://localhost:8000/api/update-call-status",
            json=test_data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Manual status update: {result}")
            return True
        else:
            print(f"❌ Manual status update failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Manual status update error: {e}")
        return False

def test_force_status_update():
    """Test force status update endpoint"""
    print("\n🔧 Testing Force Status Update...")
    
    test_data = {
        "call_sid": "test_force_call_456"
    }
    
    try:
        response = requests.post(
            "http://localhost:8000/api/force-call-in-progress",
            json=test_data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Force status update: {result}")
            return True
        else:
            print(f"❌ Force status update failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Force status update error: {e}")
        return False

def test_trigger_status_update():
    """Test trigger status update endpoint"""
    print("\n🚀 Testing Trigger Status Update...")
    
    test_data = {
        "call_sid": "test_trigger_call_789"
    }
    
    try:
        response = requests.post(
            "http://localhost:8000/api/trigger-call-in-progress",
            json=test_data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Trigger status update: {result}")
            return True
        else:
            print(f"❌ Trigger status update failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Trigger status update error: {e}")
        return False

def test_webhook_simulation():
    """Test webhook simulation for in-progress status"""
    print("\n📞 Testing Webhook Simulation...")
    
    # Simulate Exotel webhook with in-progress status
    webhook_data = {
        "CallSid": "test_webhook_call_999",
        "CallStatus": "in-progress",
        "CallDuration": "0"
    }
    
    try:
        response = requests.post(
            "http://localhost:8000/exotel-webhook",
            data=webhook_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Webhook simulation: {result}")
            return True
        else:
            print(f"❌ Webhook simulation failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Webhook simulation error: {e}")
        return False

def test_recent_calls():
    """Test getting recent calls to verify status updates"""
    print("\n📋 Testing Recent Calls...")
    
    try:
        response = requests.get("http://localhost:8000/api/recent-calls")
        
        if response.status_code == 200:
            calls = response.json()
            print(f"✅ Recent calls retrieved: {len(calls)} calls")
            
            # Look for our test calls
            for call in calls[:5]:  # Check first 5 calls
                print(f"   Call: {call.get('call_sid')} - Status: {call.get('status')}")
            
            return True
        else:
            print(f"❌ Recent calls failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Recent calls error: {e}")
        return False

def main():
    """Run comprehensive tests"""
    print("🧪 COMPREHENSIVE CALL-IN-PROGRESS STATUS TEST")
    print("=" * 60)
    
    # Test 1: Server connection
    print("\n1. Testing server connection...")
    if not test_server_connection():
        print("❌ Server is not running. Please start the server first:")
        print("   python main.py")
        return False
    print("✅ Server is running")
    
    # Test 2: Manual status update
    test_manual_status_update()
    
    # Test 3: Force status update
    test_force_status_update()
    
    # Test 4: Trigger status update
    test_trigger_status_update()
    
    # Test 5: Webhook simulation
    test_webhook_simulation()
    
    # Test 6: Recent calls
    test_recent_calls()
    
    print("\n" + "=" * 60)
    print("🎯 TEST SUMMARY:")
    print("- All endpoints should return success responses")
    print("- Check your server logs for status update messages")
    print("- Use these endpoints to manually trigger CALL_IN_PROGRESS status")
    
    print("\n💡 USAGE INSTRUCTIONS:")
    print("1. When a call is answered, use /api/trigger-call-in-progress")
    print("2. Or use /api/force-call-in-progress for immediate status update")
    print("3. Check the dashboard to see 'In Progress' status")
    print("4. Monitor server logs for status update confirmations")
    
    print("\n🔧 MANUAL TRIGGER COMMANDS:")
    print("curl -X POST http://localhost:8000/api/trigger-call-in-progress \\")
    print("  -H 'Content-Type: application/json' \\")
    print("  -d '{\"call_sid\": \"your_call_sid\"}'")
    
    return True

if __name__ == "__main__":
    main()
