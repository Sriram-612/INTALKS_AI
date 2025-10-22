#!/usr/bin/env python3
"""
Test script for Amazon Cognito authentication integration
Run this script to test the authentication system
"""

import asyncio
import httpx
import json
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://localhost:8000"

async def test_auth_flow():
    """Test the complete authentication flow"""
    
    print("🔧 Testing Amazon Cognito Authentication Integration")
    print("=" * 60)
    
    async with httpx.AsyncClient() as client:
        
        # Test 1: Test signup endpoint
        print("\n1. Testing User Signup...")
        signup_data = {
            "email": "test@example.com",
            "password": "TestPassword123!",
            "first_name": "Test",
            "last_name": "User"
        }
        
        try:
            response = await client.post(f"{BASE_URL}/auth/signup", json=signup_data)
            print(f"   Status: {response.status_code}")
            result = response.json()
            print(f"   Response: {json.dumps(result, indent=2)}")
            
            if response.status_code == 201:
                print("   ✅ Signup endpoint working correctly")
            else:
                print(f"   ⚠️  Signup returned {response.status_code}: {result.get('message', 'Unknown error')}")
                
        except Exception as e:
            print(f"   ❌ Signup test failed: {str(e)}")
        
        # Test 2: Test login endpoint
        print("\n2. Testing User Login...")
        login_data = {
            "email": "test@example.com", 
            "password": "TestPassword123!"
        }
        
        try:
            response = await client.post(f"{BASE_URL}/auth/login", json=login_data)
            print(f"   Status: {response.status_code}")
            result = response.json()
            print(f"   Response: {json.dumps(result, indent=2)}")
            
            access_token = None
            if response.status_code == 200 and result.get('success'):
                access_token = result.get('access_token')
                print("   ✅ Login endpoint working correctly")
                print(f"   🔑 Access token received: {access_token[:50]}...")
            else:
                print(f"   ⚠️  Login returned {response.status_code}: {result.get('message', 'Unknown error')}")
                
        except Exception as e:
            print(f"   ❌ Login test failed: {str(e)}")
        
        # Test 3: Test protected endpoint without token
        print("\n3. Testing Protected Endpoint (without token)...")
        try:
            response = await client.get(f"{BASE_URL}/api/customers")
            print(f"   Status: {response.status_code}")
            result = response.json()
            print(f"   Response: {json.dumps(result, indent=2)}")
            
            if response.status_code == 401:
                print("   ✅ Protected endpoint correctly requires authentication")
            else:
                print(f"   ⚠️  Expected 401, got {response.status_code}")
                
        except Exception as e:
            print(f"   ❌ Protected endpoint test failed: {str(e)}")
        
        # Test 4: Test protected endpoint with token (if we have one)
        if access_token:
            print("\n4. Testing Protected Endpoint (with valid token)...")
            try:
                headers = {"Authorization": f"Bearer {access_token}"}
                response = await client.get(f"{BASE_URL}/api/customers", headers=headers)
                print(f"   Status: {response.status_code}")
                
                if response.status_code == 200:
                    print("   ✅ Protected endpoint accepts valid token")
                    result = response.json()
                    print(f"   📊 Found {len(result)} customers in database")
                else:
                    result = response.json()
                    print(f"   ⚠️  Expected 200, got {response.status_code}: {result}")
                    
            except Exception as e:
                print(f"   ❌ Authenticated endpoint test failed: {str(e)}")
        
        # Test 5: Test user info endpoint
        if access_token:
            print("\n5. Testing User Info Endpoint...")
            try:
                headers = {"Authorization": f"Bearer {access_token}"}
                response = await client.get(f"{BASE_URL}/auth/me", headers=headers)
                print(f"   Status: {response.status_code}")
                result = response.json()
                print(f"   Response: {json.dumps(result, indent=2)}")
                
                if response.status_code == 200:
                    print("   ✅ User info endpoint working correctly")
                else:
                    print(f"   ⚠️  Expected 200, got {response.status_code}")
                    
            except Exception as e:
                print(f"   ❌ User info test failed: {str(e)}")
    
    print("\n" + "=" * 60)
    print("🎉 Authentication Integration Test Complete!")
    print("\n📋 Next Steps:")
    print("1. Configure your AWS Cognito User Pool")
    print("2. Update .env file with your Cognito settings")
    print("3. Test with real Cognito users")
    print("4. Update your frontend to use the new auth endpoints")

async def test_configuration():
    """Test if the authentication configuration is set up correctly"""
    
    print("🔧 Testing Authentication Configuration")
    print("=" * 50)
    
    # Test environment variables
    import os
    required_vars = [
        'COGNITO_USER_POOL_ID',
        'COGNITO_CLIENT_ID', 
        'AWS_REGION'
    ]
    
    print("\n1. Checking Environment Variables...")
    missing_vars = []
    for var in required_vars:
        value = os.getenv(var)
        if value and value != "your-user-pool-id" and value != "your-client-id":
            print(f"   ✅ {var}: {value}")
        else:
            print(f"   ❌ {var}: Not configured")
            missing_vars.append(var)
    
    if missing_vars:
        print(f"\n⚠️  Missing configuration: {', '.join(missing_vars)}")
        print("   Please update your .env file with actual Cognito values")
        return False
    
    # Test AWS credentials
    print("\n2. Checking AWS Credentials...")
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    
    if aws_access_key and aws_secret_key:
        print(f"   ✅ AWS_ACCESS_KEY_ID: {aws_access_key[:10]}...")
        print(f"   ✅ AWS_SECRET_ACCESS_KEY: {aws_secret_key[:10]}...")
    else:
        print("   ❌ AWS credentials not configured")
        return False
    
    # Test if server is running
    print("\n3. Checking Server Availability...")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BASE_URL}/", timeout=5.0)
            if response.status_code == 200:
                print(f"   ✅ Server running at {BASE_URL}")
            else:
                print(f"   ⚠️  Server returned status {response.status_code}")
    except Exception as e:
        print(f"   ❌ Server not accessible: {str(e)}")
        print(f"   💡 Make sure to start the server with: uvicorn main:app --reload --host 0.0.0.0 --port 8000")
        return False
    
    return True

async def main():
    """Main test function"""
    
    # First test configuration
    config_ok = await test_configuration()
    
    if config_ok:
        # Then test authentication flow
        await test_auth_flow()
    else:
        print("\n❌ Configuration issues found. Please fix them before testing authentication.")

if __name__ == "__main__":
    asyncio.run(main())
