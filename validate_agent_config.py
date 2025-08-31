#!/usr/bin/env python3
"""
Agent Number Configuration Validator
Validates that all files are using AGENT_PHONE_NUMBER from environment variables
"""

import os
import re
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def validate_agent_configuration():
    """Validate that agent phone number is properly configured"""
    print("🔍 Agent Number Configuration Validator")
    print("=" * 50)
    
    # Check if AGENT_PHONE_NUMBER is set in environment
    agent_number = os.getenv("AGENT_PHONE_NUMBER")
    if agent_number:
        print(f"✅ AGENT_PHONE_NUMBER found in environment: {agent_number}")
    else:
        print("❌ AGENT_PHONE_NUMBER not found in environment variables!")
        return False
    
    # Files that should be using environment variable
    files_to_check = [
        "main.py",
        "services/call_management.py", 
        "utils/connect_agent.py",
        "utils/agent_transfer.py",
        "analyze_calls.py"
    ]
    
    print(f"\n🔍 Checking {len(files_to_check)} files for proper agent number usage...")
    
    all_good = True
    
    for file_path in files_to_check:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Check if file uses os.getenv("AGENT_PHONE_NUMBER") 
            env_var_patterns = [
                'os.getenv("AGENT_PHONE_NUMBER")',
                "os.getenv('AGENT_PHONE_NUMBER')",
                'os.getenv("AGENT_PHONE_NUMBER",',  # With default value
                "os.getenv('AGENT_PHONE_NUMBER',"   # With default value
            ]
            
            uses_env_var = any(pattern in content for pattern in env_var_patterns)
            
            if uses_env_var:
                print(f"✅ {file_path}: Using environment variable correctly")
            else:
                print(f"⚠️  {file_path}: May not be using environment variable")
                all_good = False
        else:
            print(f"❌ {file_path}: File not found")
            all_good = False
    
    print("\n" + "=" * 50)
    if all_good:
        print("🎉 All files are properly configured!")
        print(f"📞 Current agent number: {agent_number}")
        print("\n💡 To change the agent number:")
        print("   1. Update AGENT_PHONE_NUMBER in .env file")
        print("   2. Restart your application")
        print("   3. All calls will now be transferred to the new number")
    else:
        print("⚠️  Some files may need manual updates")
    
    return all_good

if __name__ == "__main__":
    validate_agent_configuration()
