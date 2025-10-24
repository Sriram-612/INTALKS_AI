#!/usr/bin/env python3
"""
Test Cognito Token Exchange
Debug why token exchange is failing
"""
import os
import base64
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_token_exchange():
    """Test Cognito token exchange with detailed logging"""
    print("🔍 Testing Cognito Token Exchange Configuration")
    print("=" * 70)
    
    # Get configuration
    cognito_region = os.getenv("COGNITO_REGION", "ap-south-1")
    user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
    client_id = os.getenv("COGNITO_CLIENT_ID")
    client_secret = os.getenv("COGNITO_CLIENT_SECRET")
    cognito_domain = os.getenv("COGNITO_DOMAIN")
    redirect_uri = os.getenv("COGNITO_REDIRECT_URI")
    
    print(f"\n📋 Configuration:")
    print(f"   Region: {cognito_region}")
    print(f"   User Pool ID: {user_pool_id}")
    print(f"   Client ID: {client_id}")
    print(f"   Client Secret: {'***' + client_secret[-4:] if client_secret else 'None'}")
    print(f"   Cognito Domain: {cognito_domain}")
    print(f"   Redirect URI: {redirect_uri}")
    
    # Check if client secret is set
    if not client_secret:
        print(f"\n⚠️  WARNING: No client secret found!")
        print(f"   This might be required if your Cognito app client has a secret.")
        print(f"\n   To check in AWS Console:")
        print(f"   1. Go to Cognito User Pool: {user_pool_id}")
        print(f"   2. App Integration → App clients → {client_id}")
        print(f"   3. Check 'App client information' section")
        print(f"   4. If 'Client secret' is shown, you need to set COGNITO_CLIENT_SECRET in .env")
    
    # Test token endpoint URL
    token_url = f"{cognito_domain}/oauth2/token"
    print(f"\n🔗 Token endpoint: {token_url}")
    
    # Test with a dummy code (will fail but shows the error)
    print(f"\n🧪 Testing token endpoint with dummy code...")
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": "dummy-code-for-testing",
        "redirect_uri": redirect_uri
    }
    
    # Add client secret if available
    if client_secret:
        auth_string = f"{client_id}:{client_secret}"
        auth_bytes = base64.b64encode(auth_string.encode()).decode()
        headers["Authorization"] = f"Basic {auth_bytes}"
        print(f"   Using Basic Auth with client secret")
    else:
        print(f"   Using public client (no secret)")
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(token_url, headers=headers, data=data)
            
            print(f"\n📊 Response:")
            print(f"   Status Code: {response.status_code}")
            print(f"   Headers: {dict(response.headers)}")
            print(f"   Body: {response.text}")
            
            if response.status_code == 400:
                error_data = response.json() if response.text else {}
                error = error_data.get('error', 'unknown')
                error_desc = error_data.get('error_description', 'No description')
                
                print(f"\n❌ Token exchange error (expected with dummy code):")
                print(f"   Error: {error}")
                print(f"   Description: {error_desc}")
                
                if error == "invalid_grant":
                    print(f"\n✅ This is expected! The error shows token endpoint is working.")
                    print(f"   The actual issue is likely:")
                    print(f"   1. Authorization code can only be used once")
                    print(f"   2. Code expires after 10 minutes")
                    print(f"   3. Redirect URI must match exactly")
                elif error == "invalid_client":
                    print(f"\n⚠️  Client authentication failed!")
                    print(f"   Possible causes:")
                    print(f"   1. Client secret is wrong or missing")
                    print(f"   2. Client ID is incorrect")
                    print(f"   3. App client is not configured for authorization code flow")
                
    except httpx.ConnectError as e:
        print(f"\n❌ Connection Error: {e}")
        print(f"   Cannot reach Cognito domain: {cognito_domain}")
        print(f"   Check if domain is correct")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Additional checks
    print(f"\n🔍 Additional Checks:")
    print(f"\n1. Verify redirect URI in AWS Cognito:")
    print(f"   Expected: {redirect_uri}")
    print(f"   Go to: https://console.aws.amazon.com/cognito/")
    print(f"   Navigate to: User Pools → {user_pool_id} → App Integration → App clients")
    print(f"   Check: Allowed callback URLs must include {redirect_uri}")
    
    print(f"\n2. Verify OAuth flows enabled:")
    print(f"   Required: Authorization code grant")
    print(f"   Required: Implicit grant (for userInfo endpoint)")
    
    print(f"\n3. Verify OAuth scopes:")
    print(f"   Required: openid, email, profile")
    
    print(f"\n4. Authorization code usage:")
    print(f"   • Each code can only be used ONCE")
    print(f"   • Codes expire after 10 minutes")
    print(f"   • If you refresh the callback URL, you get the SAME code (already used)")
    print(f"   • Solution: Start a fresh login from the beginning")

if __name__ == "__main__":
    asyncio.run(test_token_exchange())
