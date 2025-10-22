#!/usr/bin/env python3
"""
Simple Voice Test - File-based Voice Testing
===========================================
Simplified voice testing system that:
1. Triggers real calls automatically
2. Uses file-based audio input/output (no microphone needed)
3. Processes through Sarvam STT → Claude → Sarvam TTS
4. Simulates voice conversations with pre-recorded responses
5. Works independently without affecting main.py

Usage:
    python simple_voice_test.py
    python simple_voice_test.py --customer vijay --auto-call
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

# Load environment variables
load_dotenv()

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import existing components
from utils.production_asr import ProductionSarvamHandler
from utils import bedrock_client
from utils.logger import logger
from services.call_management import CallManagementService
from database.schemas import get_session

class SimpleVoiceTest:
    """
    Simple voice testing system with file-based audio
    """
    
    def __init__(self):
        """Initialize simple voice test system"""
        self.sarvam_handler = ProductionSarvamHandler(os.getenv("SARVAM_API_KEY"))
        self.call_service = CallManagementService()
        
        # Conversation state
        self.conversation_history = {}
        self.active_call_sid = None
        
        # Test customers
        self.test_customers = self._get_test_customers()
        
        # Create output directories
        self.audio_dir = Path("voice_test_audio")
        self.audio_dir.mkdir(exist_ok=True)
        
        print("🎙️ Simple Voice Test System Initialized")
        print("📁 Audio files will be saved to: voice_test_audio/")
        print("📞 Independent call triggering enabled")
        print("=" * 60)
    
    def _get_test_customers(self) -> Dict[str, Dict[str, Any]]:
        """Get test customer data"""
        return {
            "vijay": {
                "name": "Vijay",
                "phone": "+919384531725",
                "loan_id": "LOAN123456",
                "amount": "15000",
                "due_date": "2024-01-15",
                "state": "Karnataka",
                "language_code": "en-IN"
            },
            "priya": {
                "name": "Priya Sharma",
                "phone": "+919876543210",
                "loan_id": "LOAN789012",
                "amount": "25000",
                "due_date": "2024-02-01",
                "state": "Maharashtra",
                "language_code": "hi-IN"
            }
        }
    
    async def trigger_test_call(self, customer_key: str) -> Dict[str, Any]:
        """Trigger a real call to test customer"""
        if customer_key not in self.test_customers:
            return {"success": False, "error": f"Customer {customer_key} not found"}
        
        customer_data = self.test_customers[customer_key]
        print(f"📞 Triggering call to: {customer_data['name']} ({customer_data['phone']})")
        
        try:
            # Create customer in database if not exists
            customer_id = await self._create_test_customer_in_db(customer_data)
            if not customer_id:
                return {"success": False, "error": "Failed to create customer in database"}
            
            # Trigger call using existing call management service
            result = await self.call_service.trigger_single_call(customer_id)
            
            if result.get("success"):
                self.active_call_sid = result.get("call_sid")
                print(f"✅ Call triggered successfully!")
                print(f"   Call SID: {self.active_call_sid}")
                print(f"   Customer: {customer_data['name']}")
                
                return {
                    "success": True,
                    "call_sid": self.active_call_sid,
                    "customer_data": customer_data,
                    "customer_id": customer_id
                }
            else:
                return {"success": False, "error": result.get("error", "Unknown error")}
                
        except Exception as e:
            print(f"❌ Error triggering call: {e}")
            return {"success": False, "error": str(e)}
    
    async def _create_test_customer_in_db(self, customer_data: Dict[str, Any]) -> str:
        """Create test customer in database"""
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
    
    async def simulate_voice_input(self, text_input: str, customer_data: Dict[str, Any]) -> str:
        """Simulate voice input by converting text to audio first, then processing"""
        try:
            print(f"🎤 Simulating customer voice: '{text_input}'")
            
            # Step 1: Convert text to audio (simulate customer speaking)
            print("🔄 Step 1: Converting text to audio (customer speech simulation)...")
            customer_audio = await self.sarvam_handler.synthesize_tts(text_input, customer_data['language_code'])
            print(f"   Generated {len(customer_audio)} bytes of customer audio")
            
            # Save customer audio
            customer_audio_file = self.audio_dir / f"customer_input_{int(time.time())}.raw"
            with open(customer_audio_file, "wb") as f:
                f.write(customer_audio)
            print(f"   Saved customer audio: {customer_audio_file}")
            
            # Step 2: Process customer audio through STT
            print("📝 Step 2: Converting speech to text (STT)...")
            transcript_result = await self.sarvam_handler.transcribe_from_payload(customer_audio)
            
            if isinstance(transcript_result, tuple):
                transcript, detected_language = transcript_result
                language = detected_language or customer_data['language_code']
            else:
                transcript = transcript_result
                language = customer_data['language_code']
            
            print(f"   Transcript: '{transcript}'")
            print(f"   Language: {language}")
            
            if not transcript or transcript.strip() == "":
                return "I'm sorry, I didn't catch that. Could you please repeat?"
            
            # Step 3: Process with Claude
            print("🤖 Step 3: Processing with Claude LLM...")
            ai_response = await self._process_with_claude(transcript, customer_data, language)
            print(f"   Claude Response: '{ai_response}'")
            
            # Step 4: Convert AI response to speech
            print("🔊 Step 4: Converting AI response to speech (TTS)...")
            ai_audio = await self.sarvam_handler.synthesize_tts(ai_response, language)
            print(f"   Generated {len(ai_audio)} bytes of AI audio")
            
            # Save AI audio
            ai_audio_file = self.audio_dir / f"ai_response_{int(time.time())}.raw"
            with open(ai_audio_file, "wb") as f:
                f.write(ai_audio)
            print(f"   Saved AI audio: {ai_audio_file}")
            
            print("✅ Voice processing completed!")
            return ai_response
            
        except Exception as e:
            print(f"❌ Error processing voice input: {e}")
            traceback.print_exc()
            return "I apologize, I'm having technical difficulties."
    
    async def _process_with_claude(self, transcript: str, customer_data: Dict[str, Any], language: str) -> str:
        """Process transcript with Claude LLM"""
        try:
            conversation_id = self.active_call_sid or "voice_test"
            
            # Initialize conversation if not exists
            if conversation_id not in self.conversation_history:
                system_prompt = self._build_system_prompt(customer_data, language)
                self.conversation_history[conversation_id] = [{
                    "role": "system",
                    "content": system_prompt
                }]
            
            # Add user message
            self.conversation_history[conversation_id].append({
                "role": "user",
                "content": transcript
            })
            
            # Prepare messages for Claude
            bedrock_messages = []
            system_content = ""
            
            for msg in self.conversation_history[conversation_id]:
                if msg["role"] == "system":
                    system_content = msg["content"]
                else:
                    content = msg["content"]
                    if isinstance(content, str):
                        formatted_content = [{"type": "text", "text": content}]
                    else:
                        formatted_content = content
                    
                    bedrock_messages.append({
                        "role": msg["role"],
                        "content": formatted_content
                    })
            
            # Add system message
            if system_content:
                bedrock_messages.insert(0, {
                    "role": "user",
                    "content": [{"type": "text", "text": system_content.strip()}]
                })
            
            # Get Claude model ID
            claude_model_id = os.getenv("CLAUDE_MODEL_ID", 
                "arn:aws:bedrock:eu-north-1:844605843483:inference-profile/eu.anthropic.claude-3-7-sonnet-20250219-v1:0")
            
            # Call Claude
            response_text = bedrock_client.invoke_claude_model(bedrock_messages, claude_model_id)
            
            # Add response to history
            self.conversation_history[conversation_id].append({
                "role": "assistant",
                "content": response_text
            })
            
            return response_text.strip()
            
        except Exception as e:
            print(f"❌ Claude Error: {e}")
            return "I apologize, I'm having technical difficulties. Let me transfer you to a human agent."
    
    def _build_system_prompt(self, customer_data: Dict[str, Any], language: str) -> str:
        """Build system prompt for customer"""
        return f"""You are a Collections Voice Agent for South India Finvest Bank (SIF).

CUSTOMER CONTEXT:
- Name: {customer_data['name']}
- Phone: {customer_data['phone']}
- Loan ID: {customer_data['loan_id']}
- Outstanding Amount: ₹{customer_data['amount']}
- Due Date: {customer_data['due_date']}
- State: {customer_data['state']}
- Language: {language}

GUIDELINES:
- Greet, ask for consent, then verify identity before sharing details
- Be concise (<=2 sentences). Offer payment options and human handoff
- No threats; be empathetic. Support language: {language}
- If user interrupts, pause and let them speak (barge-in friendly)
- Provide helpful payment solutions and maintain professional tone
- Keep responses conversational and suitable for voice calls

IMPORTANT: Always respond in a helpful, empathetic manner focusing on finding solutions for the customer."""
    
    async def run_voice_conversation(self, customer_key: str, auto_call: bool = False):
        """Run voice conversation simulation"""
        if customer_key not in self.test_customers:
            print(f"❌ Customer '{customer_key}' not found")
            return
        
        customer_data = self.test_customers[customer_key]
        print(f"🎬 Starting voice conversation with {customer_data['name']}")
        print("=" * 60)
        
        # Trigger call if requested
        if auto_call:
            print("📞 Auto-triggering call...")
            call_result = await self.trigger_test_call(customer_key)
            if not call_result["success"]:
                print(f"❌ Failed to trigger call: {call_result['error']}")
                return
            
            print("⏳ Waiting 5 seconds for call setup...")
            await asyncio.sleep(5)
        
        print("\n🎙️ Voice Conversation Started")
        print("Commands:")
        print("   Type your message to simulate customer speech")
        print("   Type 'quit' to end conversation")
        print("   Type 'call' to trigger a call")
        print("=" * 60)
        
        turn = 1
        while True:
            try:
                user_input = input(f"\n🎯 Turn {turn} - Customer says: ").strip()
                
                if user_input.lower() == 'quit':
                    print("👋 Ending voice conversation")
                    break
                
                elif user_input.lower() == 'call':
                    print("📞 Triggering call...")
                    call_result = await self.trigger_test_call(customer_key)
                    if call_result["success"]:
                        print(f"✅ Call triggered: {call_result['call_sid']}")
                    else:
                        print(f"❌ Call failed: {call_result['error']}")
                    continue
                
                elif user_input:
                    print(f"\n🔄 Processing voice input...")
                    
                    # Process through voice pipeline
                    ai_response = await self.simulate_voice_input(user_input, customer_data)
                    
                    print(f"\n🤖 AI Agent says: '{ai_response}'")
                    print("✅ Turn completed!")
                    
                    turn += 1
                else:
                    print("❓ Please enter a message or 'quit' to exit")
                    
            except KeyboardInterrupt:
                print("\n👋 Voice conversation interrupted")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    async def run_predefined_conversation(self, customer_key: str, auto_call: bool = False):
        """Run predefined conversation scenario"""
        if customer_key not in self.test_customers:
            print(f"❌ Customer '{customer_key}' not found")
            return
        
        customer_data = self.test_customers[customer_key]
        print(f"🎭 Running predefined conversation with {customer_data['name']}")
        print("=" * 60)
        
        # Trigger call if requested
        if auto_call:
            print("📞 Auto-triggering call...")
            call_result = await self.trigger_test_call(customer_key)
            if not call_result["success"]:
                print(f"❌ Failed to trigger call: {call_result['error']}")
                return
            
            print("⏳ Waiting 5 seconds for call setup...")
            await asyncio.sleep(5)
        
        # Predefined conversation scripts
        conversations = {
            "vijay": [
                "Hello, I received a call about my loan payment",
                "I want to know about my outstanding amount",
                "What payment options do I have?",
                "Can I pay in two installments?",
                "Thank you for your help"
            ],
            "priya": [
                "मुझे अपने लोन के बारे में जानकारी चाहिए",
                "मैं पेमेंट करना चाहता हूं",
                "क्या कोई छूट मिल सकती है?",
                "धन्यवाद"
            ]
        }
        
        conversation_script = conversations.get(customer_key, conversations["vijay"])
        
        print(f"\n🎬 Starting predefined conversation ({len(conversation_script)} turns)")
        print("=" * 60)
        
        for i, customer_input in enumerate(conversation_script, 1):
            print(f"\n🎯 Turn {i}/{len(conversation_script)}")
            print(f"👤 Customer: '{customer_input}'")
            
            # Process through voice pipeline
            ai_response = await self.simulate_voice_input(customer_input, customer_data)
            
            print(f"🤖 AI Agent: '{ai_response}'")
            print("✅ Turn completed!")
            
            # Add delay between turns
            await asyncio.sleep(2)
        
        print(f"\n🏁 Predefined conversation completed!")
        print(f"📁 Audio files saved in: {self.audio_dir}/")

async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Simple Voice Test System")
    parser.add_argument("--customer", type=str, choices=["vijay", "priya"],
                       help="Customer to test with")
    parser.add_argument("--auto-call", action="store_true",
                       help="Automatically trigger call")
    parser.add_argument("--predefined", action="store_true",
                       help="Run predefined conversation")
    parser.add_argument("--interactive", action="store_true",
                       help="Interactive mode")
    
    args = parser.parse_args()
    
    print("🎙️ Simple Voice Test System")
    print("=" * 60)
    print("📁 File-based audio processing")
    print("📞 Independent call triggering")
    print("🎯 Complete voice pipeline testing")
    print("=" * 60)
    
    system = SimpleVoiceTest()
    
    try:
        if args.customer:
            if args.predefined:
                await system.run_predefined_conversation(args.customer, args.auto_call)
            else:
                await system.run_voice_conversation(args.customer, args.auto_call)
        
        elif args.interactive:
            # Interactive mode
            print("🎮 Interactive Voice Testing")
            print("Available customers: vijay, priya")
            
            while True:
                customer = input("\nSelect customer (vijay/priya) or 'quit': ").strip().lower()
                
                if customer == 'quit':
                    break
                elif customer in ["vijay", "priya"]:
                    auto_call = input("Auto-trigger call? (y/n): ").strip().lower() == 'y'
                    predefined = input("Use predefined conversation? (y/n): ").strip().lower() == 'y'
                    
                    if predefined:
                        await system.run_predefined_conversation(customer, auto_call)
                    else:
                        await system.run_voice_conversation(customer, auto_call)
                else:
                    print("❌ Invalid customer. Choose 'vijay' or 'priya'")
        
        else:
            # Default: predefined conversation with Vijay and auto-call
            await system.run_predefined_conversation("vijay", auto_call=True)
            
    except KeyboardInterrupt:
        print("\n👋 Test interrupted")
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
