#!/usr/bin/env python3
"""
Update AWS Cognito App Client for New Domain
Updates Cognito app client with the new callback URLs for collections.intalksai.com
"""
import os
import boto3
from dotenv import load_dotenv

load_dotenv()

def update_cognito_for_new_domain():
    """Update Cognito app client for the new domain"""
    
    print("🔧 Updating AWS Cognito Configuration for New Domain")
    print("=" * 60)
    
    # Environment variables
    region = os.getenv("COGNITO_REGION", "ap-south-1")
    user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
    client_id = os.getenv("COGNITO_CLIENT_ID")
    new_domain = "https://collections.intalksai.com"
    
    print(f"🌍 New Domain: {new_domain}")
    print(f"📍 Region: {region}")
    print(f"🏊 User Pool ID: {user_pool_id}")
    print(f"📱 Client ID: {client_id}")
    
    if not all([user_pool_id, client_id]):
        print("❌ Missing required environment variables!")
        print("   Make sure COGNITO_USER_POOL_ID and COGNITO_CLIENT_ID are set")
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
        
        # Prepare new callback URLs
        new_callback_urls = [
            f"{new_domain}/auth/callback",
            "http://localhost:8000/auth/callback"  # Keep localhost for development
        ]
        
        new_logout_urls = [
            f"{new_domain}/",
            "http://localhost:8000/"  # Keep localhost for development
        ]
        
        print(f"\n🔄 Updating callback URLs:")
        for url in new_callback_urls:
            print(f"   ✅ {url}")
        
        print(f"\n🔄 Updating logout URLs:")
        for url in new_logout_urls:
            print(f"   ✅ {url}")
        
        # Update the app client
        update_params = {
            'UserPoolId': user_pool_id,
            'ClientId': client_id,
            'CallbackURLs': new_callback_urls,
            'LogoutURLs': new_logout_urls,
            'AllowedOAuthFlows': ['code'],
            'AllowedOAuthScopes': ['email', 'openid', 'profile'],
            'AllowedOAuthFlowsUserPoolClient': True,
            'SupportedIdentityProviders': ['COGNITO']
        }
        
        # Preserve existing settings
        preserve_fields = [
            'ClientName', 'GenerateSecret', 'RefreshTokenValidity',
            'AccessTokenValidity', 'IdTokenValidity', 'TokenValidityUnits',
            'ReadAttributes', 'WriteAttributes', 'ExplicitAuthFlows',
            'PreventUserExistenceErrors'
        ]
        
        for field in preserve_fields:
            if field in current_client:
                update_params[field] = current_client[field]
        
        print(f"\n🚀 Updating Cognito app client...")
        cognito_client.update_user_pool_client(**update_params)
        
        print(f"✅ Cognito app client updated successfully!")
        print(f"\n📋 Summary:")
        print(f"   🌍 Domain: {new_domain}")
        print(f"   🔗 Callback URL: {new_domain}/auth/callback")
        print(f"   🚪 Logout URL: {new_domain}/")
        
        print(f"\n🎯 Next Steps:")
        print(f"   1. Restart your application server")
        print(f"   2. Test authentication at: {new_domain}")
        print(f"   3. Check the application logs for any errors")
        
        return True
        
    except Exception as e:
        print(f"❌ Error updating Cognito configuration: {str(e)}")
        print(f"\n🔧 Manual Steps Required:")
        print(f"   1. Go to AWS Console → Cognito → User Pools")
        print(f"   2. Select your User Pool: {user_pool_id}")
        print(f"   3. Go to 'App Integration' → 'App clients and analytics'")
        print(f"   4. Click on your app client: {client_id}")
        print(f"   5. Click 'Edit' in the Hosted UI section")
        print(f"   6. Add these URLs:")
        print(f"      Callback URLs:")
        for url in new_callback_urls:
            print(f"        - {url}")
        print(f"      Sign out URLs:")
        for url in new_logout_urls:
            print(f"        - {url}")
        
        return False

if __name__ == "__main__":
    update_cognito_for_new_domain()
