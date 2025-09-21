#!/usr/bin/env python3
"""
Quick Test Script for Cognito Hosted UI Setup
Verifies that all components are properly configured
"""

import sys
import os
sys.path.append('/home/cyberdude/Documents/Projects/voice')

def test_imports():
    """Test that all required modules can be imported"""
    try:
        print("🔍 Testing imports...")
        
        # Test Cognito auth module
        from utils.cognito_hosted_auth import cognito_auth, get_current_user
        print("✅ Cognito hosted auth module imported successfully")
        
        # Test main module
        import main
        print("✅ Main application module imported successfully")
        
        return True
    except Exception as e:
        print(f"❌ Import error: {e}")
        return False

def test_env_config():
    """Test environment configuration"""
    try:
        print("\n🔧 Testing environment configuration...")
        
        from dotenv import load_dotenv
        load_dotenv()
        
        required_vars = [
            'COGNITO_USER_POOL_ID',
            'COGNITO_CLIENT_ID', 
            'COGNITO_CLIENT_SECRET',
            'COGNITO_DOMAIN',
            'COGNITO_REDIRECT_URI',
            'COGNITO_LOGOUT_URI'
        ]
        
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var)
            if not value:
                missing_vars.append(var)
            else:
                # Mask sensitive values
                if 'SECRET' in var:
                    display_value = value[:8] + "..." if len(value) > 8 else "***"
                elif 'URI' in var:
                    display_value = value
                else:
                    display_value = value
                print(f"  ✅ {var}: {display_value}")
        
        if missing_vars:
            print(f"❌ Missing environment variables: {', '.join(missing_vars)}")
            return False
        
        # Check if URLs need updating
        redirect_uri = os.getenv('COGNITO_REDIRECT_URI')
        logout_uri = os.getenv('COGNITO_LOGOUT_URI')
        
        if 'your-domain.com' in redirect_uri or 'your-domain.com' in logout_uri:
            print("⚠️  WARNING: URLs still contain placeholder 'your-domain.com'")
            print("   Please update with your actual AWS domain in .env file")
        
        return True
        
    except Exception as e:
        print(f"❌ Environment configuration error: {e}")
        return False

def test_cognito_setup():
    """Test Cognito configuration"""
    try:
        print("\n🔐 Testing Cognito setup...")
        
        from utils.cognito_hosted_auth import cognito_auth
        
        # Test login URL generation
        login_url = cognito_auth.get_login_url()
        print(f"✅ Login URL: {login_url}")
        
        # Test logout URL generation  
        logout_url = cognito_auth.get_logout_url()
        print(f"✅ Logout URL: {logout_url}")
        
        return True
        
    except Exception as e:
        print(f"❌ Cognito setup error: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 Starting Cognito Hosted UI Configuration Test\n")
    
    tests = [
        ("Imports", test_imports),
        ("Environment Config", test_env_config), 
        ("Cognito Setup", test_cognito_setup)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        if test_func():
            passed += 1
        print()
    
    print("=" * 50)
    print(f"🏁 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ All tests passed! Your Cognito hosted UI setup is ready.")
        print("\n📋 Next Steps:")
        print("1. Update .env file with your actual AWS domain URLs")
        print("2. Configure callback URLs in AWS Cognito Console")
        print("3. Deploy to AWS and test the authentication flow")
        print("\n📖 See COGNITO_HOSTED_UI_SETUP.md for detailed instructions")
    else:
        print("❌ Some tests failed. Please fix the issues above.")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
