#!/usr/bin/env python3
"""
Simple Speech-to-Speech Test Runner
==================================
Quick test runner for the speech-to-speech pipeline.

Usage:
    python run_speech_test.py
    python run_speech_test.py --interactive
    python run_speech_test.py --single "Hello, I need help with my loan"
"""

import asyncio
import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from test_speech_to_speech_pipeline import SpeechToSpeechTester, run_predefined_tests
from test_config import validate_environment, get_test_config

async def run_single_test(input_text: str):
    """Run a single test with given input"""
    print(f"🎯 Running single test: '{input_text}'")
    print("=" * 60)
    
    tester = SpeechToSpeechTester()
    result = await tester.run_complete_pipeline(input_text)
    
    print(f"\n📊 Results:")
    print(f"   Success: {result['success']}")
    print(f"   Transcript: {result['transcript']}")
    print(f"   Claude Response: {result['claude_response']}")
    print(f"   Audio Generated: {result['audio_generated']}")
    
    if result['error']:
        print(f"   Error: {result['error']}")

async def run_interactive():
    """Run interactive mode"""
    tester = SpeechToSpeechTester()
    await tester.run_interactive_test()

async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Speech-to-Speech Pipeline Tester")
    parser.add_argument("--interactive", "-i", action="store_true", 
                       help="Run in interactive mode")
    parser.add_argument("--single", "-s", type=str, 
                       help="Run single test with given input")
    parser.add_argument("--quick", "-q", action="store_true",
                       help="Run quick test with predefined scenarios")
    
    args = parser.parse_args()
    
    # Validate environment
    is_valid, missing_vars = validate_environment()
    if not is_valid:
        print(f"❌ Missing environment variables: {missing_vars}")
        print("\nPlease set the following environment variables:")
        for var in missing_vars:
            print(f"   export {var}=your_value_here")
        return
    
    print("✅ Environment validated")
    
    try:
        if args.single:
            await run_single_test(args.single)
        elif args.interactive:
            await run_interactive()
        elif args.quick:
            # Run just first 3 scenarios for quick test
            print("🚀 Running Quick Test (3 scenarios)")
            tester = SpeechToSpeechTester()
            quick_scenarios = [
                "Hello, I received a call about my loan payment",
                "What are my payment options?",
                "I want to speak to a manager"
            ]
            
            for i, scenario in enumerate(quick_scenarios, 1):
                print(f"\n🧪 Quick Test {i}/{len(quick_scenarios)}")
                result = await tester.run_complete_pipeline(scenario)
                print(f"   Result: {'✅ Success' if result['success'] else '❌ Failed'}")
                if not result['success']:
                    print(f"   Error: {result['error']}")
        else:
            await run_predefined_tests()
            
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"❌ Error running test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
