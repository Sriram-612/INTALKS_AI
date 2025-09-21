#!/usr/bin/env python3
"""
Diagnose Cognito Token Exchange Issue
Tests different token exchange methods to identify the problem
"""

import os
import base64
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_token_exchange_methods():
    """Test different token exchange authentication methods"""
    
    print("🔍 Diagnosing Cognito Token Exchange Issue")
    print("=" * 60)
    
    # Environment variables
    region = os.getenv("COGNITO_REGION", "ap-south-1")
    user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
    client_id = os.getenv("COGNITO_CLIENT_ID")
    client_secret = os.getenv("COGNITO_CLIENT_SECRET")
    domain = os.getenv("COGNITO_DOMAIN")
    redirect_uri = os.getenv("COGNITO_REDIRECT_URI")
    
    print(f"📍 Region: {region}")
    print(f"🏊 User Pool ID: {user_pool_id}")
    print(f"🆔 Client ID: {client_id}")
    print(f"🔐 Client Secret: {'***' + client_secret[-4:] if client_secret else 'None'}")
    print(f"🌐 Domain: {domain}")
    print(f"↩️  Redirect URI: {redirect_uri}")
    print()
    
    # Test the OAuth endpoints first
    print("1️⃣ Testing OAuth Configuration Endpoints...")
    
    async with httpx.AsyncClient() as client:
        
        # Test the well-known configuration endpoint
        config_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/openid_configuration"
        try:
            response = await client.get(config_url)
            if response.status_code == 200:
                config = response.json()
                print(f"✅ OpenID Configuration: Found")
                print(f"   Token endpoint: {config.get('token_endpoint')}")
                print(f"   Authorization endpoint: {config.get('authorization_endpoint')}")
                print(f"   Issuer: {config.get('issuer')}")
                
                # Check if the expected token endpoint matches our domain
                expected_token_endpoint = f"{domain}/oauth2/token"
                actual_token_endpoint = config.get('token_endpoint')
                
                if expected_token_endpoint == actual_token_endpoint:
                    print(f"✅ Token endpoint matches: {actual_token_endpoint}")
                else:
                    print(f"⚠️  Token endpoint mismatch!")
                    print(f"   Expected: {expected_token_endpoint}")
                    print(f"   Actual: {actual_token_endpoint}")
            else:
                print(f"❌ OpenID Configuration failed: {response.status_code}")
        except Exception as e:
            print(f"❌ OpenID Configuration error: {str(e)}")
        
        print()
        
        # Test authorization endpoint with correct parameters
        print("2️⃣ Testing Authorization URL Generation...")
        auth_url = f"{domain}/oauth2/authorize"
        auth_params = {
            "client_id": client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": redirect_uri,
            "state": "test_state"
        }
        
        try:
            response = await client.get(auth_url, params=auth_params, follow_redirects=False)
            if response.status_code == 302:
                print(f"✅ Authorization endpoint: Working (redirect)")
                redirect_location = response.headers.get('location', '')
                if 'signin' in redirect_location.lower():
                    print(f"   Redirects to sign-in page: ✅")
                else:
                    print(f"   Redirect location: {redirect_location}")
            elif response.status_code == 200:
                print(f"✅ Authorization endpoint: Working (form)")
            else:
                print(f"❌ Authorization endpoint failed: {response.status_code}")
                print(f"   Response: {response.text[:200]}...")
        except Exception as e:
            print(f"❌ Authorization endpoint error: {str(e)}")
        
        print()
        
        # Test token endpoint with dummy data to see the exact error
        print("3️⃣ Testing Token Endpoint Error Responses...")
        token_url = f"{domain}/oauth2/token"
        
        # Method 1: Basic Auth (current method)
        print("\n   Method 1: Client Secret in Authorization Header (Basic Auth)")
        headers1 = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data1 = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": "dummy_code_for_testing",
            "redirect_uri": redirect_uri
        }
        
        if client_secret:
            auth_string = f"{client_id}:{client_secret}"
            auth_bytes = base64.b64encode(auth_string.encode()).decode()
            headers1["Authorization"] = f"Basic {auth_bytes}"
        
        try:
            response = await client.post(token_url, headers=headers1, data=data1)
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text}")
        except Exception as e:
            print(f"   Error: {str(e)}")
        
        # Method 2: Client Secret as POST parameter
        print("\n   Method 2: Client Secret as POST Parameter")
        headers2 = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data2 = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": "dummy_code_for_testing",
            "redirect_uri": redirect_uri
        }
        
        try:
            response = await client.post(token_url, headers=headers2, data=data2)
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text}")
        except Exception as e:
            print(f"   Error: {str(e)}")
        
        # Method 3: No client secret (public client)
        print("\n   Method 3: No Client Secret (Public Client)")
        headers3 = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data3 = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": "dummy_code_for_testing",
            "redirect_uri": redirect_uri
        }
        
        try:
            response = await client.post(token_url, headers=headers3, data=data3)
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text}")
        except Exception as e:
            print(f"   Error: {str(e)}")
        
        print()
        print("🎯 Analysis Summary:")
        print("=" * 60)
        print("• 'unauthorized_client' typically means:")
        print("  1. Client ID doesn't match")
        print("  2. Client secret authentication method is wrong")
        print("  3. Redirect URI doesn't match exactly")
        print("  4. Client is not configured for 'authorization_code' grant type")
        print()
        print("📋 Next Steps:")
        print("1. Check AWS Cognito Console → App Client → Hosted UI settings")
        print("2. Verify 'Allowed OAuth flows' includes 'Authorization code grant'")
        print("3. Verify 'Allowed OAuth scopes' includes 'openid', 'email', 'profile'")
        print("4. Check if 'Generate client secret' is enabled/disabled as expected")
        print("5. Ensure callback URLs exactly match (including https/http)")

if __name__ == "__main__":
    asyncio.run(test_token_exchange_methods())
