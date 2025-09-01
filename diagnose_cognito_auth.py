#!/usr/bin/env python3
"""
Cognito App Client Diagnostic and Fix Script
Diagnoses and fixes common Cognito app client configuration issues
"""
import os
import boto3
from dotenv import load_dotenv

load_dotenv()

def diagnose_and_fix_cognito():
    """Diagnose and fix Cognito app client configuration"""
    
    print("🔍 Cognito App Client Diagnostic Tool")
    print("=" * 60)
    
    # Environment variables
    region = os.getenv("COGNITO_REGION", "ap-south-1")
    user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
    client_id = os.getenv("COGNITO_CLIENT_ID")
    client_secret = os.getenv("COGNITO_CLIENT_SECRET")
    domain = "https://collections.intalksai.com"
    
    print(f"🌍 Domain: {domain}")
    print(f"📍 Region: {region}")
    print(f"🏊 User Pool ID: {user_pool_id}")
    print(f"📱 Client ID: {client_id}")
    print(f"🔐 Client Secret: {'***' + client_secret[-4:] if client_secret else 'NOT SET'}")
    
    if not all([user_pool_id, client_id]):
        print("❌ Missing required environment variables!")
        return False
    
    try:
        # Initialize Cognito client
        cognito_client = boto3.client('cognito-idp', region_name=region)
        
        # Get current app client configuration
        print(f"\n🔍 Getting current app client configuration...")
        response = cognito_client.describe_user_pool_client(
            UserPoolId=user_pool_id,
            ClientId=client_id
        )
        
        current_client = response['UserPoolClient']
        print(f"✅ Current client found: {current_client['ClientName']}")
        
        # Check current configuration
        print(f"\n📋 Current Configuration:")
        print(f"   🔐 Generate Secret: {current_client.get('GenerateSecret', False)}")
        print(f"   🔄 OAuth Flows: {current_client.get('AllowedOAuthFlows', [])}")
        print(f"   📦 OAuth Scopes: {current_client.get('AllowedOAuthScopes', [])}")
        print(f"   🌐 OAuth Flows User Pool Client: {current_client.get('AllowedOAuthFlowsUserPoolClient', False)}")
        print(f"   🔗 Callback URLs: {current_client.get('CallbackURLs', [])}")
        print(f"   🚪 Logout URLs: {current_client.get('LogoutURLs', [])}")
        print(f"   🆔 Supported Identity Providers: {current_client.get('SupportedIdentityProviders', [])}")
        
        # Determine if fixes are needed
        needs_update = False
        issues = []
        
        # Check OAuth flows
        required_flows = ['code']
        current_flows = current_client.get('AllowedOAuthFlows', [])
        if not all(flow in current_flows for flow in required_flows):
            needs_update = True
            issues.append("Missing required OAuth flows")
        
        # Check OAuth flows enabled
        if not current_client.get('AllowedOAuthFlowsUserPoolClient', False):
            needs_update = True
            issues.append("OAuth flows not enabled for user pool client")
        
        # Check OAuth scopes
        required_scopes = ['email', 'openid', 'profile']
        current_scopes = current_client.get('AllowedOAuthScopes', [])
        if not all(scope in current_scopes for scope in required_scopes):
            needs_update = True
            issues.append("Missing required OAuth scopes")
        
        # Check callback URLs
        required_callback = f"{domain}/auth/callback"
        current_callbacks = current_client.get('CallbackURLs', [])
        if required_callback not in current_callbacks:
            needs_update = True
            issues.append("Missing required callback URL")
        
        # Check logout URLs
        required_logout = f"{domain}/"
        current_logouts = current_client.get('LogoutURLs', [])
        if required_logout not in current_logouts:
            needs_update = True
            issues.append("Missing required logout URL")
        
        # Check identity providers
        if 'COGNITO' not in current_client.get('SupportedIdentityProviders', []):
            needs_update = True
            issues.append("Missing COGNITO identity provider")
        
        if issues:
            print(f"\n❌ Issues Found:")
            for issue in issues:
                print(f"   • {issue}")
        
        if needs_update:
            print(f"\n🔧 Fixing configuration...")
            
            # Prepare new configuration
            new_callback_urls = list(set(current_callbacks + [
                f"{domain}/auth/callback",
                "http://localhost:8000/auth/callback"
            ]))
            
            new_logout_urls = list(set(current_logouts + [
                f"{domain}/",
                "http://localhost:8000/"
            ]))
            
            update_params = {
                'UserPoolId': user_pool_id,
                'ClientId': client_id,
                'CallbackURLs': new_callback_urls,
                'LogoutURLs': new_logout_urls,
                'AllowedOAuthFlows': ['code'],
                'AllowedOAuthScopes': ['email', 'openid', 'profile'],
                'AllowedOAuthFlowsUserPoolClient': True,
                'SupportedIdentityProviders': ['COGNITO'],
                'ExplicitAuthFlows': [
                    'ALLOW_USER_PASSWORD_AUTH',
                    'ALLOW_USER_SRP_AUTH',
                    'ALLOW_REFRESH_TOKEN_AUTH'
                ]
            }
            
            # Preserve existing settings
            preserve_fields = [
                'ClientName', 'GenerateSecret', 'RefreshTokenValidity',
                'AccessTokenValidity', 'IdTokenValidity', 'TokenValidityUnits',
                'ReadAttributes', 'WriteAttributes', 'PreventUserExistenceErrors'
            ]
            
            for field in preserve_fields:
                if field in current_client:
                    update_params[field] = current_client[field]
            
            # Update the app client
            cognito_client.update_user_pool_client(**update_params)
            
            print(f"✅ App client configuration updated!")
            print(f"\n📋 Updated Configuration:")
            print(f"   🔗 Callback URLs: {new_callback_urls}")
            print(f"   🚪 Logout URLs: {new_logout_urls}")
            print(f"   🔄 OAuth Flows: ['code']")
            print(f"   📦 OAuth Scopes: ['email', 'openid', 'profile']")
            print(f"   🌐 OAuth Flows Enabled: True")
            
        else:
            print(f"\n✅ Configuration looks good!")
        
        print(f"\n🧪 Testing Token Exchange...")
        
        # Test the token endpoint
        import httpx
        import base64
        
        token_url = f"https://ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com/oauth2/token"
        
        # Test with a dummy request to see the error
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        if client_secret:
            auth_string = f"{client_id}:{client_secret}"
            auth_bytes = base64.b64encode(auth_string.encode()).decode()
            headers["Authorization"] = f"Basic {auth_bytes}"
        
        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": "test_code",  # This will fail but show us the error
            "redirect_uri": f"{domain}/auth/callback"
        }
        
        print(f"🌐 Token URL: {token_url}")
        print(f"🔑 Using client authentication: {'Yes' if client_secret else 'No'}")
        
        try:
            import asyncio
            async def test_token_endpoint():
                async with httpx.AsyncClient() as client:
                    response = await client.post(token_url, headers=headers, data=data)
                    print(f"📊 Response Status: {response.status_code}")
                    print(f"📝 Response: {response.text}")
                    return response
            
            # Run the async test
            response = asyncio.run(test_token_endpoint())
            
        except Exception as e:
            print(f"❌ Token endpoint test failed: {str(e)}")
        
        print(f"\n🎯 Next Steps:")
        print(f"   1. Restart your application server")
        print(f"   2. Test authentication at: {domain}")
        print(f"   3. If still failing, check Cognito domain configuration")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    diagnose_and_fix_cognito()
