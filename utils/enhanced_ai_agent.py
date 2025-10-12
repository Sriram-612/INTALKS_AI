"""
Enhanced AI Agent System - Integrated from vocode_sarvam_exotel
Provides advanced AI agent capabilities for customer interactions
"""
import os
import json
import asyncio
import base64
from typing import Dict, List, Optional, Any
from utils.logger import logger
from utils.production_asr import ProductionSarvamHandler

class EnhancedAIAgent:
    """
    Advanced AI Agent with enhanced capabilities for loan collection calls
    """
    
    def __init__(self, customer_data: Dict[str, Any], language: str = "en-IN"):
        self.customer_data = customer_data
        self.language = language
        self.conversation_history = []
        self.agent_mode = True
        self.sarvam_handler = ProductionSarvamHandler(os.getenv("SARVAM_API_KEY"))
        
        # Enhanced system prompt for AI agent
        self.system_prompt = self._build_agent_system_prompt()
        self.conversation_history.append({
            "role": "system", 
            "content": self.system_prompt
        })
        
        logger.websocket.info(f"🤖 Enhanced AI Agent initialized for {customer_data.get('name', 'Unknown')}")
    
    def _build_agent_system_prompt(self) -> str:
        """Build comprehensive system prompt for AI agent"""
        customer_name = self.customer_data.get('name', 'Customer')
        loan_id = self.customer_data.get('loan_id', 'N/A')
        amount = self.customer_data.get('amount', 0)
        due_date = self.customer_data.get('due_date', 'N/A')
        
        return f"""You are an EXPERT Collections Specialist Agent for South India Finvest Bank.

CUSTOMER CONTEXT:
- Name: {customer_name}
- Loan ID: {loan_id}
- Outstanding Amount: ₹{amount}
- Due Date: {due_date}
- Language: {self.language}

AGENT CAPABILITIES:
1. PAYMENT SOLUTIONS:
   - Offer flexible payment plans (part payments, EMI restructuring)
   - Provide multiple payment channels (UPI, Net Banking, Branch visit)
   - Calculate revised EMI amounts based on customer's financial situation
   
2. EMPATHETIC COMMUNICATION:
   - Acknowledge customer's financial difficulties with understanding
   - Use supportive language, avoid aggressive collection tactics
   - Show genuine concern for customer's wellbeing
   
3. PROBLEM RESOLUTION:
   - Listen actively to customer's concerns and constraints
   - Provide practical solutions based on their specific situation
   - Offer grace periods or temporary relief if appropriate
   
4. ESCALATION MANAGEMENT:
   - Know when to escalate to human agents
   - Provide clear next steps and timelines
   - Ensure customer feels heard and valued

CONVERSATION GUIDELINES:
- Be conversational but professional
- Keep responses concise (2-3 sentences max)
- Ask clarifying questions to understand customer's situation
- Offer specific, actionable solutions
- Always end with clear next steps
- Support barge-in (if customer interrupts, acknowledge and respond)

LANGUAGE: Respond in {self.language} language.

Remember: Your goal is to find a mutually beneficial solution that helps the customer while protecting the bank's interests."""

    async def process_customer_input(self, transcript: str) -> str:
        """Process customer input and generate appropriate response"""
        try:
            # Add customer input to conversation history
            self.conversation_history.append({
                "role": "user",
                "content": transcript
            })
            
            # Generate AI response using Claude/GPT
            response = await self._generate_ai_response()
            
            # Add AI response to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": response
            })
            
            logger.websocket.info(f"🤖 AI Agent Response: {response}")
            return response
            
        except Exception as e:
            logger.error.error(f"❌ Error processing customer input: {e}")
            return "I apologize, I'm having some technical difficulties. Let me connect you with a human agent who can assist you better."
    
    async def _generate_ai_response(self) -> str:
        """Generate AI response using available LLM"""
        try:
            # Use Claude via Bedrock if available
            from utils import bedrock_client
            
            # Prepare messages for Claude
            messages = []
            system_content = ""
            
            for msg in self.conversation_history:
                if msg["role"] == "system":
                    system_content += msg["content"] + "\n"
                else:
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
            
            # Call Claude via Bedrock using the correct invoke_claude_model function
            # Uses CLAUDE_MODEL_ID for main conversation AI (Claude 3.7 Sonnet)
            claude_model_id = os.getenv("CLAUDE_MODEL_ID", "arn:aws:bedrock:eu-north-1:844605843483:inference-profile/eu.anthropic.claude-3-7-sonnet-20250219-v1:0")
            
            # Convert messages to Bedrock format
            bedrock_messages = []
            for msg in messages:
                bedrock_messages.append({
                    "role": msg["role"],
                    "content": [{"type": "text", "text": msg["content"]}]
                })
            
            # Add system message as user message if exists
            if system_content.strip():
                bedrock_messages.insert(0, {
                    "role": "user", 
                    "content": [{"type": "text", "text": system_content.strip()}]
                })
            
            # Use the existing invoke_claude_model function
            response_text = bedrock_client.invoke_claude_model(bedrock_messages, claude_model_id)
            
            return response_text.strip()
            
        except Exception as e:
            logger.error.error(f"❌ Error generating AI response: {e}")
            # Fallback to predefined responses
            return self._get_fallback_response()
    
    def _get_fallback_response(self) -> str:
        """Provide fallback response if AI generation fails"""
        fallback_responses = {
            "en-IN": "I understand your situation. Let me help you find the best payment solution. Can you tell me about your current financial constraints?",
            "hi-IN": "मैं आपकी स्थिति समझती हूं। आइए मिलकर सबसे अच्छा भुगतान समाधान खोजते हैं। क्या आप अपनी वर्तमान वित्तीय कठिनाइयों के बारे में बता सकते हैं?",
            "ta-IN": "உங்கள் நிலைமையை நான் புரிந்துகொள்கிறேன். சிறந்த கட்டணத் தீர்வைக் கண்டறிய உதவுகிறேன். உங்கள் தற்போதைய நிதிக் கட்டுப்பாடுகளைப் பற்றி சொல்ல முடியுமா?",
            "te-IN": "మీ పరిస్థితిని నేను అర్థం చేసుకున్నాను. ఉత్తమ చెల్లింపు పరిష్కారాన్ని కనుగొనడంలో సహాయం చేస్తాను. మీ ప్రస్తుత ఆర్థిక పరిమితుల గురించి చెప్పగలరా?"
        }
        
        return fallback_responses.get(self.language, fallback_responses["en-IN"])
    
    async def generate_audio_response(self, text_response: str) -> bytes:
        """Convert text response to audio using Sarvam TTS"""
        try:
            audio_bytes = await self.sarvam_handler.synthesize_tts(text_response, self.language)
            logger.websocket.info(f"🎵 Generated {len(audio_bytes)} bytes of audio for AI agent response")
            return audio_bytes
            
        except Exception as e:
            logger.error.error(f"❌ Error generating audio response: {e}")
            # Return empty bytes if TTS fails
            return b""
    
    async def handle_conversation_turn(self, transcript: str, websocket) -> bool:
        """Handle a complete conversation turn (input -> processing -> audio response)"""
        try:
            logger.websocket.info(f"🤖 AI Agent processing: '{transcript[:50]}...'")
            
            # Generate text response
            text_response = await self.process_customer_input(transcript)
            logger.websocket.info(f"💬 AI Agent response: '{text_response[:100]}...'")
            
            # Convert to audio
            audio_bytes = await self.generate_audio_response(text_response)
            
            if audio_bytes:
                # Stream audio response with better error handling
                try:
                    await self._stream_audio_to_websocket(websocket, audio_bytes)
                    logger.websocket.info("✅ AI Agent conversation turn completed successfully")
                    return True
                except Exception as stream_error:
                    logger.error.error(f"❌ Error streaming audio in conversation turn: {stream_error}")
                    # Even if audio streaming fails, the conversation turn was processed
                    return True
            else:
                logger.error.error("❌ Failed to generate audio response")
                # Return True anyway - text processing succeeded even if audio failed
                return True
                
        except Exception as e:
            logger.error.error(f"❌ Error in conversation turn: {e}")
            import traceback
            logger.error.error(f"🔍 Conversation turn traceback: {traceback.format_exc()}")
            return False
    
    async def _stream_audio_to_websocket(self, websocket, audio_bytes: bytes):
        """Stream audio response to WebSocket with enhanced error handling"""
        if not audio_bytes:
            logger.websocket.warning("⚠️ No audio bytes to stream")
            return
        
        CHUNK_SIZE = 1600
        chunks_sent = 0
        
        try:
            # Enhanced WebSocket state checking with better error handling
            try:
                if not hasattr(websocket, 'client_state') or websocket.client_state is None:
                    logger.websocket.error("❌ WebSocket has no client_state attribute or is None")
                    return
                    
                initial_state = getattr(websocket.client_state, 'name', 'UNKNOWN')
                if initial_state not in ['CONNECTED']:
                    logger.websocket.warning(f"⚠️ WebSocket not connected (state={initial_state}). Skipping audio stream.")
                    return
                    
                # Additional check: try a small test operation to verify connection
                if hasattr(websocket, 'send_json'):
                    # WebSocket appears to be valid
                    pass
                else:
                    logger.websocket.error("❌ WebSocket missing send_json method - invalid connection")
                    return
                    
            except Exception as state_check_error:
                logger.websocket.error(f"❌ Error checking WebSocket state: {state_check_error}")
                return
            
            logger.websocket.info(f"🎧 Starting audio stream: {len(audio_bytes)} bytes, {len(audio_bytes)//CHUNK_SIZE + 1} chunks")
            
            for i in range(0, len(audio_bytes), CHUNK_SIZE):
                chunk = audio_bytes[i:i + CHUNK_SIZE]
                if not chunk:
                    continue
                
                try:
                    b64_chunk = base64.b64encode(chunk).decode("utf-8")
                    response_msg = {
                        "event": "media",
                        "media": {"payload": b64_chunk}
                    }
                    
                    # Enhanced WebSocket state check before each send
                    try:
                        current_state = getattr(websocket.client_state, 'name', 'UNKNOWN') if hasattr(websocket, 'client_state') and websocket.client_state else 'UNKNOWN'
                        if current_state not in ['CONNECTED']:
                            logger.websocket.warning(f"⚠️ WebSocket disconnected during stream (state={current_state}). Sent {chunks_sent} chunks.")
                            break
                        
                        await websocket.send_json(response_msg)
                    except Exception as send_error:
                        logger.websocket.error(f"❌ Error sending WebSocket message: {send_error}")
                        # If it's a connection error, break the loop
                        if "not connected" in str(send_error).lower() or "accept" in str(send_error).lower():
                            logger.websocket.error("❌ WebSocket connection lost, stopping audio stream")
                            break
                        # For other errors, try to continue
                        continue
                    chunks_sent += 1
                    await asyncio.sleep(0.02)  # Pace the audio
                    
                except Exception as chunk_error:
                    logger.error.error(f"❌ Error sending audio chunk {chunks_sent}: {chunk_error}")
                    # Try to continue with next chunk
                    continue
                
            logger.websocket.info(f"✅ AI Agent audio response streamed successfully ({chunks_sent} chunks)")
            
        except Exception as e:
            logger.error.error(f"❌ Error streaming AI agent audio: {e}")
            import traceback
            logger.error.error(f"🔍 Audio streaming traceback: {traceback.format_exc()}")
            # Don't return empty bytes, let the caller handle the error
    
    def get_conversation_summary(self) -> Dict[str, Any]:
        """Get summary of the conversation for logging/analytics"""
        return {
            "customer_name": self.customer_data.get('name'),
            "loan_id": self.customer_data.get('loan_id'),
            "language": self.language,
            "total_turns": len([msg for msg in self.conversation_history if msg["role"] in ["user", "assistant"]]),
            "agent_mode": self.agent_mode,
            "conversation_length": len(self.conversation_history)
        }

class AIAgentManager:
    """Manages multiple AI agent instances"""
    
    def __init__(self):
        self.active_agents: Dict[str, EnhancedAIAgent] = {}
        logger.websocket.info("🤖 AI Agent Manager initialized")
    
    async def create_agent(self, session_id: str, customer_data: Dict[str, Any], language: str = "en-IN") -> EnhancedAIAgent:
        """Create a new AI agent instance"""
        agent = EnhancedAIAgent(customer_data, language)
        self.active_agents[session_id] = agent
        logger.websocket.info(f"🤖 Created AI agent for session {session_id}")
        return agent
    
    def get_agent(self, session_id: str) -> Optional[EnhancedAIAgent]:
        """Get existing AI agent instance"""
        return self.active_agents.get(session_id)
    
    def remove_agent(self, session_id: str):
        """Remove AI agent instance"""
        if session_id in self.active_agents:
            agent = self.active_agents.pop(session_id)
            summary = agent.get_conversation_summary()
            logger.websocket.info(f"🤖 Removed AI agent for session {session_id}. Summary: {summary}")

# Global AI Agent Manager instance
ai_agent_manager = AIAgentManager()
