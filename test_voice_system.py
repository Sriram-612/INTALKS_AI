#!/usr/bin/env python3
"""
Quick Voice System Test
======================
Tests the voice system components without triggering actual calls
"""

import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from voice_call_tester import VoiceCallTester

async def test_voice_system():
    """Test voice system components"""
    print("🧪 Testing Voice System Components")
    print("=" * 50)
    
    try:
        # Initialize voice call tester
        print("1. Initializing Voice Call Tester...")
        tester = VoiceCallTester()
        print("✅ Voice Call Tester initialized successfully")
        
        # Test system status
        print("\n2. Testing System Status...")
        await tester._show_system_status()
        
        # Test customer data
        print("\n3. Testing Customer Data...")
        customers = tester.test_customers
        print(f"✅ Loaded {len(customers)} test customers:")
        for key, customer in customers.items():
            print(f"   - {key}: {customer['name']} ({customer['phone']})")
        
        print("\n✅ All voice system components are working!")
        print("\n🎯 Ready for voice testing!")
        print("   Use: python run_voice_test.py")
        print("   Or: python run_voice_test.py --test vijay")
        
    except Exception as e:
        print(f"❌ Error testing voice system: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_voice_system())
