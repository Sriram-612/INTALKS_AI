#!/usr/bin/env python3
"""
Test Authentication with Session Cookies
Simulates a complete browser authentication flow
"""
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://c2299b13328d.ngrok-free.app"

async def test_complete_auth_flow():
    """Test complete authentication flow with session persistence"""
    print("🔍 Testing Complete Authentication Flow with Sessions")
    print("=" * 70)
    
    # Use a session that maintains cookies
    async with httpx.AsyncClient(follow_redirects=False) as client:
        
        print("\n1. Testing dashboard access (should redirect to login):")
        try:
            response = await client.get(f"{BASE_URL}/")
            print(f"   Status: {response.status_code}")
            if response.status_code == 302:
                print(f"   ✅ Correctly redirecting to: {response.headers.get('location')}")
            else:
                print(f"   ❌ Unexpected status code")
        except Exception as e:
            print(f"   Error: {e}")
        
        print("\n2. Testing session debug endpoint:")
        try:
            response = await client.get(f"{BASE_URL}/debug/session")
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   Session exists: {data.get('session_exists')}")
                print(f"   Is authenticated: {data.get('is_authenticated')}")
                print(f"   User data: {data.get('user_data')}")
            else:
                print(f"   Response: {response.text}")
        except Exception as e:
            print(f"   Error: {e}")
        
        print("\n3. Testing auth/me endpoint:")
        try:
            response = await client.get(f"{BASE_URL}/auth/me")
            print(f"   Status: {response.status_code}")
            if response.status_code == 401:
                print("   ✅ Correctly blocking unauthenticated access")
            else:
                print(f"   Response: {response.text}")
        except Exception as e:
            print(f"   Error: {e}")
    
    print("\n" + "=" * 70)
    print("🎯 Manual Testing Next Steps:")
    print(f"1. Visit: {BASE_URL}/")
    print("2. You should be redirected to Cognito login")
    print("3. Complete the authentication process")
    print("4. After callback, check application logs for debug info")
    print("5. Dashboard should load if session is working correctly")
    print(f"\n📊 Check debug endpoint after login: {BASE_URL}/debug/session")
    print(f"📊 Check logs: tail -f logs/application.log")

if __name__ == "__main__":
    asyncio.run(test_complete_auth_flow())
