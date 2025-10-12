#!/usr/bin/env python3
"""
Voice Call Tester - Real Voice-based Testing System
==================================================
This system triggers actual calls and handles real voice interactions:
Call Trigger → Customer Answers → Greeting → Voice Input → Sarvam STT → Claude LLM → Sarvam TTS → Customer

Features:
- Triggers real calls using existing Exotel infrastructure
- Handles live voice interactions via WebSocket
- Real-time speech processing pipeline
- Uses existing voice bot components
"""

import os
import sys
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional
import traceback
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import existing components
from services.call_management import CallManagementService
from database.schemas import get_session
from utils.production_asr import ProductionSarvamHandler
from utils import bedrock_client
from utils.logger import logger
from utils.redis_session import redis_manager

class VoiceCallTester:
    """
    Real voice call testing system that integrates with existing infrastructure
    """
    
    def __init__(self):
        """Initialize the voice call tester"""
        self.call_service = CallManagementService()
        self.sarvam_handler = ProductionSarvamHandler(os.getenv("SARVAM_API_KEY"))
        self.redis_manager = redis_manager
        self.base_url = os.getenv("BASE_URL", "https://9a81252242ca.ngrok-free.app")
        
        # Test customer data
        self.test_customers = self._get_test_customers()
        
        print("🎙️ Voice Call Tester Initialized")
        print(f"🌐 Base URL: {self.base_url}")
        print(f"👥 Test customers loaded: {len(self.test_customers)}")
        print("=" * 60)
    
    def _get_test_customers(self) -> Dict[str, Dict[str, Any]]:
        """Get test customer data"""
        return {
            "test_customer_1": {
                "name": "Vijay",
                "phone": "+919384531725",
                "loan_id": "LOAN123456",
                "amount": "15000",
                "due_date": "2024-01-15",
                "state": "Karnataka",
                "language_code": "en-IN"
            },
            "test_customer_2": {
                "name": "Priya Sharma",
                "phone": "+919876543210",
                "loan_id": "LOAN789012",
                "amount": "25000",
                "due_date": "2024-02-01",
                "state": "Maharashtra",
                "language_code": "hi-IN"
            }
        }
    
    async def create_test_customer_in_db(self, customer_data: Dict[str, Any]) -> str:
        """Create test customer in database and return customer ID"""
        try:
            session = get_session()
            
            # Import database models
            from database.schemas import Customer, Loan
            
            # Check if customer already exists
            existing_customer = session.query(Customer).filter_by(
                primary_phone=customer_data["phone"]
            ).first()
            
            if existing_customer:
                print(f"✅ Customer already exists: {existing_customer.full_name} (ID: {existing_customer.id})")
                return str(existing_customer.id)
            
            # Create new customer
            customer = Customer(
                full_name=customer_data["name"],
                primary_phone=customer_data["phone"],
                state=customer_data["state"],
                language_preference=customer_data["language_code"]
            )
            session.add(customer)
            session.flush()  # Get the ID
            
            # Create loan for customer
            loan = Loan(
                customer_id=customer.id,
                loan_id=customer_data["loan_id"],
                outstanding_amount=float(customer_data["amount"]),
                next_due_date=customer_data["due_date"]
            )
            session.add(loan)
            session.commit()
            
            print(f"✅ Created test customer: {customer.full_name} (ID: {customer.id})")
            return str(customer.id)
            
        except Exception as e:
            print(f"❌ Error creating test customer: {e}")
            session.rollback()
            return None
        finally:
            session.close()
    
    async def trigger_test_call(self, customer_key: str) -> Dict[str, Any]:
        """Trigger a test call to a specific customer"""
        if customer_key not in self.test_customers:
            return {"success": False, "error": f"Customer {customer_key} not found"}
        
        customer_data = self.test_customers[customer_key]
        print(f"📞 Triggering test call to: {customer_data['name']} ({customer_data['phone']})")
        
        try:
            # Create customer in database if not exists
            customer_id = await self.create_test_customer_in_db(customer_data)
            if not customer_id:
                return {"success": False, "error": "Failed to create customer in database"}
            
            # Trigger call using existing call management service
            result = await self.call_service.trigger_single_call(customer_id)
            
            if result.get("success"):
                call_sid = result.get("call_sid")
                print(f"✅ Call triggered successfully!")
                print(f"   Call SID: {call_sid}")
                print(f"   Customer: {customer_data['name']}")
                print(f"   Phone: {customer_data['phone']}")
                print(f"   Expected flow: Greeting → Voice Input → STT → Claude → TTS → Customer")
                
                return {
                    "success": True,
                    "call_sid": call_sid,
                    "customer_data": customer_data,
                    "customer_id": customer_id
                }
            else:
                return {"success": False, "error": result.get("error", "Unknown error")}
                
        except Exception as e:
            print(f"❌ Error triggering call: {e}")
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    async def monitor_call_status(self, call_sid: str, duration_minutes: int = 5):
        """Monitor call status and WebSocket activity"""
        print(f"📊 Monitoring call {call_sid} for {duration_minutes} minutes...")
        print("🎧 Expected voice flow:")
        print("   1. Customer answers call")
        print("   2. System plays greeting")
        print("   3. Customer speaks")
        print("   4. Sarvam STT processes speech")
        print("   5. Claude generates response")
        print("   6. Sarvam TTS converts to speech")
        print("   7. Customer hears response")
        print("=" * 50)
        
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)
        
        while time.time() < end_time:
            try:
                # Check call status in database
                session = get_session()
                from database.schemas import get_call_session_by_sid
                
                call_session = get_call_session_by_sid(session, call_sid)
                if call_session:
                    print(f"📞 Call Status: {call_session.status}")
                    
                    if call_session.status in ["call_completed", "call_failed"]:
                        print(f"🏁 Call ended with status: {call_session.status}")
                        break
                
                session.close()
                
                # Wait before next check
                await asyncio.sleep(10)
                
            except Exception as e:
                print(f"❌ Error monitoring call: {e}")
                await asyncio.sleep(10)
        
        print("📊 Call monitoring completed")
    
    async def run_interactive_voice_test(self):
        """Run interactive voice testing session"""
        print("\n🎮 Interactive Voice Call Testing")
        print("Available test customers:")
        
        for key, customer in self.test_customers.items():
            print(f"   {key}: {customer['name']} ({customer['phone']})")
        
        print("\nCommands:")
        print("   call <customer_key> - Trigger call to customer")
        print("   monitor <call_sid> - Monitor active call")
        print("   status - Show system status")
        print("   quit - Exit")
        print("=" * 60)
        
        while True:
            try:
                command = input("\n🎙️ Voice Test> ").strip().lower()
                
                if command == "quit" or command == "exit":
                    print("👋 Goodbye!")
                    break
                
                elif command == "status":
                    await self._show_system_status()
                
                elif command.startswith("call "):
                    customer_key = command.split(" ", 1)[1]
                    result = await self.trigger_test_call(customer_key)
                    
                    if result["success"]:
                        call_sid = result["call_sid"]
                        print(f"\n🎯 Call triggered! Now monitoring...")
                        
                        # Ask if user wants to monitor
                        monitor = input("Monitor this call? (y/n): ").strip().lower()
                        if monitor == "y":
                            await self.monitor_call_status(call_sid)
                    else:
                        print(f"❌ Call failed: {result['error']}")
                
                elif command.startswith("monitor "):
                    call_sid = command.split(" ", 1)[1]
                    await self.monitor_call_status(call_sid)
                
                elif command == "help":
                    print("\nAvailable commands:")
                    print("   call test_customer_1 - Call Vijay")
                    print("   call test_customer_2 - Call Priya")
                    print("   monitor <call_sid> - Monitor active call")
                    print("   status - Show system status")
                
                else:
                    print("❓ Unknown command. Type 'help' for available commands.")
                    
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    async def _show_system_status(self):
        """Show system status"""
        print("\n📊 System Status:")
        print(f"   Base URL: {self.base_url}")
        print(f"   Sarvam API: {'✅ Configured' if os.getenv('SARVAM_API_KEY') else '❌ Missing'}")
        print(f"   AWS/Claude: {'✅ Configured' if os.getenv('AWS_ACCESS_KEY_ID') else '❌ Missing'}")
        print(f"   Exotel: {'✅ Configured' if os.getenv('EXOTEL_SID') else '❌ Missing'}")
        
        # Test database connection
        try:
            session = get_session()
            session.execute("SELECT 1")
            session.close()
            print(f"   Database: ✅ Connected")
        except:
            print(f"   Database: ❌ Connection failed")
        
        # Test Redis connection
        try:
            if self.redis_manager.test_connection():
                print(f"   Redis: ✅ Connected")
            else:
                print(f"   Redis: ❌ Connection failed")
        except:
            print(f"   Redis: ❌ Connection failed")
    
    async def run_automated_voice_test(self, customer_key: str):
        """Run automated voice test for a specific customer"""
        print(f"🤖 Running automated voice test for {customer_key}")
        
        # Trigger call
        result = await self.trigger_test_call(customer_key)
        
        if not result["success"]:
            print(f"❌ Failed to trigger call: {result['error']}")
            return
        
        call_sid = result["call_sid"]
        customer_data = result["customer_data"]
        
        print(f"✅ Call triggered successfully!")
        print(f"📞 Call SID: {call_sid}")
        print(f"👤 Customer: {customer_data['name']}")
        print(f"📱 Phone: {customer_data['phone']}")
        print("\n🎯 Expected Voice Flow:")
        print("   1. Customer answers → Exotel connects")
        print("   2. WebSocket established → Voice bot starts")
        print("   3. Greeting played → Customer hears introduction")
        print("   4. Customer speaks → Audio captured")
        print("   5. Sarvam STT → Speech converted to text")
        print("   6. Claude processes → AI generates response")
        print("   7. Sarvam TTS → Response converted to speech")
        print("   8. Customer hears → AI response played")
        print("   9. Conversation continues...")
        
        # Monitor the call
        await self.monitor_call_status(call_sid, duration_minutes=3)
        
        return result

async def main():
    """Main function"""
    print("🎙️ Voice Call Tester - Real Voice-based Testing")
    print("=" * 60)
    
    # Check environment
    required_vars = ["SARVAM_API_KEY", "AWS_ACCESS_KEY_ID", "EXOTEL_SID", "EXOTEL_TOKEN"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"❌ Missing environment variables: {missing_vars}")
        return
    
    print("✅ Environment validated")
    
    tester = VoiceCallTester()
    
    # Choose test mode
    print("\nSelect test mode:")
    print("1. Interactive voice testing")
    print("2. Automated test (Vijay)")
    print("3. Automated test (Priya)")
    
    try:
        choice = input("Enter choice (1-3): ").strip()
        
        if choice == "1":
            await tester.run_interactive_voice_test()
        elif choice == "2":
            await tester.run_automated_voice_test("test_customer_1")
        elif choice == "3":
            await tester.run_automated_voice_test("test_customer_2")
        else:
            print("Invalid choice. Running interactive mode...")
            await tester.run_interactive_voice_test()
            
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
