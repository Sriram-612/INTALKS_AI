#!/usr/bin/env python3
"""
Test Redis Session for Authentication
"""
import redis
import json
import os
from dotenv import load_dotenv

load_dotenv()

def test_redis_session():
    """Test Redis session storage"""
    print("🔍 Testing Redis Session Storage")
    print("=" * 60)
    
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    print(f"Redis URL: {redis_url}")
    
    try:
        # Connect to Redis
        r = redis.from_url(redis_url, decode_responses=True)
        r.ping()
        print("✅ Redis connection successful")
        
        # Create test session
        test_session_id = "test-session-12345"
        test_user_data = {
            "user": {
                "email": "test@example.com",
                "name": "Test User"
            },
            "authenticated_at": "2025-10-24T04:10:00"
        }
        
        # Save test session
        r.setex(f"session:{test_session_id}", 3600, json.dumps(test_user_data))
        print(f"✅ Test session created: session:{test_session_id}")
        
        # Retrieve test session
        retrieved = r.get(f"session:{test_session_id}")
        if retrieved:
            session_data = json.loads(retrieved)
            print(f"✅ Session retrieved successfully")
            print(f"   Email: {session_data['user']['email']}")
            print(f"   Name: {session_data['user']['name']}")
        else:
            print("❌ Failed to retrieve session")
        
        # List all sessions
        print("\n📋 All sessions in Redis:")
        keys = r.keys("session:*")
        if keys:
            for key in keys[:10]:  # Show first 10
                ttl = r.ttl(key)
                print(f"   • {key} (TTL: {ttl}s)")
        else:
            print("   No sessions found")
        
        # Clean up test session
        r.delete(f"session:{test_session_id}")
        print(f"\n✅ Test session cleaned up")
        
        return True
        
    except Exception as e:
        print(f"❌ Redis test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_redis_session()
    exit(0 if success else 1)
