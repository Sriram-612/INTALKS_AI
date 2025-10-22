#!/usr/bin/env python3
"""
Comprehensive Authentication Test and Debug Script
Diagnoses and attempts to fix authentication issues
"""

import os
import json
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_cognito_endpoints():
    """Test all Cognito endpoints comprehensively"""
    
    print("🔍 Comprehensive Cognito Authentication Test")
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
    
    async with httpx.AsyncClient() as client:
        
        # Test 1: JWKS endpoint
        print("1️⃣ Testing JWKS endpoint...")
        jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
        try:
            response = await client.get(jwks_url)
            if response.status_code == 200:
                jwks_data = response.json()
                print(f"✅ JWKS endpoint working: {len(jwks_data.get('keys', []))} keys found")
            else:
                print(f"❌ JWKS endpoint failed: {response.status_code}")
        except Exception as e:
            print(f"❌ JWKS test failed: {str(e)}")
        print()
        
        # Test 2: OpenID Configuration
        print("2️⃣ Testing OpenID Configuration...")
        openid_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/openid_configuration"
        try:
            response = await client.get(openid_url)
            if response.status_code == 200:
                config = response.json()
                print(f"✅ OpenID Configuration working")
                print(f"   Issuer: {config.get('issuer')}")
                print(f"   Token endpoint: {config.get('token_endpoint')}")
                print(f"   Authorization endpoint: {config.get('authorization_endpoint')}")
            else:
                print(f"❌ OpenID Configuration failed: {response.status_code}")
        except Exception as e:
            print(f"❌ OpenID Configuration test failed: {str(e)}")
        print()
        
        # Test 3: Domain health check
        print("3️⃣ Testing Cognito Domain...")
        try:
            response = await client.get(domain, follow_redirects=False)
            if response.status_code in [200, 302, 403]:
                print(f"✅ Cognito domain accessible: {response.status_code}")
            else:
                print(f"⚠️  Cognito domain response: {response.status_code}")
        except Exception as e:
            print(f"❌ Domain test failed: {str(e)}")
        print()
        
        # Test 4: Login URL generation
        print("4️⃣ Testing login URL generation...")
        login_url = f"{domain}/login"
        params = {
            "client_id": client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": redirect_uri
        }
        
        try:
            response = await client.get(login_url, params=params, follow_redirects=False)
            if response.status_code in [200, 302]:
                print(f"✅ Login URL working: {response.status_code}")
                if response.status_code == 302:
                    print(f"   Redirected to: {response.headers.get('location', 'Unknown')}")
            else:
                print(f"❌ Login URL failed: {response.status_code}")
                print(f"   Response: {response.text[:200]}...")
        except Exception as e:
            print(f"❌ Login URL test failed: {str(e)}")
        print()
        
        # Test 5: Test OAuth endpoints  
        print("5️⃣ Testing OAuth endpoints...")
        oauth_endpoints = [
            f"{domain}/oauth2/authorize",
            f"{domain}/oauth2/token",
            f"{domain}/oauth2/userInfo"
        ]
        
        for endpoint in oauth_endpoints:
            try:
                response = await client.get(endpoint, follow_redirects=False)
                if response.status_code in [200, 302, 400, 401]:  # 400/401 expected without params
                    print(f"✅ {endpoint.split('/')[-1]}: {response.status_code}")
                else:
                    print(f"❌ {endpoint.split('/')[-1]}: {response.status_code}")
            except Exception as e:
                print(f"❌ {endpoint.split('/')[-1]}: {str(e)}")
        
        print()
        
        # Test 6: Application server health
        print("6️⃣ Testing application server...")
        app_base = redirect_uri.replace('/auth/callback', '')
        
        try:
            # Test auth endpoints
            auth_endpoints = [
                f"{app_base}/auth/login",
                f"{app_base}/health"
            ]
            
            for endpoint in auth_endpoints:
                try:
                    response = await client.get(endpoint, timeout=10.0)
                    if response.status_code == 200:
                        print(f"✅ {endpoint.split('/')[-1]}: Working")
                    else:
                        print(f"⚠️  {endpoint.split('/')[-1]}: {response.status_code}")
                except Exception as e:
                    print(f"❌ {endpoint.split('/')[-1]}: {str(e)}")
                    
        except Exception as e:
            print(f"❌ Application server test failed: {str(e)}")
        
        print()
        print("🎯 Diagnosis Summary:")
        print("=" * 60)
        
        if client_secret:
            print("✅ Client has secret (confidential client)")
            print("   → Token exchange should use Basic Auth")
        else:
            print("⚠️  Client has no secret (public client)")
            print("   → Token exchange should not use Basic Auth")
        
        print()
        print("🔧 Recommendations:")
        print("1. Ensure ngrok is running and accessible")
        print("2. Verify Cognito app client callback URLs include ngrok URL")
        print("3. Check if client secret is required for token exchange")
        print("4. Verify OAuth flow settings in Cognito console")
        print("5. Test authentication manually through browser")
        
        # Generate working URLs for manual testing
        print()
        print("🌐 URLs for manual testing:")
        print(f"   App login: {app_base}/auth/login")
        print(f"   Direct login: {login_url}?{httpx.QueryParams(params)}")
        print(f"   Health check: {app_base}/health")

if __name__ == "__main__":
    asyncio.run(test_cognito_endpoints())
