#!/usr/bin/env python3
"""
Automated Exotel Webhook Configuration for AWS Production
Updates all webhook URLs to point to AWS server: 3.108.35.213:8000
"""

import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Exotel configuration
EXOTEL_SID = os.getenv('EXOTEL_SID')
EXOTEL_TOKEN = os.getenv('EXOTEL_TOKEN')
BASE_URL = os.getenv('BASE_URL', 'http://3.108.35.213:8000')

# Webhook endpoints to configure
WEBHOOK_ENDPOINTS = {
    'incoming_call': f'{BASE_URL}/exotel/incoming_call',
    'call_status': f'{BASE_URL}/exotel/call_status',
    'recording': f'{BASE_URL}/exotel/recording',
    'websocket_url': f'{BASE_URL}/ws-url'
}

def update_exotel_webhooks():
    """Update Exotel webhook configurations"""
    
    print("🔧 Updating Exotel Webhook Configurations...")
    print(f"📍 Target Server: {BASE_URL}")
    print("")
    
    # Basic authentication for Exotel API
    auth = (EXOTEL_SID, EXOTEL_TOKEN)
    
    # Headers
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    print("📋 Webhook URLs to configure:")
    for name, url in WEBHOOK_ENDPOINTS.items():
        print(f"   {name}: {url}")
    print("")
    
    # Example configuration data (adjust based on your Exotel setup)
    webhook_configs = [
        {
            'name': 'Incoming Call Webhook',
            'url': WEBHOOK_ENDPOINTS['incoming_call'],
            'method': 'POST',
            'description': 'Handles incoming voice calls'
        },
        {
            'name': 'Call Status Webhook',
            'url': WEBHOOK_ENDPOINTS['call_status'],
            'method': 'POST',
            'description': 'Receives call status updates'
        },
        {
            'name': 'Recording Webhook',
            'url': WEBHOOK_ENDPOINTS['recording'],
            'method': 'POST',
            'description': 'Handles call recording events'
        }
    ]
    
    print("✅ Webhook configuration summary:")
    for config in webhook_configs:
        print(f"   • {config['name']}: {config['url']}")
    
    print("")
    print("⚠️  MANUAL STEPS REQUIRED:")
    print("   1. Log into your Exotel dashboard")
    print("   2. Navigate to Flow Builder or Webhook Settings")
    print("   3. Update the following webhook URLs:")
    print("")
    
    for config in webhook_configs:
        print(f"   📌 {config['name']}:")
        print(f"      URL: {config['url']}")
        print(f"      Method: {config['method']}")
        print(f"      Description: {config['description']}")
        print("")
    
    print("🌐 WebSocket URL for Exotel Flow:")
    print(f"   URL: {WEBHOOK_ENDPOINTS['websocket_url']}")
    print("   Use this URL in your Exotel Flow for WebSocket connections")
    print("")
    
    print("🧪 Test your configuration:")
    print(f"   Health Check: curl {BASE_URL}/health")
    print(f"   WebSocket Test: wscat -c ws://3.108.35.213:8000/ws/voice/test123")
    print("")

def test_webhook_endpoints():
    """Test if webhook endpoints are accessible"""
    print("🧪 Testing webhook endpoint accessibility...")
    
    for name, url in WEBHOOK_ENDPOINTS.items():
        try:
            if url.startswith('ws://'):
                print(f"   {name}: {url} (WebSocket - test manually)")
                continue
                
            response = requests.get(url.replace('/exotel/', '/health'), timeout=5)
            if response.status_code == 200:
                print(f"   ✅ {name}: Server accessible")
            else:
                print(f"   ⚠️  {name}: Server returned {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ {name}: Connection failed - {e}")
    
    print("")

def validate_environment():
    """Validate required environment variables"""
    required_vars = ['EXOTEL_SID', 'EXOTEL_TOKEN', 'BASE_URL']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"❌ Missing environment variables: {missing_vars}")
        return False
    
    print("✅ All required environment variables are set")
    return True

def main():
    """Main function"""
    print("🚀 Exotel Webhook Configuration Tool")
    print("=" * 50)
    
    # Validate environment
    if not validate_environment():
        exit(1)
    
    # Update webhooks
    update_exotel_webhooks()
    
    # Test endpoints
    test_webhook_endpoints()
    
    print("🎉 Webhook configuration completed!")
    print("📝 Remember to update your Exotel dashboard manually with the above URLs")

if __name__ == "__main__":
    main()
