#!/usr/bin/env python3
"""
Speech-to-Speech Pipeline Test
=============================
Tests the complete pipeline: Speech → Sarvam STT → Claude LLM → Sarvam TTS → Audio Output

This test demonstrates:
1. Audio input processing (simulated or from file)
2. Sarvam STT (Speech-to-Text)
3. Claude LLM processing with collections prompt
4. Sarvam TTS (Text-to-Speech)
5. Audio output generation

Usage:
    python test_speech_to_speech_pipeline.py
"""

import os
import sys
import asyncio
import json
import base64
import time
from pathlib import Path
from typing import Dict, Any, Optional
import traceback
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import your existing modules
from utils.production_asr import ProductionSarvamHandler
from utils import bedrock_client
from utils.logger import logger

class SpeechToSpeechTester:
    """
    Complete Speech-to-Speech Pipeline Tester
    """
    
    def __init__(self):
        """Initialize the tester with required components"""
        self.sarvam_handler = ProductionSarvamHandler(os.getenv("SARVAM_API_KEY"))
        self.customer_data = self._get_test_customer_data()
        self.language = "en-IN"  # Default language
        self.conversation_history = []
        
        # Initialize conversation with system prompt
        self.system_prompt = self._build_collections_system_prompt()
        self.conversation_history.append({
            "role": "system",
            "content": self.system_prompt
        })
        
        print("🚀 Speech-to-Speech Pipeline Tester Initialized")
        print(f"📋 Customer: {self.customer_data['name']}")
        print(f"🌐 Language: {self.language}")
        print("=" * 60)
    
    def _get_test_customer_data(self) -> Dict[str, Any]:
        """Get test customer data"""
        return {
            "name": "Vijay",
            "phone": "+919384531725",
            "loan_id": "LOAN123456",
            "amount": "15000",
            "due_date": "2024-01-15",
            "state": "Karnataka",
            "language_code": "en-IN"
        }
    
    def _build_collections_system_prompt(self) -> str:
        """Build the collections system prompt based on agent_config.py"""
        customer_name = self.customer_data.get('name', 'Customer')
        loan_id = self.customer_data.get('loan_id', 'N/A')
        amount = self.customer_data.get('amount', 0)
        due_date = self.customer_data.get('due_date', 'N/A')
        
        return f"""You are a Collections Voice Agent for South India Finvest Bank (SIF).

CUSTOMER CONTEXT:
- Name: {customer_name}
- Loan ID: {loan_id}
- Outstanding Amount: ₹{amount}
- Due Date: {due_date}
- Language: {self.language}

GUIDELINES:
- Greet, ask for consent, then verify identity before sharing details.
- Be concise (<=2 sentences). Offer payment options and human handoff.
- No threats; be empathetic. Support language: {self.language}.
- If user interrupts, pause and let them speak (barge-in friendly).
- Provide helpful payment solutions and maintain professional tone.
- Keep responses conversational and suitable for voice calls.

IMPORTANT: Always respond in a helpful, empathetic manner focusing on finding solutions for the customer."""
    
    async def simulate_audio_input(self, text_input: str) -> bytes:
        """
        Simulate audio input by converting text to audio first
        (In real scenario, this would be actual customer speech)
        """
        print(f"🎤 Simulating customer speech: '{text_input}'")
        
        try:
            # Convert text to audio to simulate customer speech
            audio_bytes = await self.sarvam_handler.synthesize_tts(text_input, self.language)
            print(f"✅ Generated {len(audio_bytes)} bytes of simulated customer audio")
            return audio_bytes
        except Exception as e:
            print(f"❌ Error generating simulated audio: {e}")
            return b""
    
    async def process_speech_to_text(self, audio_bytes: bytes) -> str:
        """
        Step 1: Convert speech to text using Sarvam STT
        """
        print("🔄 Step 1: Converting speech to text...")
        
        try:
            # Use Sarvam STT to transcribe audio
            transcript_result = await self.sarvam_handler.transcribe_from_payload(audio_bytes)
            
            if isinstance(transcript_result, tuple):
                transcript, detected_language = transcript_result
                if detected_language and detected_language != self.language:
                    print(f"🌐 Language detected: {detected_language} (switching from {self.language})")
                    self.language = detected_language
            else:
                transcript = transcript_result
            
            print(f"📝 Transcript: '{transcript}'")
            return transcript.strip() if transcript else ""
            
        except Exception as e:
            print(f"❌ STT Error: {e}")
            traceback.print_exc()
            return ""
    
    async def process_with_claude(self, transcript: str) -> str:
        """
        Step 2: Process transcript with Claude LLM
        """
        print("🤖 Step 2: Processing with Claude LLM...")
        
        if not transcript:
            return "I'm sorry, I didn't catch that. Could you please repeat?"
        
        try:
            # Add user message to conversation history
            self.conversation_history.append({
                "role": "user",
                "content": transcript
            })
            
            # Prepare messages for Claude (Bedrock format)
            bedrock_messages = []
            system_content = ""
            
            for msg in self.conversation_history:
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
            
            # Add system message if present (prepend as user message with system context)
            if system_content:
                bedrock_messages.insert(0, {
                    "role": "user",
                    "content": [{"type": "text", "text": system_content.strip()}]
                })
            
            # Get Claude model ID
            claude_model_id = os.getenv("CLAUDE_MODEL_ID", 
                "arn:aws:bedrock:eu-north-1:844605843483:inference-profile/eu.anthropic.claude-3-7-sonnet-20250219-v1:0")
            
            print(f"🔮 Invoking Claude model: {claude_model_id}")
            
            # Call Claude via Bedrock
            response_text = bedrock_client.invoke_claude_model(bedrock_messages, claude_model_id)
            
            # Add Claude's response to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": response_text
            })
            
            print(f"💬 Claude Response: '{response_text}'")
            return response_text.strip()
            
        except Exception as e:
            print(f"❌ Claude Error: {e}")
            traceback.print_exc()
            return "I apologize, I'm having technical difficulties. Let me transfer you to a human agent."
    
    async def process_text_to_speech(self, response_text: str) -> bytes:
        """
        Step 3: Convert Claude's response to speech using Sarvam TTS
        """
        print("🔊 Step 3: Converting response to speech...")
        
        try:
            # Use Sarvam TTS to generate audio
            audio_bytes = await self.sarvam_handler.synthesize_tts(response_text, self.language)
            print(f"✅ Generated {len(audio_bytes)} bytes of response audio")
            return audio_bytes
            
        except Exception as e:
            print(f"❌ TTS Error: {e}")
            traceback.print_exc()
            return b""
    
    def save_audio_output(self, audio_bytes: bytes, filename: str):
        """
        Save audio output to file for testing
        """
        try:
            output_dir = Path("test_outputs")
            output_dir.mkdir(exist_ok=True)
            
            output_path = output_dir / filename
            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            
            print(f"💾 Audio saved to: {output_path}")
            
        except Exception as e:
            print(f"❌ Error saving audio: {e}")
    
    async def run_complete_pipeline(self, customer_input: str) -> Dict[str, Any]:
        """
        Run the complete Speech-to-Speech pipeline
        """
        print(f"\n🎯 Running Complete Pipeline for: '{customer_input}'")
        print("=" * 60)
        
        pipeline_result = {
            "input": customer_input,
            "transcript": "",
            "claude_response": "",
            "audio_generated": False,
            "success": False,
            "error": None
        }
        
        try:
            # Step 1: Simulate audio input (in real scenario, this comes from customer)
            audio_input = await self.simulate_audio_input(customer_input)
            if not audio_input:
                pipeline_result["error"] = "Failed to generate audio input"
                return pipeline_result
            
            # Step 2: Speech to Text (Sarvam STT)
            transcript = await self.process_speech_to_text(audio_input)
            pipeline_result["transcript"] = transcript
            
            if not transcript:
                pipeline_result["error"] = "Failed to transcribe audio"
                return pipeline_result
            
            # Step 3: Process with Claude LLM
            claude_response = await self.process_with_claude(transcript)
            pipeline_result["claude_response"] = claude_response
            
            if not claude_response:
                pipeline_result["error"] = "Failed to get Claude response"
                return pipeline_result
            
            # Step 4: Text to Speech (Sarvam TTS)
            response_audio = await self.process_text_to_speech(claude_response)
            
            if response_audio:
                pipeline_result["audio_generated"] = True
                # Save audio for testing
                timestamp = int(time.time())
                filename = f"response_{timestamp}.raw"
                self.save_audio_output(response_audio, filename)
            
            pipeline_result["success"] = True
            print("✅ Pipeline completed successfully!")
            
        except Exception as e:
            pipeline_result["error"] = str(e)
            print(f"❌ Pipeline failed: {e}")
            traceback.print_exc()
        
        return pipeline_result
    
    async def run_interactive_test(self):
        """
        Run interactive test session
        """
        print("\n🎮 Interactive Speech-to-Speech Test Session")
        print("Type 'quit' to exit")
        print("=" * 60)
        
        while True:
            try:
                user_input = input("\n👤 Customer says: ").strip()
                
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("👋 Goodbye!")
                    break
                
                if not user_input:
                    continue
                
                # Run the pipeline
                result = await self.run_complete_pipeline(user_input)
                
                # Display results
                print(f"\n📊 Pipeline Results:")
                print(f"   Input: {result['input']}")
                print(f"   Transcript: {result['transcript']}")
                print(f"   Claude Response: {result['claude_response']}")
                print(f"   Audio Generated: {result['audio_generated']}")
                print(f"   Success: {result['success']}")
                
                if result['error']:
                    print(f"   Error: {result['error']}")
                
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error in interactive test: {e}")

async def run_predefined_tests():
    """
    Run predefined test scenarios
    """
    print("🧪 Running Predefined Test Scenarios")
    print("=" * 60)
    
    tester = SpeechToSpeechTester()
    
    test_scenarios = [
        "Hello, I received a call about my loan payment",
        "I want to know about my outstanding amount",
        "Can I get an extension on my payment?",
        "I'm facing financial difficulties, can you help?",
        "What are my payment options?",
        "I want to speak to a manager",
        "मुझे अपने लोन के बारे में जानकारी चाहिए",  # Hindi
        "I can pay half amount now, rest next month"
    ]
    
    results = []
    
    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n🧪 Test {i}/{len(test_scenarios)}")
        result = await tester.run_complete_pipeline(scenario)
        results.append(result)
        
        # Add delay between tests
        await asyncio.sleep(1)
    
    # Summary
    print(f"\n📈 Test Summary:")
    print(f"Total Tests: {len(results)}")
    print(f"Successful: {sum(1 for r in results if r['success'])}")
    print(f"Failed: {sum(1 for r in results if not r['success'])}")
    
    return results

async def main():
    """
    Main function to run tests
    """
    print("🎙️ Speech-to-Speech Pipeline Tester")
    print("=" * 60)
    
    # Check environment variables
    required_env_vars = ["SARVAM_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"❌ Missing environment variables: {missing_vars}")
        print("Please set these variables before running the test.")
        return
    
    print("✅ Environment variables configured")
    
    # Choose test mode
    print("\nSelect test mode:")
    print("1. Predefined test scenarios")
    print("2. Interactive test session")
    
    try:
        choice = input("Enter choice (1 or 2): ").strip()
        
        if choice == "1":
            await run_predefined_tests()
        elif choice == "2":
            tester = SpeechToSpeechTester()
            await tester.run_interactive_test()
        else:
            print("Invalid choice. Running predefined tests...")
            await run_predefined_tests()
            
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    # Run the test
    asyncio.run(main())
