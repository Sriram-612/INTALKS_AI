#!/usr/bin/env python3
"""
AWS Cognito App Client Configuration Fixer
Updates Cognito app client with correct callback URLs for ngrok development and production
"""

import boto3
import os
from dotenv import load_dotenv

load_dotenv()

def update_cognito_app_client():
    """Update Cognito app client with correct callback URLs"""
    
    # Environment variables
    region = os.getenv("COGNITO_REGION", "ap-south-1")
    user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
    client_id = os.getenv("COGNITO_CLIENT_ID")
    ngrok_url = "https://c2299b13328d.ngrok-free.app"
    production_url = "https://collections.intalksai.com"
    
    print(f"🔧 Updating Cognito App Client Configuration")
    print(f"📍 Region: {region}")
    print(f"🏊 User Pool ID: {user_pool_id}")
    print(f"🆔 Client ID: {client_id}")
    print(f"🌐 ngrok URL: {ngrok_url}")
    print(f"🌍 Production URL: {production_url}")
    print()
    
    try:
        # Initialize Cognito client
        cognito_client = boto3.client('cognito-idp', region_name=region)
        
        # Get current app client configuration
        print("📋 Getting current app client configuration...")
        response = cognito_client.describe_user_pool_client(
            UserPoolId=user_pool_id,
            ClientId=client_id
        )
        
        current_config = response['UserPoolClient']
        print(f"✅ Current callback URLs: {current_config.get('CallbackURLs', [])}")
        print(f"✅ Current logout URLs: {current_config.get('LogoutURLs', [])}")
        print()
        
        # Define new callback and logout URLs
        new_callback_urls = [
            f"{ngrok_url}/auth/callback",  # Development with ngrok
            f"{production_url}/auth/callback",  # Production
            "http://localhost:8000/auth/callback"  # Local development
        ]
        
        new_logout_urls = [
            f"{ngrok_url}/",  # Development with ngrok
            f"{production_url}/",  # Production
            "http://localhost:8000/"  # Local development
        ]
        
        print("🔄 Updating app client with new URLs...")
        print(f"📝 New callback URLs: {new_callback_urls}")
        print(f"📝 New logout URLs: {new_logout_urls}")
        print()
        
        # Update the app client
        update_response = cognito_client.update_user_pool_client(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            ClientName=current_config.get('ClientName', 'VoiceAssistantClient'),
            CallbackURLs=new_callback_urls,
            LogoutURLs=new_logout_urls,
            SupportedIdentityProviders=current_config.get('SupportedIdentityProviders', ['COGNITO']),
            AllowedOAuthFlows=current_config.get('AllowedOAuthFlows', ['code']),
            AllowedOAuthScopes=current_config.get('AllowedOAuthScopes', ['openid', 'email', 'profile']),
            AllowedOAuthFlowsUserPoolClient=current_config.get('AllowedOAuthFlowsUserPoolClient', True),
            RefreshTokenValidity=current_config.get('RefreshTokenValidity', 30),
            AccessTokenValidity=current_config.get('AccessTokenValidity', 60),
            IdTokenValidity=current_config.get('IdTokenValidity', 60),
            TokenValidityUnits=current_config.get('TokenValidityUnits', {
                'AccessToken': 'minutes',
                'IdToken': 'minutes',
                'RefreshToken': 'days'
            }),
            ExplicitAuthFlows=current_config.get('ExplicitAuthFlows', [
                'ALLOW_USER_SRP_AUTH',
                'ALLOW_REFRESH_TOKEN_AUTH'
            ])
        )
        
        print("✅ App client updated successfully!")
        print()
        
        # Verify the update
        print("🔍 Verifying updated configuration...")
        verify_response = cognito_client.describe_user_pool_client(
            UserPoolId=user_pool_id,
            ClientId=client_id
        )
        
        updated_config = verify_response['UserPoolClient']
        print(f"✅ Updated callback URLs: {updated_config.get('CallbackURLs', [])}")
        print(f"✅ Updated logout URLs: {updated_config.get('LogoutURLs', [])}")
        print()
        
        print("🎯 Configuration updated successfully!")
        print("📋 Next steps:")
        print("1. Test authentication with ngrok URL")
        print("2. Verify callback flow works correctly")
        print("3. Deploy to production when ready")
        
    except Exception as e:
        print(f"❌ Error updating Cognito app client: {str(e)}")
        print()
        print("🔧 Manual steps:")
        print("1. Go to AWS Cognito Console")
        print("2. Navigate to your User Pool > App integration > App clients")
        print(f"3. Edit client {client_id}")
        print("4. Update Callback URLs:")
        for url in new_callback_urls:
            print(f"   - {url}")
        print("5. Update Sign out URLs:")
        for url in new_logout_urls:
            print(f"   - {url}")
        print("6. Save changes")

if __name__ == "__main__":
    update_cognito_app_client()
