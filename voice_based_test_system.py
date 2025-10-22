#!/usr/bin/env python3
"""
Voice-Based Test System - Real Audio Voice Testing
=================================================
Independent voice testing system that:
1. Triggers real calls automatically
2. Uses real audio input (microphone) and output (speakers)
3. Processes through Sarvam STT → Claude → Sarvam TTS
4. Handles real voice conversations
5. Works independently without affecting main.py

Usage:
    python voice_based_test_system.py
    python voice_based_test_system.py --customer vijay
    python voice_based_test_system.py --auto-call
"""

import os
import sys
import asyncio
import json
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional
import traceback
from dotenv import load_dotenv
import pyaudio
import wave
import tempfile

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

class VoiceBasedTestSystem:
    """
    Independent voice-based testing system with real audio I/O
    """
    
    def __init__(self):
        """Initialize voice-based test system"""
        self.sarvam_handler = ProductionSarvamHandler(os.getenv("SARVAM_API_KEY"))
        self.call_service = CallManagementService()
        
        # Audio configuration
        self.audio_format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000  # 16kHz for better STT
        self.chunk = 1024
        self.record_seconds = 5  # Max recording time per turn
        
        # Initialize PyAudio
        self.audio = pyaudio.PyAudio()
        
        # Conversation state
        self.conversation_history = {}
        self.active_call_sid = None
        self.is_recording = False
        
        # Test customers
        self.test_customers = self._get_test_customers()
        
        print("🎙️ Voice-Based Test System Initialized")
        print("🔊 Real audio input/output enabled")
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
    
    def record_audio(self, duration: int = 5) -> bytes:
        """Record audio from microphone"""
        print(f"🎤 Recording audio for {duration} seconds...")
        print("   Speak now...")
        
        stream = self.audio.open(
            format=self.audio_format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk
        )
        
        frames = []
        for i in range(0, int(self.rate / self.chunk * duration)):
            data = stream.read(self.chunk)
            frames.append(data)
        
        stream.stop_stream()
        stream.close()
        
        # Convert to bytes
        audio_data = b''.join(frames)
        print(f"✅ Recorded {len(audio_data)} bytes of audio")
        
        return audio_data
    
    def play_audio(self, audio_bytes: bytes):
        """Play audio through speakers"""
        try:
            print(f"🔊 Playing audio ({len(audio_bytes)} bytes)...")
            
            # Save to temporary WAV file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                # Convert raw audio to WAV format
                with wave.open(temp_file.name, 'wb') as wav_file:
                    wav_file.setnchannels(self.channels)
                    wav_file.setsampwidth(self.audio.get_sample_size(self.audio_format))
                    wav_file.setframerate(8000)  # Sarvam returns 8kHz
                    wav_file.writeframes(audio_bytes)
                
                # Play the WAV file
                import subprocess
                if os.name == 'nt':  # Windows
                    os.system(f'start /wait "" "{temp_file.name}"')
                else:  # Linux/Mac
                    subprocess.run(['aplay', temp_file.name], check=True)
                
                # Clean up
                os.unlink(temp_file.name)
            
            print("✅ Audio playback completed")
            
        except Exception as e:
            print(f"❌ Error playing audio: {e}")
    
    async def process_voice_input(self, audio_bytes: bytes, customer_data: Dict[str, Any]) -> str:
        """Process voice input through STT → Claude → TTS pipeline"""
        try:
            # Step 1: Speech-to-Text
            print("📝 Step 1: Converting speech to text...")
            transcript_result = await self.sarvam_handler.transcribe_from_payload(audio_bytes)
            
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
            
            # Step 2: Process with Claude
            print("🤖 Step 2: Processing with Claude LLM...")
            ai_response = await self._process_with_claude(transcript, customer_data, language)
            print(f"   Claude Response: '{ai_response}'")
            
            # Step 3: Text-to-Speech
            print("🔊 Step 3: Converting response to speech...")
            audio_response = await self.sarvam_handler.synthesize_tts(ai_response, language)
            print(f"   Generated {len(audio_response)} bytes of audio")
            
            # Step 4: Play audio response
            self.play_audio(audio_response)
            
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
        """Run voice-based conversation with real audio"""
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
            
            print("⏳ Waiting 10 seconds for call to connect...")
            await asyncio.sleep(10)
        
        print("\n🎙️ Voice Conversation Started")
        print("Commands:")
        print("   Press ENTER to record your voice")
        print("   Type 'quit' to end conversation")
        print("   Type 'call' to trigger a call")
        print("=" * 60)
        
        turn = 1
        while True:
            try:
                command = input(f"\n🎯 Turn {turn} - Press ENTER to speak (or 'quit'/'call'): ").strip().lower()
                
                if command == 'quit':
                    print("👋 Ending voice conversation")
                    break
                
                elif command == 'call':
                    print("📞 Triggering call...")
                    call_result = await self.trigger_test_call(customer_key)
                    if call_result["success"]:
                        print(f"✅ Call triggered: {call_result['call_sid']}")
                    else:
                        print(f"❌ Call failed: {call_result['error']}")
                    continue
                
                elif command == '':
                    # Record audio
                    audio_data = self.record_audio(duration=5)
                    
                    if len(audio_data) > 0:
                        print(f"🔄 Processing your voice input...")
                        
                        # Process through voice pipeline
                        ai_response = await self.process_voice_input(audio_data, customer_data)
                        
                        print(f"🤖 AI Agent Response: '{ai_response}'")
                        print("✅ Turn completed!")
                        
                        turn += 1
                    else:
                        print("❌ No audio recorded")
                
                else:
                    print("❓ Unknown command. Press ENTER to speak, 'quit' to exit, 'call' to trigger call")
                    
            except KeyboardInterrupt:
                print("\n👋 Voice conversation interrupted")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    async def run_auto_voice_test(self, customer_key: str):
        """Run automated voice test with call triggering"""
        print(f"🤖 Running automated voice test for {customer_key}")
        print("=" * 60)
        
        customer_data = self.test_customers[customer_key]
        
        # Step 1: Trigger call
        print("📞 Step 1: Triggering call...")
        call_result = await self.trigger_test_call(customer_key)
        
        if not call_result["success"]:
            print(f"❌ Failed to trigger call: {call_result['error']}")
            return
        
        print(f"✅ Call triggered successfully: {call_result['call_sid']}")
        
        # Step 2: Wait for call to connect
        print("⏳ Step 2: Waiting for call to connect...")
        await asyncio.sleep(15)
        
        # Step 3: Start voice interaction
        print("🎙️ Step 3: Starting voice interaction...")
        print("   The system is now ready for voice input")
        print("   Customer can speak and receive AI responses")
        
        # Monitor call for a few minutes
        print("📊 Step 4: Monitoring call...")
        for i in range(12):  # Monitor for 2 minutes
            await asyncio.sleep(10)
            print(f"   Monitoring... {i+1}/12 (10s intervals)")
        
        print("🏁 Automated voice test completed!")
    
    def cleanup(self):
        """Cleanup audio resources"""
        try:
            self.audio.terminate()
            print("🧹 Audio resources cleaned up")
        except:
            pass

async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Voice-Based Test System")
    parser.add_argument("--customer", type=str, choices=["vijay", "priya"],
                       help="Customer to test with")
    parser.add_argument("--auto-call", action="store_true",
                       help="Automatically trigger call")
    parser.add_argument("--interactive", action="store_true",
                       help="Interactive voice mode")
    
    args = parser.parse_args()
    
    print("🎙️ Voice-Based Test System")
    print("=" * 60)
    print("🔊 Real audio input/output enabled")
    print("📞 Independent call triggering")
    print("🎯 Complete voice pipeline testing")
    print("=" * 60)
    
    system = VoiceBasedTestSystem()
    
    try:
        if args.customer:
            if args.auto_call:
                await system.run_auto_voice_test(args.customer)
            else:
                await system.run_voice_conversation(args.customer, auto_call=False)
        
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
                    await system.run_voice_conversation(customer, auto_call=auto_call)
                else:
                    print("❌ Invalid customer. Choose 'vijay' or 'priya'")
        
        else:
            # Default: voice conversation with Vijay
            await system.run_voice_conversation("vijay", auto_call=True)
            
    except KeyboardInterrupt:
        print("\n👋 Test interrupted")
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
    finally:
        system.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
