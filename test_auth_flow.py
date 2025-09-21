#!/usr/bin/env python3
"""
Test Authentication Flow
Tests the complete Cognito authentication flow
"""

import httpx
import os
from dotenv import load_dotenv

load_dotenv()

async def test_auth_flow():
    """Test the authentication flow"""
    
    base_url = os.getenv("BASE_URL", "https://c2299b13328d.ngrok-free.app")
    
    print(f"🧪 Testing Authentication Flow")
    print(f"🌍 Base URL: {base_url}")
    print()
    
    async with httpx.AsyncClient() as client:
        # Test 1: Get login URL
        print("1️⃣ Testing login URL generation...")
        try:
            response = await client.get(f"{base_url}/auth/login")
            if response.status_code == 200:
                login_data = response.json()
                print(f"✅ Login URL: {login_data.get('login_url', 'Not found')}")
            else:
                print(f"❌ Login URL request failed: {response.status_code}")
        except Exception as e:
            print(f"❌ Login URL test failed: {str(e)}")
        
        print()
        
        # Test 2: Test main page access (should redirect to login)
        print("2️⃣ Testing protected route access...")
        try:
            response = await client.get(f"{base_url}/", follow_redirects=False)
            if response.status_code == 302:
                print(f"✅ Protected route correctly redirects to login")
                print(f"   Location: {response.headers.get('location', 'Not found')}")
            elif response.status_code == 200:
                print(f"⚠️  Protected route accessible without authentication")
            else:
                print(f"❌ Unexpected response: {response.status_code}")
        except Exception as e:
            print(f"❌ Protected route test failed: {str(e)}")
        
        print()
        
        # Test 3: Test callback endpoint error handling
        print("3️⃣ Testing callback endpoint...")
        try:
            response = await client.get(f"{base_url}/auth/callback")
            if response.status_code == 400:
                print(f"✅ Callback correctly handles missing parameters")
            else:
                print(f"⚠️  Callback response: {response.status_code}")
        except Exception as e:
            print(f"❌ Callback test failed: {str(e)}")
        
        print()
        
        # Test 4: Health check
        print("4️⃣ Testing health endpoint...")
        try:
            response = await client.get(f"{base_url}/health")
            if response.status_code == 200:
                health_data = response.json()
                print(f"✅ Health check passed")
                print(f"   Status: {health_data.get('status', 'Unknown')}")
            else:
                print(f"❌ Health check failed: {response.status_code}")
        except Exception as e:
            print(f"❌ Health check failed: {str(e)}")
    
    print()
    print("🎯 Next steps for manual testing:")
    print(f"1. Visit: {base_url}/auth/login")
    print("2. Use the login URL to authenticate with Cognito")
    print("3. Complete the authentication flow")
    print("4. Verify successful login and session creation")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_auth_flow())
