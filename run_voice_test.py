#!/usr/bin/env python3
"""
Voice Test Runner - Complete Voice-based Testing System
======================================================
Triggers real calls and monitors the complete voice pipeline:
Call → Customer Answers → Greeting → Voice Input → Sarvam STT → Claude LLM → Sarvam TTS → Customer

Usage:
    python run_voice_test.py                    # Interactive mode
    python run_voice_test.py --call vijay       # Call specific customer
    python run_voice_test.py --monitor          # Monitor mode only
"""

import asyncio
import argparse
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from voice_call_tester import VoiceCallTester
from voice_websocket_monitor import VoiceWebSocketMonitor

class VoiceTestRunner:
    """
    Complete voice testing system that combines call triggering with monitoring
    """
    
    def __init__(self):
        self.call_tester = VoiceCallTester()
        self.websocket_monitor = VoiceWebSocketMonitor()
    
    async def run_complete_voice_test(self, customer_key: str = "test_customer_1"):
        """
        Run complete voice test: Trigger call + Monitor voice pipeline
        """
        print("🎙️ Complete Voice Test Starting")
        print("=" * 60)
        print("📋 Test Flow:")
        print("   1. Trigger call to customer")
        print("   2. Monitor WebSocket connections")
        print("   3. Track voice pipeline: STT → Claude → TTS")
        print("   4. Display real-time voice interactions")
        print("=" * 60)
        
        # Step 1: Trigger the call
        print("📞 Step 1: Triggering call...")
        call_result = await self.call_tester.trigger_test_call(customer_key)
        
        if not call_result["success"]:
            print(f"❌ Failed to trigger call: {call_result['error']}")
            return
        
        call_sid = call_result["call_sid"]
        customer_data = call_result["customer_data"]
        
        print(f"✅ Call triggered successfully!")
        print(f"   Call SID: {call_sid}")
        print(f"   Customer: {customer_data['name']} ({customer_data['phone']})")
        
        # Step 2: Start monitoring
        print(f"\n🎧 Step 2: Starting voice pipeline monitoring...")
        print("   Waiting for customer to answer...")
        
        # Give some time for call to connect
        await asyncio.sleep(5)
        
        # Step 3: Monitor the voice interactions
        print(f"📊 Step 3: Monitoring voice interactions...")
        await self.websocket_monitor.monitor_call(call_sid, duration_minutes=5)
        
        print("\n🏁 Voice test completed!")
    
    async def run_interactive_voice_test(self):
        """Run interactive voice testing"""
        print("🎮 Interactive Voice Testing System")
        print("=" * 60)
        print("Available commands:")
        print("   call <customer> - Trigger voice call (vijay/priya)")
        print("   monitor <call_sid> - Monitor specific call")
        print("   status - Show system status")
        print("   test <customer> - Complete voice test")
        print("   help - Show this help")
        print("   quit - Exit")
        print("=" * 60)
        
        while True:
            try:
                command = input("\n🎙️ Voice> ").strip().lower()
                
                if command in ["quit", "exit", "q"]:
                    print("👋 Goodbye!")
                    break
                
                elif command == "help":
                    await self._show_help()
                
                elif command == "status":
                    await self.call_tester._show_system_status()
                
                elif command.startswith("call "):
                    customer = command.split(" ", 1)[1]
                    customer_key = f"test_customer_1" if customer == "vijay" else "test_customer_2"
                    
                    result = await self.call_tester.trigger_test_call(customer_key)
                    if result["success"]:
                        print(f"✅ Call triggered! Call SID: {result['call_sid']}")
                    else:
                        print(f"❌ Call failed: {result['error']}")
                
                elif command.startswith("monitor "):
                    call_sid = command.split(" ", 1)[1]
                    print(f"🎧 Monitoring call {call_sid}...")
                    await self.websocket_monitor.monitor_call(call_sid, 3)
                
                elif command.startswith("test "):
                    customer = command.split(" ", 1)[1]
                    customer_key = f"test_customer_1" if customer == "vijay" else "test_customer_2"
                    
                    print(f"🎯 Running complete voice test for {customer}...")
                    await self.run_complete_voice_test(customer_key)
                
                elif command == "demo":
                    await self._run_demo()
                
                else:
                    print("❓ Unknown command. Type 'help' for available commands.")
                    
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    async def _show_help(self):
        """Show help information"""
        print("\n📖 Voice Testing Help:")
        print("=" * 40)
        print("🎯 Complete Voice Test:")
        print("   test vijay    - Full voice test with Vijay")
        print("   test priya    - Full voice test with Priya")
        print("")
        print("📞 Call Management:")
        print("   call vijay    - Trigger call to Vijay")
        print("   call priya    - Trigger call to Priya")
        print("")
        print("🎧 Monitoring:")
        print("   monitor <sid> - Monitor specific call")
        print("   status        - Show system status")
        print("")
        print("🎙️ Expected Voice Flow:")
        print("   1. Customer answers call")
        print("   2. System: 'Hello [Name], this is SIF Bank...'")
        print("   3. Customer speaks (any response)")
        print("   4. Sarvam STT converts speech to text")
        print("   5. Claude processes and generates response")
        print("   6. Sarvam TTS converts response to speech")
        print("   7. Customer hears AI response")
        print("   8. Conversation continues...")
    
    async def _run_demo(self):
        """Run a demo voice test"""
        print("🎬 Running Voice Test Demo...")
        print("   This will trigger a call to Vijay and monitor the voice pipeline")
        
        confirm = input("Continue with demo? (y/n): ").strip().lower()
        if confirm == "y":
            await self.run_complete_voice_test("test_customer_1")
        else:
            print("Demo cancelled")

async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Voice-based Testing System")
    parser.add_argument("--call", type=str, choices=["vijay", "priya"],
                       help="Trigger call to specific customer")
    parser.add_argument("--monitor", action="store_true",
                       help="Monitor mode only")
    parser.add_argument("--test", type=str, choices=["vijay", "priya"],
                       help="Run complete voice test")
    parser.add_argument("--interactive", "-i", action="store_true",
                       help="Interactive mode")
    
    args = parser.parse_args()
    
    print("🎙️ Voice-based Testing System")
    print("=" * 60)
    
    runner = VoiceTestRunner()
    
    try:
        if args.call:
            customer_key = "test_customer_1" if args.call == "vijay" else "test_customer_2"
            result = await runner.call_tester.trigger_test_call(customer_key)
            
            if result["success"]:
                print(f"✅ Call triggered successfully!")
                print(f"   Call SID: {result['call_sid']}")
                print(f"   Customer: {result['customer_data']['name']}")
            else:
                print(f"❌ Call failed: {result['error']}")
        
        elif args.monitor:
            print("🎧 Starting monitoring mode...")
            await runner.websocket_monitor.monitor_dashboard_websocket()
        
        elif args.test:
            customer_key = "test_customer_1" if args.test == "vijay" else "test_customer_2"
            await runner.run_complete_voice_test(customer_key)
        
        else:
            # Default to interactive mode
            await runner.run_interactive_voice_test()
            
    except KeyboardInterrupt:
        print("\n👋 Test interrupted")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
