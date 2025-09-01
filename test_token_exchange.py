#!/usr/bin/env python3
"""
Test Token Exchange with Different Authentication Methods
"""
import os
import httpx
import base64
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_token_exchange_methods():
    """Test different token exchange authentication methods"""
    
    print("🧪 Testing Token Exchange Methods")
    print("=" * 50)
    
    # Configuration
    client_id = os.getenv("COGNITO_CLIENT_ID")
    client_secret = os.getenv("COGNITO_CLIENT_SECRET")
    domain = os.getenv("COGNITO_DOMAIN")
    redirect_uri = os.getenv("COGNITO_REDIRECT_URI")
    
    token_url = f"{domain}/oauth2/token"
    
    print(f"🌐 Token URL: {token_url}")
    print(f"📱 Client ID: {client_id}")
    print(f"🔐 Client Secret: {'***' + client_secret[-4:] if client_secret else 'None'}")
    print(f"🔗 Redirect URI: {redirect_uri}")
    
    # Test data (will fail with invalid_grant but shows auth method issues)
    test_code = "test_code_123"
    
    # Method 1: With Basic Auth (current method)
    print(f"\n🔍 Method 1: Basic Authentication")
    headers_basic = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    if client_secret:
        auth_string = f"{client_id}:{client_secret}"
        auth_bytes = base64.b64encode(auth_string.encode()).decode()
        headers_basic["Authorization"] = f"Basic {auth_bytes}"
    
    data_basic = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": test_code,
        "redirect_uri": redirect_uri
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, headers=headers_basic, data=data_basic)
        print(f"   📊 Status: {response.status_code}")
        print(f"   📝 Response: {response.text}")
    
    # Method 2: With client_secret in body (alternative method)
    print(f"\n🔍 Method 2: Client Secret in Body")
    headers_body = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data_body = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": test_code,
        "redirect_uri": redirect_uri
    }
    
    if client_secret:
        data_body["client_secret"] = client_secret
    
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, headers=headers_body, data=data_body)
        print(f"   📊 Status: {response.status_code}")
        print(f"   📝 Response: {response.text}")
    
    # Method 3: Without client secret (public client)
    print(f"\n🔍 Method 3: Public Client (No Secret)")
    headers_public = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data_public = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": test_code,
        "redirect_uri": redirect_uri
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, headers=headers_public, data=data_public)
        print(f"   📊 Status: {response.status_code}")
        print(f"   📝 Response: {response.text}")
    
    print(f"\n📋 Analysis:")
    print(f"   - All methods should return 'invalid_grant' (expected for test code)")
    print(f"   - 'unauthorized_client' indicates authentication method mismatch")
    print(f"   - Check which method works and update the implementation")

if __name__ == "__main__":
    asyncio.run(test_token_exchange_methods())
