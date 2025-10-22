#!/usr/bin/env python3
"""
Authentication Debug Test
Tests the Cognito authentication flow to identify the specific issue
"""

import httpx
import asyncio
import json
from urllib.parse import urlparse, parse_qs

async def test_auth_flow():
    """Test the complete authentication flow"""
    
    base_url = "https://60050b01fc79.ngrok-free.app"
    
    print("🔍 Testing Authentication Flow")
    print("=" * 50)
    
    async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
        
        # Step 1: Test login redirect
        print("\n1. Testing login redirect...")
        try:
            response = await client.get(f"{base_url}/auth/login")
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 302:
                redirect_url = response.headers.get('location')
                print(f"   ✅ Login redirect URL: {redirect_url}")
                
                # Check if redirect URL is valid
                if "ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com" in redirect_url:
                    print("   ✅ Redirect to Cognito hosted UI successful")
                else:
                    print(f"   ❌ Unexpected redirect URL: {redirect_url}")
            else:
                print(f"   ❌ Expected 302 redirect, got {response.status_code}")
                print(f"   Response: {response.text}")
                
        except Exception as e:
            print(f"   ❌ Login test failed: {e}")
        
        # Step 2: Test callback with a dummy code
        print("\n2. Testing callback endpoint...")
        try:
            # This should fail, but we can see the specific error
            callback_url = f"{base_url}/auth/callback?code=dummy_code&state=default"
            response = await client.get(callback_url)
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text[:500]}...")
            
        except Exception as e:
            print(f"   ❌ Callback test failed: {e}")
        
        # Step 3: Test Cognito domain directly
        print("\n3. Testing Cognito domain...")
        try:
            cognito_domain = "https://ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com"
            response = await client.get(f"{cognito_domain}/.well-known/jwks.json")
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                jwks = response.json()
                print(f"   ✅ JWKS retrieved successfully, keys count: {len(jwks.get('keys', []))}")
            else:
                print(f"   ❌ JWKS request failed: {response.text}")
                
        except Exception as e:
            print(f"   ❌ JWKS test failed: {e}")
        
        # Step 4: Test app accessibility
        print("\n4. Testing app accessibility...")
        try:
            response = await client.get(base_url)
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                print("   ✅ App accessible")
            else:
                print(f"   ❌ App not accessible: {response.text[:200]}...")
                
        except Exception as e:
            print(f"   ❌ App accessibility test failed: {e}")
    
    print("\n" + "=" * 50)
    print("🎯 Test Complete")
    
    # Print configuration summary
    print("\n📋 Configuration Summary:")
    print(f"   Base URL: {base_url}")
    print(f"   Redirect URI: {base_url}/auth/callback")
    print(f"   Cognito Domain: https://ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com")
    print(f"   User Pool: ap-south-1_MYtre8r4L")
    print(f"   Client ID: 6vvpsk667mdsq42kqlokc25il")

if __name__ == "__main__":
    asyncio.run(test_auth_flow())
