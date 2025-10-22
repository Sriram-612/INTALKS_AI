#!/usr/bin/env python3
"""
Quick Authentication Test - Tests the login URL generation
"""

import httpx
import asyncio

async def test_login_url():
    """Test the login URL generation and redirect"""
    
    print("🔍 Testing Login URL Generation")
    print("=" * 40)
    
    base_url = "https://60050b01fc79.ngrok-free.app"
    
    async with httpx.AsyncClient(follow_redirects=False, timeout=10.0) as client:
        
        try:
            # Test the login endpoint
            print(f"📍 Testing: {base_url}/auth/login")
            response = await client.get(f"{base_url}/auth/login")
            
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 302:
                redirect_url = response.headers.get('location')
                print(f"✅ Redirect URL: {redirect_url}")
                
                # Check if it contains the expected Cognito parameters
                if "ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com" in redirect_url:
                    print("✅ Redirects to correct Cognito domain")
                    
                    if "client_id=6vvpsk667mdsq42kqlokc25il" in redirect_url:
                        print("✅ Contains correct client ID")
                    else:
                        print("❌ Missing or incorrect client ID")
                        
                    if "response_type=code" in redirect_url:
                        print("✅ Contains correct response type")
                    else:
                        print("❌ Missing or incorrect response type")
                        
                    if "redirect_uri=" in redirect_url:
                        print("✅ Contains redirect URI")
                    else:
                        print("❌ Missing redirect URI")
                        
                else:
                    print(f"❌ Unexpected redirect URL: {redirect_url}")
            else:
                print(f"❌ Expected 302 redirect, got {response.status_code}")
                print(f"Response: {response.text[:300]}...")
                
        except Exception as e:
            print(f"❌ Test failed: {e}")
    
    print("\n" + "=" * 40)
    print("📋 Next Steps:")
    print("1. Open: https://60050b01fc79.ngrok-free.app")
    print("2. Click 'Login' button")
    print("3. You should be redirected to Cognito login page")
    print("4. Enter your username and password")
    print("5. Should redirect back and authenticate successfully")

if __name__ == "__main__":
    asyncio.run(test_login_url())
