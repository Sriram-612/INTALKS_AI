#!/usr/bin/env python3
"""
Debug Session Test Script
Tests the session authentication flow
"""
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://c2299b13328d.ngrok-free.app"

async def test_session_debug():
    """Test session authentication flow"""
    print("🔍 Debugging Session Authentication Flow")
    print("=" * 60)
    
    async with httpx.AsyncClient(follow_redirects=False) as client:
        
        # Test 1: Check root endpoint without authentication
        print("\n1. Testing root endpoint without authentication:")
        try:
            response = await client.get(f"{BASE_URL}/")
            print(f"   Status: {response.status_code}")
            print(f"   Headers: {dict(response.headers)}")
            if response.status_code == 302:
                print(f"   Redirected to: {response.headers.get('location')}")
        except Exception as e:
            print(f"   Error: {e}")
        
        # Test 2: Check if we have a session debug endpoint
        print("\n2. Testing session debug endpoint:")
        try:
            response = await client.get(f"{BASE_URL}/debug/session")
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                print(f"   Response: {response.text}")
        except Exception as e:
            print(f"   Error: {e}")
        
        # Test 3: Check auth/me endpoint
        print("\n3. Testing auth/me endpoint:")
        try:
            response = await client.get(f"{BASE_URL}/auth/me")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text}")
        except Exception as e:
            print(f"   Error: {e}")
    
    print("\n" + "=" * 60)
    print("🎯 Manual Testing Instructions:")
    print(f"1. Visit: {BASE_URL}/")
    print("2. Check if you're redirected to Cognito login")
    print("3. Complete authentication")
    print("4. Check if you're redirected back to dashboard")

if __name__ == "__main__":
    asyncio.run(test_session_debug())
