#!/usr/bin/env python3
"""
Enhanced Main Integration
========================
This script provides enhanced voice processing that integrates with your existing main.py
Instead of creating a separate system, it enhances the current WebSocket handlers.

Usage:
1. Keep main.py running as usual
2. This provides enhanced voice processing functions
3. Your existing call flow will use the enhanced processing
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

class EnhancedVoiceProcessor:
    """
    Enhanced voice processor that integrates with existing main.py
    """
    
    def __init__(self):
        """Initialize enhanced voice processor"""
        self.sarvam_handler = ProductionSarvamHandler(os.getenv("SARVAM_API_KEY"))
        self.conversation_history = {}
        
        print("🎙️ Enhanced Voice Processor Initialized")
        print("🔄 Ready to enhance existing main.py voice processing")
        print("=" * 60)
    
    async def process_customer_audio(self, audio_bytes: bytes, customer_info: Dict[str, Any], 
                                   conversation_stage: str = "CONVERSATION") -> Dict[str, Any]:
        """
        Enhanced audio processing that can be called from main.py
        
        Args:
            audio_bytes: Raw audio data from customer
            customer_info: Customer information dict
            conversation_stage: Current stage of conversation
            
        Returns:
            Dict with processed response and audio
        """
        try:
            print(f"🎤 Processing customer audio: {len(audio_bytes)} bytes")
            print(f"👤 Customer: {customer_info.get('name', 'Unknown')}")
            print(f"🎯 Stage: {conversation_stage}")
            
            # Step 1: Speech-to-Text
            print("📝 Step 1: Converting speech to text...")
            transcript_result = await self.sarvam_handler.transcribe_from_payload(audio_bytes)
            
            if isinstance(transcript_result, tuple):
                transcript, detected_language = transcript_result
                language = detected_language or customer_info.get('lang', 'en-IN')
            else:
                transcript = transcript_result
                language = customer_info.get('lang', 'en-IN')
            
            print(f"   STT Result: '{transcript}'")
            print(f"   Language: {language}")
            
            if not transcript or transcript.strip() == "":
                return {
                    "success": False,
                    "error": "No speech detected",
                    "transcript": "",
                    "response_text": "I'm sorry, I didn't catch that. Could you please repeat?",
                    "response_audio": None
                }
            
            # Step 2: Process with Claude based on conversation stage
            print("🤖 Step 2: Processing with Claude LLM...")
            ai_response = await self._process_with_claude_enhanced(
                transcript, customer_info, language, conversation_stage
            )
            print(f"   Claude Response: '{ai_response}'")
            
            # Step 3: Convert to speech
            print("🔊 Step 3: Converting response to speech...")
            response_audio = await self.sarvam_handler.synthesize_tts(ai_response, language)
            print(f"   Generated {len(response_audio)} bytes of audio")
            
            return {
                "success": True,
                "transcript": transcript,
                "detected_language": language,
                "response_text": ai_response,
                "response_audio": response_audio,
                "conversation_stage": conversation_stage
            }
            
        except Exception as e:
            print(f"❌ Error in enhanced audio processing: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "transcript": "",
                "response_text": "I apologize, I'm having technical difficulties.",
                "response_audio": None
            }
    
    async def _process_with_claude_enhanced(self, transcript: str, customer_info: Dict[str, Any], 
                                          language: str, conversation_stage: str) -> str:
        """Enhanced Claude processing with conversation stage awareness"""
        try:
            # Create conversation ID
            conversation_id = customer_info.get('phone', 'unknown')
            
            # Initialize conversation if not exists
            if conversation_id not in self.conversation_history:
                system_prompt = self._build_enhanced_system_prompt(customer_info, language, conversation_stage)
                self.conversation_history[conversation_id] = [{
                    "role": "system",
                    "content": system_prompt
                }]
            
            # Add user message
            self.conversation_history[conversation_id].append({
                "role": "user",
                "content": f"[Stage: {conversation_stage}] {transcript}"
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
            print(f"❌ Enhanced Claude Error: {e}")
            return "I apologize, I'm having technical difficulties. Let me transfer you to a human agent."
    
    def _build_enhanced_system_prompt(self, customer_info: Dict[str, Any], 
                                    language: str, conversation_stage: str) -> str:
        """Build enhanced system prompt based on conversation stage"""
        
        base_prompt = f"""You are an Enhanced Collections Voice Agent for South India Finvest Bank (SIF).

CUSTOMER CONTEXT:
- Name: {customer_info.get('name', 'Customer')}
- Phone: {customer_info.get('phone', '')}
- Loan ID: {customer_info.get('loan_id', '')}
- Outstanding Amount: ₹{customer_info.get('amount', '')}
- Due Date: {customer_info.get('due_date', '')}
- State: {customer_info.get('state', '')}
- Language: {language}

CURRENT CONVERSATION STAGE: {conversation_stage}

ENHANCED GUIDELINES:
- Use Anushka's professional female voice tone
- Be empathetic and solution-focused
- Provide clear, actionable payment options
- Handle interruptions gracefully (barge-in friendly)
- Keep responses concise (1-2 sentences max)
- Always maintain professional banking standards
"""
        
        # Stage-specific instructions
        if conversation_stage == "INITIAL_GREETING" or conversation_stage == "PLAYING_PERSONALIZED_GREETING":
            base_prompt += """
STAGE INSTRUCTIONS:
- Greet warmly and introduce yourself as SIF Bank representative
"""
        elif conversation_stage == "WAITING_FOR_LANG_DETECT":
            base_prompt += """
STAGE INSTRUCTIONS:
- Listen for language preference
- Adapt to customer's preferred language
- Continue with personalized greeting
- Provide personalized greeting with loan details
- Explain purpose of call clearly
- Ask how you can assist with payment
- Keep it short (5-10 sentences max)
"""

        elif conversation_stage == "ASKING_AGENT_CONNECT":
            base_prompt += """
STAGE INSTRUCTIONS:
- Offer to connect to human agent if needed
- Provide final payment options before transfer
- Confirm customer's preference
"""
        else:
            base_prompt += """
STAGE INSTRUCTIONS:
- Continue natural conversation flow
- Focus on payment solutions
- Be ready to transfer to agent if requested
"""
        
        base_prompt += """

IMPORTANT: Always respond in a helpful, empathetic manner. Use the customer's name when appropriate. Keep responses suitable for voice calls with natural pauses."""
        
        return base_prompt
    
    def get_enhanced_greeting(self, customer_info: Dict[str, Any], language: str) -> str:
        """Generate enhanced personalized greeting"""
        name = customer_info.get('name', 'Customer')
        loan_id = customer_info.get('loan_id', '')
        amount = customer_info.get('amount', '')
        
        if language.startswith('hi'):
            return f"नमस्ते {name} जी, मैं साउथ इंडिया फिनवेस्ट बैंक से अनुष्का बोल रही हूं। आपके लोन {loan_id} के बारे में बात करने के लिए कॉल किया है। क्या मैं आगे बढ़ सकती हूं?"
        else:
            return f"Hello {name}, this is Anushka from South India Finvest Bank. I'm calling regarding your loan {loan_id} with an outstanding amount of ₹{amount}. May I have your consent to discuss your account details?"

# Global enhanced processor instance
enhanced_processor = EnhancedVoiceProcessor()

async def enhanced_audio_processing(audio_bytes: bytes, customer_info: Dict[str, Any], 
                                  conversation_stage: str = "CONVERSATION") -> Dict[str, Any]:
    """
    Main function that can be called from main.py to process audio
    
    Usage in main.py:
    from enhanced_main_integration import enhanced_audio_processing
    
    result = await enhanced_audio_processing(audio_bytes, customer_info, conversation_stage)
    if result["success"]:
        response_audio = result["response_audio"]
        response_text = result["response_text"]
    """
    return await enhanced_processor.process_customer_audio(audio_bytes, customer_info, conversation_stage)

def get_enhanced_greeting(customer_info: Dict[str, Any], language: str = "en-IN") -> str:
    """
    Get enhanced greeting that can be used in main.py
    
    Usage in main.py:
    from enhanced_main_integration import get_enhanced_greeting
    
    greeting = get_enhanced_greeting(customer_info, detected_language)
    """
    return enhanced_processor.get_enhanced_greeting(customer_info, language)

if __name__ == "__main__":
    print("🎙️ Enhanced Main Integration")
    print("=" * 60)
    print("This module provides enhanced voice processing for main.py")
    print("Import the functions in your main.py to use enhanced processing:")
    print("")
    print("from enhanced_main_integration import enhanced_audio_processing, get_enhanced_greeting")
    print("")
    print("# In your WebSocket handler:")
    print("result = await enhanced_audio_processing(audio_bytes, customer_info, conversation_stage)")
    print("if result['success']:")
    print("    response_audio = result['response_audio']")
    print("    # Send response_audio to WebSocket")
    print("=" * 60)
