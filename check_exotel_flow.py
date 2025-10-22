#!/usr/bin/env python3

import requests
import os
from dotenv import load_dotenv

load_dotenv()

def check_exotel_flow():
    """Check if Exotel Flow is configured properly"""
    
    # Get credentials from environment
    exotel_sid = os.getenv("EXOTEL_SID")
    exotel_token = os.getenv("EXOTEL_TOKEN")
    flow_app_id = os.getenv("EXOTEL_FLOW_APP_ID")
    
    print(f"🔧 Checking Exotel Flow Configuration...")
    print(f"   • Account SID: {exotel_sid}")
    print(f"   • Flow App ID: {flow_app_id}")
    
    # Check Flow URL accessibility
    flow_url = f"http://my.exotel.com/{exotel_sid}/exoml/start_voice/{flow_app_id}"
    print(f"   • Flow URL: {flow_url}")
    
    try:
        # Try to access the flow URL
        response = requests.get(flow_url, timeout=10)
        
        print(f"\n📡 Flow URL Response:")
        print(f"   • Status Code: {response.status_code}")
        print(f"   • Content Length: {len(response.text)} bytes")
        
        if response.status_code == 200:
            content = response.text.strip()
            if content:
                print(f"   • Content Preview: {content[:200]}...")
                
                # Check if it looks like valid ExoML
                if any(tag in content.lower() for tag in ['<response>', '<say>', '<play>', '<gather>', '<dial>']):
                    print("✅ Flow appears to contain valid ExoML tags")
                else:
                    print("⚠️  Flow content doesn't appear to contain ExoML tags")
                    
            else:
                print("❌ Flow is EMPTY - This is why you heard nothing!")
                
        elif response.status_code == 404:
            print("❌ Flow NOT FOUND - Flow App ID might be incorrect")
        else:
            print(f"❌ Flow returned error: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error checking flow: {str(e)}")
    
    # Provide solution
    print(f"\n🎯 **SOLUTION:**")
    print(f"1. Log into your Exotel dashboard: https://my.exotel.com/{exotel_sid}/")
    print(f"2. Go to 'Flows' or 'Apps' section")
    print(f"3. Find Flow/App ID: {flow_app_id}")
    print(f"4. Add ExoML content like this:")
    print(f"""
    
    🎵 **SAMPLE EXOML FOR VOICE BOT:**
    
    <Response>
        <Say voice="woman">
            Hello! This is a call from your loan service. 
            We are calling regarding your loan payment due.
            Please press 1 to speak to an agent, or press 2 to make a payment.
        </Say>
        <Gather numDigits="1" timeout="10" finishOnKey="#">
            <Say voice="woman">Please press 1 for agent or 2 for payment</Say>
        </Gather>
        <Say voice="woman">Thank you for your time. Goodbye!</Say>
    </Response>
    """)

if __name__ == '__main__':
    check_exotel_flow()
