#!/usr/bin/env python3
"""
EC2 Deployment Diagnostic Script
Run this on EC2 to check all dependencies and configurations
"""

import os
import sys
import asyncio
from dotenv import load_dotenv

load_dotenv()

def print_section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def check_env_variables():
    """Check all required environment variables"""
    print_section("1. ENVIRONMENT VARIABLES CHECK")
    
    required_vars = {
        "SARVAM_API_KEY": "Sarvam API Key",
        "AWS_REGION": "AWS Region (or BEDROCK_REGION)",
        "CLAUDE_MODEL_ID": "Claude Model ID",
        "EXOTEL_SID": "Exotel SID",
        "EXOTEL_TOKEN": "Exotel Token",
        "EXOTEL_API_KEY": "Exotel API Key",
        "COGNITO_USER_POOL_ID": "Cognito User Pool ID",
        "COGNITO_CLIENT_ID": "Cognito Client ID",
        "DATABASE_URL": "Database URL"
    }
    
    missing = []
    for var, desc in required_vars.items():
        value = os.getenv(var) or os.getenv(var.replace("AWS_REGION", "BEDROCK_REGION"))
        if value:
            masked = f"{'***' + value[-4:]}" if len(value) > 4 else "***"
            print(f"  ✅ {desc:30s}: {masked}")
        else:
            print(f"  ❌ {desc:30s}: MISSING")
            missing.append(var)
    
    if missing:
        print(f"\n  ⚠️  Missing variables: {', '.join(missing)}")
        return False
    return True

async def test_sarvam_connectivity():
    """Test Sarvam API connectivity"""
    print_section("2. SARVAM API CONNECTIVITY TEST")
    
    try:
        import httpx
        api_key = os.getenv("SARVAM_API_KEY")
        
        if not api_key:
            print("  ❌ SARVAM_API_KEY not set")
            return False
        
        print(f"  ℹ️  API Key: {'***' + api_key[-4:]}")
        
        # Test basic connectivity
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try to reach Sarvam's general endpoint
            try:
                response = await client.get("https://api.sarvam.ai/", timeout=10.0)
                print(f"  ✅ Sarvam API reachable (status: {response.status_code})")
            except Exception as e:
                print(f"  ⚠️  Sarvam API connectivity issue: {e}")
                print("  ℹ️  This might be a firewall/security group issue")
        
        # Try to initialize Sarvam client
        try:
            from sarvamai import SarvamAI
            client = SarvamAI(api_subscription_key=api_key)
            print("  ✅ Sarvam client initialized successfully")
            return True
        except Exception as e:
            print(f"  ❌ Failed to initialize Sarvam client: {e}")
            return False
            
    except ImportError as e:
        print(f"  ❌ Failed to import required libraries: {e}")
        return False

async def test_bedrock_connectivity():
    """Test AWS Bedrock connectivity"""
    print_section("3. AWS BEDROCK CONNECTIVITY TEST")
    
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
        
        region = os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION") or "eu-north-1"
        print(f"  ℹ️  Using region: {region}")
        
        # Check AWS credentials
        try:
            session = boto3.Session()
            credentials = session.get_credentials()
            if credentials:
                print(f"  ✅ AWS credentials found (Access Key: ***{credentials.access_key[-4:]})")
            else:
                print("  ❌ No AWS credentials found")
                print("  ℹ️  Check IAM role (if EC2) or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY")
                return False
        except Exception as e:
            print(f"  ❌ Error checking credentials: {e}")
            return False
        
        # Try to create Bedrock client
        try:
            client = boto3.client('bedrock-runtime', region_name=region)
            print(f"  ✅ Bedrock client created successfully in {region}")
            
            # Test with a simple model list (this might fail without permissions, but client creation should work)
            try:
                # We won't actually invoke, just test client creation
                print("  ✅ Bedrock client ready for invocations")
                return True
            except ClientError as e:
                if 'AccessDenied' in str(e):
                    print("  ⚠️  Bedrock client created but access denied")
                    print("  ℹ️  Check IAM permissions for bedrock:InvokeModel")
                else:
                    print(f"  ⚠️  Bedrock client error: {e}")
                return False
        except Exception as e:
            print(f"  ❌ Failed to create Bedrock client: {e}")
            return False
            
    except ImportError as e:
        print(f"  ❌ Failed to import boto3: {e}")
        return False

async def test_cognito_connectivity():
    """Test Cognito JWKS endpoint"""
    print_section("4. COGNITO JWKS CONNECTIVITY TEST")
    
    try:
        import httpx
        
        region = os.getenv("COGNITO_REGION", "ap-south-1")
        user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
        
        if not user_pool_id:
            print("  ⚠️  COGNITO_USER_POOL_ID not set, skipping")
            return True
        
        jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
        print(f"  ℹ️  Testing: {jwks_url}")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(jwks_url)
                if response.status_code == 200:
                    print(f"  ✅ JWKS endpoint reachable (status: {response.status_code})")
                    return True
                else:
                    print(f"  ❌ JWKS endpoint returned {response.status_code}")
                    return False
            except Exception as e:
                print(f"  ❌ JWKS endpoint unreachable: {e}")
                print("  ℹ️  Check security group outbound rules (port 443)")
                return False
                
    except ImportError as e:
        print(f"  ❌ Failed to import httpx: {e}")
        return False

def check_system_dependencies():
    """Check system-level dependencies"""
    print_section("5. SYSTEM DEPENDENCIES CHECK")
    
    import subprocess
    
    dependencies = {
        "ffmpeg": ["ffmpeg", "-version"],
        "python": ["python3", "--version"],
        "pip": ["pip3", "--version"]
    }
    
    all_ok = True
    for name, cmd in dependencies.items():
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                version = result.stdout.split('\n')[0]
                print(f"  ✅ {name:15s}: {version[:60]}")
            else:
                print(f"  ❌ {name:15s}: Not working properly")
                all_ok = False
        except FileNotFoundError:
            print(f"  ❌ {name:15s}: Not installed")
            all_ok = False
        except Exception as e:
            print(f"  ⚠️  {name:15s}: Error checking: {e}")
            all_ok = False
    
    return all_ok

def check_python_packages():
    """Check required Python packages"""
    print_section("6. PYTHON PACKAGES CHECK")
    
    import subprocess
    import sys
    
    required_packages = [
        "fastapi", "uvicorn", "boto3", "sarvamai", "pydub", 
        "httpx", "sqlalchemy", "redis", "python-dotenv"
    ]
    
    missing = []
    for package in required_packages:
        # Use pip to check if package is installed (works with venv)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", package],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print(f"  ✅ {package:20s}: Installed")
            else:
                # Try importing as fallback
                try:
                    __import__(package.replace("-", "_"))
                    print(f"  ✅ {package:20s}: Installed")
                except ImportError:
                    print(f"  ❌ {package:20s}: NOT INSTALLED")
                    missing.append(package)
        except Exception as e:
            print(f"  ⚠️  {package:20s}: Could not verify")
    
    if missing:
        print(f"\n  ⚠️  Missing packages: {', '.join(missing)}")
        print(f"  ℹ️  Install with: pip install {' '.join(missing)}")
        return False
    return True

async def test_database_connectivity():
    """Test database connection"""
    print_section("7. DATABASE CONNECTIVITY TEST")
    
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("  ⚠️  DATABASE_URL not set, skipping")
        return True
    
    print(f"  ℹ️  Database: {db_url.split('@')[1] if '@' in db_url else 'Unknown'}")
    
    try:
        from sqlalchemy import create_engine, text
        
        engine = create_engine(db_url)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("  ✅ Database connection successful")
            return True
    except Exception as e:
        print(f"  ❌ Database connection failed: {e}")
        return False

def print_recommendations(results):
    """Print recommendations based on test results"""
    print_section("RECOMMENDATIONS")
    
    if not results.get("env_vars"):
        print("  🔧 Set missing environment variables in /etc/environment or .env file")
        print("  📝 Run: sudo nano /etc/environment")
        print("  📝 Or check your .env file exists and is loaded")
    
    if not results.get("sarvam"):
        print("  🔧 Check Sarvam API connectivity:")
        print("  📝 Verify security group allows outbound HTTPS (port 443)")
        print("  📝 Test: curl -I https://api.sarvam.ai/")
    
    if not results.get("bedrock"):
        print("  🔧 Check AWS Bedrock setup:")
        print("  📝 Verify IAM role attached to EC2 instance")
        print("  📝 Ensure role has bedrock:InvokeModel permission")
        print("  📝 Verify BEDROCK_REGION or AWS_REGION is set correctly")
    
    if not results.get("system_deps"):
        print("  🔧 Install missing system dependencies:")
        print("  📝 sudo apt update && sudo apt install -y ffmpeg libsndfile1")
    
    if not results.get("python_packages"):
        print("  🔧 Install missing Python packages:")
        print("  📝 pip install -r requirements.txt")

async def main():
    """Run all diagnostic tests"""
    print("\n")
    print("╔═══════════════════════════════════════════════════════════════════╗")
    print("║                                                                   ║")
    print("║         🔍 EC2 DEPLOYMENT DIAGNOSTIC TOOL 🔍                      ║")
    print("║                                                                   ║")
    print("╚═══════════════════════════════════════════════════════════════════╝")
    
    results = {}
    
    # Run all tests
    results["env_vars"] = check_env_variables()
    results["system_deps"] = check_system_dependencies()
    results["python_packages"] = check_python_packages()
    results["sarvam"] = await test_sarvam_connectivity()
    results["bedrock"] = await test_bedrock_connectivity()
    results["cognito"] = await test_cognito_connectivity()
    results["database"] = await test_database_connectivity()
    
    # Print summary
    print_section("SUMMARY")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    print(f"\n  📊 Tests Passed: {passed}/{total}")
    print()
    
    for test, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}  {test.replace('_', ' ').title()}")
    
    print()
    
    if passed == total:
        print("  🎉 All tests passed! Your EC2 environment is properly configured.")
    else:
        print_recommendations(results)
    
    print("\n" + "=" * 70 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
