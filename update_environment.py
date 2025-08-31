#!/usr/bin/env python3
"""
Environment Configuration Updater
Updates environment variables for production and development modes
"""

import os
from dotenv import load_dotenv

def update_environment_config(mode="development"):
    """Update environment configuration based on mode"""
    
    env_file = "/home/cyberdude/Documents/Projects/voice/.env"
    
    # Read current .env file
    with open(env_file, 'r') as f:
        content = f.read()
    
    if mode == "production":
        # Production settings
        base_url = "https://collections.intalksai.com"
        redirect_uri = f"{base_url}/auth/callback"
        logout_uri = f"{base_url}/"
        print(f"🚀 Configuring for PRODUCTION mode")
    else:
        # Development settings (ngrok)
        base_url = "https://c2299b13328d.ngrok-free.app"
        redirect_uri = f"{base_url}/auth/callback"
        logout_uri = f"{base_url}/"
        print(f"🔧 Configuring for DEVELOPMENT mode (ngrok)")
    
    print(f"🌍 Base URL: {base_url}")
    print(f"↩️  Redirect URI: {redirect_uri}")
    print(f"🚪 Logout URI: {logout_uri}")
    
    # Update the content
    lines = content.split('\n')
    updated_lines = []
    
    for line in lines:
        if line.startswith('BASE_URL='):
            updated_lines.append(f'BASE_URL="{base_url}"')
        elif line.startswith('COGNITO_REDIRECT_URI='):
            updated_lines.append(f'COGNITO_REDIRECT_URI="{redirect_uri}"')
        elif line.startswith('COGNITO_LOGOUT_URI='):
            updated_lines.append(f'COGNITO_LOGOUT_URI="{logout_uri}"')
        else:
            updated_lines.append(line)
    
    # Write updated content
    updated_content = '\n'.join(updated_lines)
    with open(env_file, 'w') as f:
        f.write(updated_content)
    
    print(f"✅ Environment updated for {mode} mode")
    print()
    print("📝 Updated configurations:")
    print(f"   BASE_URL=\"{base_url}\"")
    print(f"   COGNITO_REDIRECT_URI=\"{redirect_uri}\"")
    print(f"   COGNITO_LOGOUT_URI=\"{logout_uri}\"")

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "development"
    if mode not in ["production", "development"]:
        print("❌ Invalid mode. Use 'production' or 'development'")
        sys.exit(1)
    update_environment_config(mode)
