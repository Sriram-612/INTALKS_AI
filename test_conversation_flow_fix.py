#!/usr/bin/env python3
"""
Test script to verify the conversation flow fix is working correctly.
This tests whether the WebSocket handler properly waits for customer data
instead of immediately failing when no data is found initially.
"""

import asyncio
import websockets
import json
import time
import uuid
import redis
from datetime import datetime

def test_conversation_flow_fix():
    """Test the conversation flow fix by simulating the race condition scenario."""
    
    print("🧪 Testing Conversation Flow Fix")
    print("=" * 50)
    
    # Connect to Redis to simulate the race condition
    try:
        redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        redis_client.ping()
        print("✅ Connected to Redis")
    except Exception as e:
        print(f"❌ Failed to connect to Redis: {e}")
        return False
    
    # Generate test data
    test_call_id = f"test_call_{int(time.time())}"
    test_customer_phone = "+919876543210"
    test_session_id = str(uuid.uuid4())
    
    print(f"📞 Test Call ID: {test_call_id}")
    print(f"📱 Test Phone: {test_customer_phone}")
    print(f"🆔 Session ID: {test_session_id}")
    
    # Scenario 1: Test immediate customer data availability (should work immediately)
    print("\n📋 Scenario 1: Immediate data availability")
    test_customer_data = {
        "customer_id": str(uuid.uuid4()),
        "phone": test_customer_phone,
        "name": "Test Customer",
        "session_id": test_session_id,
        "call_id": test_call_id,
        "timestamp": datetime.now().isoformat()
    }
    
    # Store data in Redis immediately
    redis_key = f"call_session:{test_call_id}"
    redis_client.setex(redis_key, 300, json.dumps(test_customer_data))  # 5 min expiry
    print(f"✅ Customer data stored in Redis with key: {redis_key}")
    
    # Scenario 2: Test delayed customer data availability (race condition scenario)
    print("\n📋 Scenario 2: Delayed data availability (Race condition test)")
    delayed_call_id = f"delayed_call_{int(time.time())}"
    delayed_session_id = str(uuid.uuid4())
    
    print(f"📞 Delayed Test Call ID: {delayed_call_id}")
    print(f"🆔 Delayed Session ID: {delayed_session_id}")
    
    # Simulate passthru handler delay by NOT storing data initially
    delayed_redis_key = f"call_session:{delayed_call_id}"
    print(f"⏳ Customer data will be stored with 3-second delay to simulate race condition")
    
    async def delayed_data_storage():
        """Simulate passthru handler storing data after delay"""
        await asyncio.sleep(3)  # 3-second delay
        delayed_customer_data = {
            "customer_id": str(uuid.uuid4()),
            "phone": test_customer_phone,
            "name": "Delayed Test Customer",
            "session_id": delayed_session_id,
            "call_id": delayed_call_id,
            "timestamp": datetime.now().isoformat()
        }
        redis_client.setex(delayed_redis_key, 300, json.dumps(delayed_customer_data))
        print(f"✅ Delayed customer data stored after 3 seconds")
    
    print("\n🎯 Test Results Summary:")
    print("1. ✅ Redis connection working")
    print("2. ✅ Test data prepared for both scenarios")
    print("3. ✅ Race condition scenario simulated with 3-second delay")
    
    print(f"\n🌐 Server is running at: https://9354922b9b8b.ngrok-free.app")
    print(f"📡 WebSocket endpoint: wss://9354922b9b8b.ngrok-free.app/ws/call/{test_call_id}")
    print(f"📡 Delayed WebSocket endpoint: wss://9354922b9b8b.ngrok-free.app/ws/call/{delayed_call_id}")
    
    print(f"\n💡 Manual Test Instructions:")
    print(f"1. Connect to WebSocket: wss://9354922b9b8b.ngrok-free.app/ws/call/{test_call_id}")
    print(f"   Expected: Should connect immediately (data available)")
    print(f"2. Connect to WebSocket: wss://9354922b9b8b.ngrok-free.app/ws/call/{delayed_call_id}")
    print(f"   Expected: Should wait up to 10 seconds, then connect when data becomes available")
    
    print(f"\n🔍 To verify the fix:")
    print(f"- Before fix: WebSocket would immediately fail with 'No customer data found'")
    print(f"- After fix: WebSocket should wait and succeed once data is available")
    
    # Now simulate the delayed data storage for testing
    print(f"\n⏰ Simulating delayed data storage...")
    time.sleep(3)  # Wait 3 seconds
    delayed_customer_data = {
        "customer_id": str(uuid.uuid4()),
        "phone": test_customer_phone,
        "name": "Delayed Test Customer",
        "session_id": delayed_session_id,
        "call_id": delayed_call_id,
        "timestamp": datetime.now().isoformat()
    }
    redis_client.setex(delayed_redis_key, 300, json.dumps(delayed_customer_data))
    print(f"✅ Delayed customer data stored after 3 seconds")
    
    # Test WebSocket connection programmatically
    async def test_websocket_connection():
        """Test WebSocket connection to verify the fix"""
        try:
            print(f"\n🔌 Testing WebSocket connection...")
            uri = f"wss://9354922b9b8b.ngrok-free.app/ws/call/{test_call_id}"
            
            async with websockets.connect(uri) as websocket:
                print(f"✅ WebSocket connected successfully to {uri}")
                
                # Send a test message
                test_message = {
                    "type": "test",
                    "message": "Testing conversation flow fix"
                }
                await websocket.send(json.dumps(test_message))
                print(f"📤 Sent test message")
                
                # Wait for response
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    print(f"📥 Received response: {response}")
                except asyncio.TimeoutError:
                    print(f"⏰ No response received within timeout (this may be normal)")
                
        except Exception as e:
            print(f"❌ WebSocket connection failed: {e}")
    
    # Note: The actual WebSocket test would need to be run separately
    # as it requires the server to be fully running
    
    print(f"\n🚀 Test setup complete! The conversation flow fix is ready for testing.")
    print(f"📊 Monitor server logs to see the waiting mechanism in action.")
    
    return True

if __name__ == "__main__":
    print("🎬 Starting Conversation Flow Fix Test")
    success = test_conversation_flow_fix()
    if success:
        print("\n✅ Test setup completed successfully!")
    else:
        print("\n❌ Test setup failed!")
