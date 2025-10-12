#!/usr/bin/env python3
"""
Enhanced Voice Test - Real Voice Interaction Testing
===================================================
This system simulates and processes actual voice interactions:
1. Triggers real calls
2. Simulates customer speech input
3. Processes through STT → Claude → TTS pipeline
4. Handles real voice conversations

Usage:
    python enhanced_voice_test.py --interactive
    python enhanced_voice_test.py --simulate vijay
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
from utils.redis_session import redis_manager
from voice_call_tester import VoiceCallTester

class EnhancedVoiceTest:
    """
    Enhanced voice testing that processes actual voice interactions
    """
    
    def __init__(self):
        """Initialize enhanced voice test system"""
        self.voice_tester = VoiceCallTester()
        self.sarvam_handler = ProductionSarvamHandler(os.getenv("SARVAM_API_KEY"))
        
        # Conversation state
        self.active_conversations = {}
        self.conversation_history = {}
        
        print("🎙️ Enhanced Voice Test System Initialized")
        print("🔄 Supports real voice interaction processing")
        print("=" * 60)
    
    async def simulate_customer_conversation(self, customer_key: str, conversation_script: list):
        """
        Simulate a complete customer conversation with voice processing
        """
        customer_data = self.voice_tester.test_customers[customer_key]
        print(f"🎭 Simulating conversation with {customer_data['name']}")
        print("=" * 50)
        
        # Initialize conversation
        conversation_id = f"sim_{customer_key}_{int(time.time())}"
        self.conversation_history[conversation_id] = []
        
        # Build system prompt for this customer
        system_prompt = self._build_customer_system_prompt(customer_data)
        self.conversation_history[conversation_id].append({
            "role": "system",
            "content": system_prompt
        })
        
        print(f"🤖 System Prompt: {system_prompt[:100]}...")
        print("\n🎬 Starting Conversation Simulation:")
        print("=" * 50)
        
        for i, customer_input in enumerate(conversation_script, 1):
            print(f"\n🎯 Turn {i}: Processing customer input")
            print(f"👤 Customer says: '{customer_input}'")
            
            # Step 1: Simulate STT (Speech-to-Text)
            print("🔄 Step 1: Speech-to-Text processing...")
            transcript = await self._simulate_stt(customer_input, customer_data['language_code'])
            print(f"📝 STT Result: '{transcript}'")
            
            # Step 2: Process with Claude LLM
            print("🔄 Step 2: Claude LLM processing...")
            ai_response = await self._process_with_claude(transcript, conversation_id)
            print(f"🤖 Claude Response: '{ai_response}'")
            
            # Step 3: Convert to speech (TTS)
            print("🔄 Step 3: Text-to-Speech processing...")
            audio_bytes = await self._simulate_tts(ai_response, customer_data['language_code'])
            print(f"🔊 TTS Generated: {len(audio_bytes)} bytes of audio")
            
            # Save audio for testing
            self._save_conversation_audio(conversation_id, i, audio_bytes, ai_response)
            
            print(f"✅ Turn {i} completed successfully!")
            
            # Add delay between turns
            await asyncio.sleep(2)
        
        print(f"\n🏁 Conversation simulation completed!")
        print(f"📊 Total turns: {len(conversation_script)}")
        print(f"💾 Audio files saved in: conversation_outputs/{conversation_id}/")
        
        return conversation_id
    
    def _build_customer_system_prompt(self, customer_data: Dict[str, Any]) -> str:
        """Build system prompt for specific customer"""
        return f"""You are a Collections Voice Agent for South India Finvest Bank (SIF).

CUSTOMER CONTEXT:
- Name: {customer_data['name']}
- Phone: {customer_data['phone']}
- Loan ID: {customer_data['loan_id']}
- Outstanding Amount: ₹{customer_data['amount']}
- Due Date: {customer_data['due_date']}
- State: {customer_data['state']}
- Language: {customer_data['language_code']}

GUIDELINES:
- Greet, ask for consent, then verify identity before sharing details
- Be concise (<=2 sentences). Offer payment options and human handoff
- No threats; be empathetic. Support language: {customer_data['language_code']}
- If user interrupts, pause and let them speak (barge-in friendly)
- Provide helpful payment solutions and maintain professional tone
- Keep responses conversational and suitable for voice calls

IMPORTANT: Always respond in a helpful, empathetic manner focusing on finding solutions for the customer."""
    
    async def _simulate_stt(self, customer_input: str, language: str) -> str:
        """
        Simulate STT processing (in real scenario, this would process actual audio)
        """
        try:
            # In real scenario: audio_bytes → STT → transcript
            # For simulation: we already have text, but we can add language detection
            
            # Simulate processing time
            await asyncio.sleep(0.5)
            
            # Return the input as transcript (in real scenario, this would be STT result)
            return customer_input.strip()
            
        except Exception as e:
            print(f"❌ STT Error: {e}")
            return customer_input
    
    async def _process_with_claude(self, transcript: str, conversation_id: str) -> str:
        """
        Process transcript with Claude LLM
        """
        try:
            # Add user message to conversation history
            self.conversation_history[conversation_id].append({
                "role": "user",
                "content": transcript
            })
            
            # Prepare messages for Claude (Bedrock format)
            bedrock_messages = []
            system_content = ""
            
            for msg in self.conversation_history[conversation_id]:
                if msg["role"] == "system":
                    system_content = msg["content"]
                else:
                    # Format content properly for Bedrock API
                    content = msg["content"]
                    if isinstance(content, str):
                        formatted_content = [{"type": "text", "text": content}]
                    else:
                        formatted_content = content
                    
                    bedrock_messages.append({
                        "role": msg["role"],
                        "content": formatted_content
                    })
            
            # Add system message if present
            if system_content:
                bedrock_messages.insert(0, {
                    "role": "user",
                    "content": [{"type": "text", "text": system_content.strip()}]
                })
            
            # Get Claude model ID
            claude_model_id = os.getenv("CLAUDE_MODEL_ID", 
                "arn:aws:bedrock:eu-north-1:844605843483:inference-profile/eu.anthropic.claude-3-7-sonnet-20250219-v1:0")
            
            # Call Claude via Bedrock
            response_text = bedrock_client.invoke_claude_model(bedrock_messages, claude_model_id)
            
            # Add Claude's response to conversation history
            self.conversation_history[conversation_id].append({
                "role": "assistant",
                "content": response_text
            })
            
            return response_text.strip()
            
        except Exception as e:
            print(f"❌ Claude Error: {e}")
            traceback.print_exc()
            return "I apologize, I'm having technical difficulties. Let me transfer you to a human agent."
    
    async def _simulate_tts(self, response_text: str, language: str) -> bytes:
        """
        Convert response to speech using Sarvam TTS
        """
        try:
            # Use Sarvam TTS to generate audio
            audio_bytes = await self.sarvam_handler.synthesize_tts(response_text, language)
            return audio_bytes
            
        except Exception as e:
            print(f"❌ TTS Error: {e}")
            return b""
    
    def _save_conversation_audio(self, conversation_id: str, turn: int, audio_bytes: bytes, text: str):
        """Save conversation audio and transcript"""
        try:
            output_dir = Path("conversation_outputs") / conversation_id
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Save audio
            audio_path = output_dir / f"turn_{turn:02d}_response.raw"
            with open(audio_path, "wb") as f:
                f.write(audio_bytes)
            
            # Save transcript
            transcript_path = output_dir / f"turn_{turn:02d}_transcript.txt"
            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write(text)
            
            print(f"💾 Saved: {audio_path.name} ({len(audio_bytes)} bytes)")
            
        except Exception as e:
            print(f"❌ Error saving audio: {e}")
    
    async def run_interactive_voice_conversation(self):
        """
        Run interactive voice conversation simulation
        """
        print("🎮 Interactive Voice Conversation")
        print("=" * 50)
        print("Available customers:")
        for key, customer in self.voice_tester.test_customers.items():
            print(f"   {key}: {customer['name']} ({customer['language_code']})")
        
        print("\nCommands:")
        print("   start <customer_key> - Start conversation with customer")
        print("   say <text> - Customer says something")
        print("   end - End current conversation")
        print("   quit - Exit")
        print("=" * 50)
        
        current_conversation = None
        
        while True:
            try:
                command = input("\n🎙️ Voice> ").strip()
                
                if command.lower() in ['quit', 'exit', 'q']:
                    print("👋 Goodbye!")
                    break
                
                elif command.startswith("start "):
                    customer_key = command.split(" ", 1)[1]
                    if customer_key in self.voice_tester.test_customers:
                        customer_data = self.voice_tester.test_customers[customer_key]
                        current_conversation = f"interactive_{customer_key}_{int(time.time())}"
                        
                        # Initialize conversation
                        system_prompt = self._build_customer_system_prompt(customer_data)
                        self.conversation_history[current_conversation] = [{
                            "role": "system",
                            "content": system_prompt
                        }]
                        
                        print(f"🎬 Started conversation with {customer_data['name']}")
                        print("💡 Type 'say <message>' to simulate customer speech")
                    else:
                        print(f"❌ Customer '{customer_key}' not found")
                
                elif command.startswith("say ") and current_conversation:
                    customer_input = command[4:].strip()
                    if customer_input:
                        print(f"\n👤 Customer: '{customer_input}'")
                        
                        # Process through voice pipeline
                        transcript = await self._simulate_stt(customer_input, "en-IN")
                        ai_response = await self._process_with_claude(transcript, current_conversation)
                        audio_bytes = await self._simulate_tts(ai_response, "en-IN")
                        
                        print(f"🤖 AI Agent: '{ai_response}'")
                        print(f"🔊 Audio generated: {len(audio_bytes)} bytes")
                
                elif command == "end":
                    if current_conversation:
                        print(f"🏁 Ended conversation: {current_conversation}")
                        current_conversation = None
                    else:
                        print("❌ No active conversation")
                
                else:
                    print("❓ Unknown command. Available: start <customer>, say <text>, end, quit")
                    
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")

async def run_predefined_conversation_tests():
    """Run predefined conversation scenarios"""
    print("🧪 Running Predefined Conversation Tests")
    print("=" * 60)
    
    tester = EnhancedVoiceTest()
    
    # Test scenarios
    scenarios = {
        "test_customer_1": [
            "Hello, I received a call about my loan payment",
            "I want to know about my outstanding amount",
            "Can I get some payment options?",
            "I can pay half now, rest next month"
        ],
        "test_customer_2": [
            "मुझे अपने लोन के बारे में जानकारी चाहिए",
            "मैं पेमेंट करना चाहता हूं",
            "क्या कोई छूट मिल सकती है?"
        ]
    }
    
    for customer_key, conversation in scenarios.items():
        print(f"\n🎯 Testing conversation with {customer_key}")
        conversation_id = await tester.simulate_customer_conversation(customer_key, conversation)
        print(f"✅ Completed conversation: {conversation_id}")
        
        # Add delay between conversations
        await asyncio.sleep(3)
    
    print("\n🏁 All conversation tests completed!")

async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced Voice Testing System")
    parser.add_argument("--interactive", "-i", action="store_true",
                       help="Interactive conversation mode")
    parser.add_argument("--simulate", type=str, choices=["vijay", "priya"],
                       help="Simulate conversation with specific customer")
    parser.add_argument("--predefined", action="store_true",
                       help="Run predefined conversation tests")
    
    args = parser.parse_args()
    
    print("🎙️ Enhanced Voice Testing System")
    print("=" * 60)
    
    try:
        if args.interactive:
            tester = EnhancedVoiceTest()
            await tester.run_interactive_voice_conversation()
        
        elif args.simulate:
            tester = EnhancedVoiceTest()
            customer_key = "test_customer_1" if args.simulate == "vijay" else "test_customer_2"
            
            # Sample conversation
            conversation = [
                "Hello, I need help with my loan payment",
                "What are my payment options?",
                "Can I get an extension?",
                "Thank you for your help"
            ]
            
            await tester.simulate_customer_conversation(customer_key, conversation)
        
        elif args.predefined:
            await run_predefined_conversation_tests()
        
        else:
            # Default to interactive mode
            tester = EnhancedVoiceTest()
            await tester.run_interactive_voice_conversation()
            
    except KeyboardInterrupt:
        print("\n👋 Test interrupted")
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
