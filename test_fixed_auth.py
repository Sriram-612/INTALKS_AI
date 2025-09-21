#!/usr/bin/env python3
"""
Test the Fixed Authentication System
Tests the Cognito authentication with ID token validation
"""
import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://c2299b13328d.ngrok-free.app"

async def test_auth_endpoints():
    """Test authentication endpoints"""
    print("🔧 Testing Fixed Authentication System")
    print("=" * 60)
    
    async with httpx.AsyncClient() as client:
        
        print("\n1️⃣ Testing Home Page (Should redirect to login)")
        try:
            response = await client.get(f"{BASE_URL}/", follow_redirects=False)
            print(f"   Status: {response.status_code}")
            if response.status_code == 302:
                print(f"   Redirect Location: {response.headers.get('location')}")
                print("   ✅ Correctly redirecting unauthenticated users")
            else:
                print("   ❌ Expected redirect to login")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        print("\n2️⃣ Testing Login URL Generation")
        try:
            response = await client.get(f"{BASE_URL}/auth/login", follow_redirects=False)
            print(f"   Status: {response.status_code}")
            if response.status_code == 302:
                login_url = response.headers.get('location')
                print(f"   Login URL: {login_url}")
                if "ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com" in login_url:
                    print("   ✅ Correct Cognito domain")
                if "login/continue" in login_url:
                    print("   ✅ Correct hosted UI endpoint")
                if "response_type=code" in login_url:
                    print("   ✅ Authorization code flow")
                if "scope=email+openid+profile" in login_url:
                    print("   ✅ Correct scopes")
            else:
                print("   ❌ Expected redirect to Cognito")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        print("\n3️⃣ Testing User Info Endpoint (Should require auth)")
        try:
            response = await client.get(f"{BASE_URL}/auth/me")
            print(f"   Status: {response.status_code}")
            if response.status_code == 401:
                print("   ✅ Correctly blocking unauthenticated access")
            else:
                print("   ❌ Expected 401 unauthorized")
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print("\n" + "=" * 60)
    print("🎯 Manual Testing Instructions:")
    print(f"1. Visit: {BASE_URL}")
    print("2. You should be redirected to Cognito login")
    print("3. Complete the authentication")
    print("4. You should be redirected back to the dashboard")
    print("\nIf you get the 'aud claim' error again, please let me know!")

if __name__ == "__main__":
    asyncio.run(test_auth_endpoints())
