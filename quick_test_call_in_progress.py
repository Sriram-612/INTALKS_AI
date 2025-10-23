#!/usr/bin/env python3
"""
Quick test to trigger CALL_IN_PROGRESS status immediately.
"""

import requests
import json

def quick_test():
    """Quick test of CALL_IN_PROGRESS status"""
    
    print("🚀 Quick CALL_IN_PROGRESS Test")
    print("=" * 40)
    
    # Test data
    call_sid = "test_quick_call_123"
    
    # Test the trigger endpoint
    print(f"\n🧪 Testing trigger endpoint for call: {call_sid}")
    
    try:
        response = requests.post(
            "http://localhost:8000/api/trigger-call-in-progress",
            json={"call_sid": call_sid},
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ SUCCESS: {result}")
            print(f"   Status: {result.get('status', 'unknown')}")
            print(f"   Message: {result.get('message', 'No message')}")
        else:
            print(f"❌ FAILED: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
    
    print("\n" + "=" * 40)
    print("💡 If successful, check your dashboard for 'In Progress' status")
    print("💡 Check server logs for status update confirmations")

if __name__ == "__main__":
    quick_test()
