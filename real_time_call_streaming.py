#!/usr/bin/env python3
"""
Real-Time Call Streaming System
==============================
This system integrates with live phone calls to provide real-time voice processing:
1. Triggers actual phone calls
2. Connects to live call audio streams
3. Processes real-time audio: STT → Claude → TTS
4. Streams responses back to the phone call
5. Works with your existing Exotel + WebSocket infrastructure

Usage:
    python real_time_call_streaming.py --customer vijay
    python real_time_call_streaming.py --monitor-call <call_sid>
"""

import os
import sys
import asyncio
import json
import time
import websockets
import base64
from pathlib import Path
from typing import Dict, Any, Optional, Callable
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
from utils.redis_session import redis_manager

class RealTimeCallStreaming:
    """
    Real-time call streaming with live voice processing
    """
    
    def __init__(self):
        """Initialize real-time call streaming system"""
        self.sarvam_handler = ProductionSarvamHandler(os.getenv("SARVAM_API_KEY"))
        self.call_service = CallManagementService()
        
        # WebSocket connections
        self.voicebot_ws = None
        self.dashboard_ws = None
        
        # Call state
        self.active_call_sid = None
        self.conversation_history = {}
        self.is_streaming = False
        
        # Audio processing
        self.audio_buffer = []
        self.processing_audio = False
        
        # Test customers
        self.test_customers = self._get_test_customers()
        
        # Base URL for WebSocket connections
        self.base_url = os.getenv("BASE_URL", "https://9a81252242ca.ngrok-free.app")
        
        print("🎙️ Real-Time Call Streaming System Initialized")
        print("📞 Live phone call integration enabled")
        print("🔄 Real-time audio processing: STT → Claude → TTS")
        print("🌐 WebSocket streaming to live calls")
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
    
    async def trigger_live_call(self, customer_key: str) -> Dict[str, Any]:
        """Trigger a live call and prepare for streaming"""
        if customer_key not in self.test_customers:
            return {"success": False, "error": f"Customer {customer_key} not found"}
        
        customer_data = self.test_customers[customer_key]
        print(f"📞 Triggering live call to: {customer_data['name']} ({customer_data['phone']})")
        
        try:
            # Create customer in database if not exists
            customer_id = await self._create_test_customer_in_db(customer_data)
            if not customer_id:
                return {"success": False, "error": "Failed to create customer in database"}
            
            # Trigger call using existing call management service
            result = await self.call_service.trigger_single_call(customer_id)
            
            if result.get("success"):
                self.active_call_sid = result.get("call_sid")
                print(f"✅ Live call triggered successfully!")
                print(f"   Call SID: {self.active_call_sid}")
                print(f"   Customer: {customer_data['name']}")
                
                # Initialize conversation context
                self._initialize_conversation_context(customer_data)
                
                return {
                    "success": True,
                    "call_sid": self.active_call_sid,
                    "customer_data": customer_data,
                    "customer_id": customer_id
                }
            else:
                return {"success": False, "error": result.get("error", "Unknown error")}
                
        except Exception as e:
            print(f"❌ Error triggering live call: {e}")
            return {"success": False, "error": str(e)}
    
    def _initialize_conversation_context(self, customer_data: Dict[str, Any]):
        """Initialize conversation context for the call"""
        conversation_id = self.active_call_sid
        system_prompt = self._build_system_prompt(customer_data)
        
        self.conversation_history[conversation_id] = [{
            "role": "system",
            "content": system_prompt
        }]
        
        print(f"🤖 Conversation context initialized for {customer_data['name']}")
    
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
    
    async def connect_to_live_call(self, call_sid: str):
        """Connect to live call WebSocket for real-time streaming"""
        try:
            print(f"🔌 Connecting to live call WebSocket...")
            
            # Connect to voicebot WebSocket
            voicebot_url = f"wss://{self.base_url.replace('https://', '').replace('http://', '')}/ws/voicebot/{call_sid}?call_sid={call_sid}"
            print(f"🎙️ Voicebot WebSocket: {voicebot_url}")
            
            # Connect to dashboard WebSocket for monitoring
            dashboard_url = f"wss://{self.base_url.replace('https://', '').replace('http://', '')}/ws/dashboard/monitor"
            print(f"📊 Dashboard WebSocket: {dashboard_url}")
            
            # Connect to both WebSockets
            self.voicebot_ws = await websockets.connect(voicebot_url)
            self.dashboard_ws = await websockets.connect(dashboard_url)
            
            print("✅ Connected to live call WebSockets")
            self.is_streaming = True
            
            # Start listening for real-time audio
            await self._start_real_time_processing()
            
        except Exception as e:
            print(f"❌ Error connecting to live call: {e}")
            traceback.print_exc()
    
    async def _start_real_time_processing(self):
        """Start real-time audio processing from live call"""
        print("🎧 Starting real-time audio processing...")
        print("🔄 Listening for live call audio...")
        
        try:
            # Create tasks for both WebSocket listeners
            voicebot_task = asyncio.create_task(self._handle_voicebot_messages())
            dashboard_task = asyncio.create_task(self._handle_dashboard_messages())
            
            # Wait for either task to complete (or error)
            await asyncio.gather(voicebot_task, dashboard_task, return_exceptions=True)
            
        except Exception as e:
            print(f"❌ Error in real-time processing: {e}")
            traceback.print_exc()
        finally:
            await self._cleanup_connections()
    
    async def _handle_voicebot_messages(self):
        """Handle real-time messages from voicebot WebSocket"""
        try:
            async for message in self.voicebot_ws:
                try:
                    data = json.loads(message)
                    message_type = data.get("type")
                    
                    if message_type == "media":
                        # Real-time audio data from phone call
                        await self._process_live_audio(data)
                    
                    elif message_type == "start":
                        print("🎬 Live call audio stream started")
                    
                    elif message_type == "stop":
                        print("🛑 Live call audio stream stopped")
                        break
                    
                    else:
                        print(f"📨 Voicebot message: {message_type}")
                        
                except json.JSONDecodeError:
                    print(f"❌ Invalid JSON from voicebot: {message}")
                except Exception as e:
                    print(f"❌ Error processing voicebot message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            print("🔌 Voicebot WebSocket connection closed")
        except Exception as e:
            print(f"❌ Voicebot WebSocket error: {e}")
    
    async def _handle_dashboard_messages(self):
        """Handle messages from dashboard WebSocket for monitoring"""
        try:
            async for message in self.dashboard_ws:
                try:
                    data = json.loads(message)
                    event_type = data.get("event")
                    
                    if event_type == "call_status_update":
                        call_sid = data.get("call_sid")
                        status = data.get("status")
                        print(f"📊 Call Status Update: {call_sid} → {status}")
                        
                        if status in ["completed", "failed", "no-answer"]:
                            print(f"📞 Call ended with status: {status}")
                            break
                    
                    else:
                        print(f"📊 Dashboard event: {event_type}")
                        
                except json.JSONDecodeError:
                    print(f"❌ Invalid JSON from dashboard: {message}")
                except Exception as e:
                    print(f"❌ Error processing dashboard message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            print("🔌 Dashboard WebSocket connection closed")
        except Exception as e:
            print(f"❌ Dashboard WebSocket error: {e}")
    
    async def _process_live_audio(self, media_data: Dict[str, Any]):
        """Process real-time audio from live phone call"""
        try:
            if self.processing_audio:
                return  # Skip if already processing
            
            self.processing_audio = True
            
            # Extract audio payload
            payload = media_data.get("media", {}).get("payload", "")
            if not payload:
                return
            
            # Decode audio data
            audio_bytes = base64.b64decode(payload)
            print(f"🎤 Received live audio: {len(audio_bytes)} bytes")
            
            # Add to buffer for processing
            self.audio_buffer.append(audio_bytes)
            
            # Process when we have enough audio (e.g., 1 second worth)
            if len(self.audio_buffer) >= 10:  # Adjust based on chunk size
                await self._process_audio_buffer()
                
        except Exception as e:
            print(f"❌ Error processing live audio: {e}")
        finally:
            self.processing_audio = False
    
    async def _process_audio_buffer(self):
        """Process accumulated audio buffer through STT → Claude → TTS"""
        try:
            # Combine audio chunks
            combined_audio = b''.join(self.audio_buffer)
            self.audio_buffer.clear()
            
            print(f"🔄 Processing {len(combined_audio)} bytes of live audio...")
            
            # Step 1: Speech-to-Text
            print("📝 Step 1: Converting live speech to text...")
            transcript_result = await self.sarvam_handler.transcribe_from_payload(combined_audio)
            
            if isinstance(transcript_result, tuple):
                transcript, detected_language = transcript_result
                language = detected_language or "en-IN"
            else:
                transcript = transcript_result
                language = "en-IN"
            
            print(f"   Live STT Result: '{transcript}'")
            
            if not transcript or transcript.strip() == "":
                print("🔇 No speech detected in audio buffer")
                return
            
            # Step 2: Process with Claude
            print("🤖 Step 2: Processing with Claude LLM...")
            ai_response = await self._process_with_claude(transcript, language)
            print(f"   Claude Response: '{ai_response}'")
            
            # Step 3: Convert to speech
            print("🔊 Step 3: Converting response to speech...")
            response_audio = await self.sarvam_handler.synthesize_tts(ai_response, language)
            
            # Step 4: Stream back to live call
            print("📡 Step 4: Streaming response to live call...")
            await self._stream_audio_to_call(response_audio)
            
            print("✅ Live audio processing completed!")
            
        except Exception as e:
            print(f"❌ Error processing audio buffer: {e}")
            traceback.print_exc()
    
    async def _process_with_claude(self, transcript: str, language: str) -> str:
        """Process transcript with Claude LLM"""
        try:
            conversation_id = self.active_call_sid or "live_call"
            
            # Add user message to conversation
            if conversation_id in self.conversation_history:
                self.conversation_history[conversation_id].append({
                    "role": "user",
                    "content": transcript
                })
            
            # Prepare messages for Claude
            bedrock_messages = []
            system_content = ""
            
            for msg in self.conversation_history.get(conversation_id, []):
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
            if conversation_id in self.conversation_history:
                self.conversation_history[conversation_id].append({
                    "role": "assistant",
                    "content": response_text
                })
            
            return response_text.strip()
            
        except Exception as e:
            print(f"❌ Claude Error: {e}")
            return "I apologize, I'm having technical difficulties."
    
    async def _stream_audio_to_call(self, audio_bytes: bytes):
        """Stream audio response back to live phone call"""
        try:
            if not self.voicebot_ws:
                print("❌ No voicebot WebSocket connection")
                return
            
            # Encode audio for streaming
            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            # Create media message for streaming
            media_message = {
                "type": "media",
                "media": {
                    "payload": audio_b64
                }
            }
            
            # Send to live call
            await self.voicebot_ws.send(json.dumps(media_message))
            print(f"📡 Streamed {len(audio_bytes)} bytes to live call")
            
        except Exception as e:
            print(f"❌ Error streaming audio to call: {e}")
    
    def _build_system_prompt(self, customer_data: Dict[str, Any]) -> str:
        """Build system prompt for customer"""
        return f"""You are a Collections Voice Agent for South India Finvest Bank (SIF).

CUSTOMER CONTEXT:
- Name: {customer_data['name']}
- Phone: {customer_data['phone']}
- Loan ID: {customer_data['loan_id']}
- Outstanding Amount: ₹{customer_data['amount']}
- Due Date: {customer_data['due_date']}
- State: {customer_data['state']}

GUIDELINES:
- Greet, ask for consent, then verify identity before sharing details
- Be concise (<=2 sentences). Offer payment options and human handoff
- No threats; be empathetic
- If user interrupts, pause and let them speak (barge-in friendly)
- Provide helpful payment solutions and maintain professional tone
- Keep responses conversational and suitable for voice calls

IMPORTANT: Always respond in a helpful, empathetic manner focusing on finding solutions for the customer."""
    
    async def _cleanup_connections(self):
        """Cleanup WebSocket connections"""
        try:
            if self.voicebot_ws:
                await self.voicebot_ws.close()
            if self.dashboard_ws:
                await self.dashboard_ws.close()
            print("🧹 WebSocket connections cleaned up")
        except:
            pass
    
    async def run_live_call_streaming(self, customer_key: str):
        """Run complete live call streaming workflow"""
        print(f"🎬 Starting live call streaming for {customer_key}")
        print("=" * 60)
        
        try:
            # Step 1: Trigger live call
            print("📞 Step 1: Triggering live call...")
            call_result = await self.trigger_live_call(customer_key)
            
            if not call_result["success"]:
                print(f"❌ Failed to trigger call: {call_result['error']}")
                return
            
            call_sid = call_result["call_sid"]
            print(f"✅ Live call triggered: {call_sid}")
            
            # Step 2: Wait for call to connect
            print("⏳ Step 2: Waiting for call to connect...")
            await asyncio.sleep(10)  # Give time for call to connect
            
            # Step 3: Connect to live call stream
            print("🔌 Step 3: Connecting to live call stream...")
            await self.connect_to_live_call(call_sid)
            
        except KeyboardInterrupt:
            print("\n👋 Live call streaming interrupted")
        except Exception as e:
            print(f"❌ Error in live call streaming: {e}")
            traceback.print_exc()
        finally:
            await self._cleanup_connections()

async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Real-Time Call Streaming System")
    parser.add_argument("--customer", type=str, choices=["vijay", "priya"],
                       default="vijay", help="Customer to call")
    parser.add_argument("--monitor-call", type=str,
                       help="Monitor existing call by SID")
    
    args = parser.parse_args()
    
    print("🎙️ Real-Time Call Streaming System")
    print("=" * 60)
    print("📞 Live phone call integration")
    print("🔄 Real-time audio processing")
    print("📡 WebSocket streaming to calls")
    print("🎯 STT → Claude → TTS pipeline")
    print("=" * 60)
    
    system = RealTimeCallStreaming()
    
    try:
        if args.monitor_call:
            # Monitor existing call
            print(f"👁️ Monitoring existing call: {args.monitor_call}")
            await system.connect_to_live_call(args.monitor_call)
        else:
            # Start new live call streaming
            await system.run_live_call_streaming(args.customer)
            
    except KeyboardInterrupt:
        print("\n👋 System interrupted")
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
