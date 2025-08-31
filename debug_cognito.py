#!/usr/bin/env python3
"""
Debug Cognito Authentication Issues
Tests JWKS endpoint and validates configuration
"""

import os
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

async def test_cognito_endpoints():
    """Test Cognito endpoints and configuration"""
    print("🔍 Testing Cognito Configuration")
    print("=" * 50)
    
    # Configuration
    cognito_region = os.getenv("COGNITO_REGION", "ap-south-1")
    user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
    client_id = os.getenv("COGNITO_CLIENT_ID")
    cognito_domain = os.getenv("COGNITO_DOMAIN")
    redirect_uri = os.getenv("COGNITO_REDIRECT_URI")
    
    print(f"📍 Cognito Region: {cognito_region}")
    print(f"🏊 User Pool ID: {user_pool_id}")
    print(f"🆔 Client ID: {client_id}")
    print(f"🌐 Cognito Domain: {cognito_domain}")
    print(f"↩️  Redirect URI: {redirect_uri}")
    
    # Test JWKS endpoint
    jwks_url = f"https://cognito-idp.{cognito_region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
    print(f"\n🔑 Testing JWKS endpoint: {jwks_url}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url)
            print(f"📊 Status: {response.status_code}")
            
            if response.status_code == 200:
                jwks_data = response.json()
                print(f"✅ JWKS Response: {jwks_data}")
                
                if "keys" in jwks_data:
                    print(f"🔐 Found {len(jwks_data['keys'])} key(s)")
                else:
                    print("❌ No 'keys' field in JWKS response")
            else:
                print(f"❌ JWKS request failed: {response.text}")
                
    except Exception as e:
        print(f"❌ Error testing JWKS: {str(e)}")
    
    # Test Cognito domain
    print(f"\n🌐 Testing Cognito Domain: {cognito_domain}")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(cognito_domain)
            print(f"📊 Status: {response.status_code}")
            if response.status_code != 200:
                print(f"⚠️  Response: {response.text[:200]}...")
            else:
                print("✅ Cognito domain is accessible")
    except Exception as e:
        print(f"❌ Error testing Cognito domain: {str(e)}")
    
    # Generate login URL
    from urllib.parse import urlencode
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": "email openid profile",
        "redirect_uri": redirect_uri,
        "state": "test_state"
    }
    
    login_url = f"{cognito_domain}/login?" + urlencode(params)
    print(f"\n🔗 Generated Login URL:")
    print(f"   {login_url}")
    
    print("\n" + "=" * 50)
    print("🎯 Next Steps:")
    print("1. Make sure the ngrok URL is added to AWS Cognito App Client callback URLs")
    print("2. Check that the app client has the correct OAuth scopes enabled")
    print("3. Verify that the client secret is correct if you're using one")

if __name__ == "__main__":
    asyncio.run(test_cognito_endpoints())
