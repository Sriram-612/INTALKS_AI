"""
WebSocket AI Agent Handler
Handles AI agent conversation mode in the WebSocket
"""
import asyncio
from utils.logger import logger
from utils.enhanced_ai_agent import ai_agent_manager

async def handle_ai_agent_conversation(websocket, transcript: str, call_sid: str, customer_info: dict, call_detected_lang: str):
    """
    Handle conversation when in AI_AGENT_MODE
    
    Args:
        websocket: WebSocket connection
        transcript: Customer's speech transcript
        call_sid: Call session ID
        customer_info: Customer information
        call_detected_lang: Detected language
        
    Returns:
        bool: True if conversation should continue, False if should end
    """
    try:
        logger.websocket.info(f"🔍 [AI Agent Handler] Looking for AI agent with session_id: {call_sid}")
        logger.websocket.info(f"💬 [AI Agent Handler] Processing transcript: '{transcript[:100]}...'")
        
        # ✅ CRITICAL FIX: Validate transcript before processing
        if not transcript or not transcript.strip():
            logger.websocket.info(f"⚠️ [AI Agent Handler] Empty or whitespace-only transcript, skipping processing")
            return True  # Continue waiting for actual user input
        
        # Filter out very short or meaningless transcripts
        cleaned_transcript = transcript.strip()
        if len(cleaned_transcript) < 3:
            logger.websocket.info(f"⚠️ [AI Agent Handler] Transcript too short ('{cleaned_transcript}'), waiting for more input")
            return True  # Continue waiting for meaningful input
        
        # Filter out common noise patterns
        noise_patterns = ['um', 'uh', 'hmm', 'ah', 'er', 'oh', '...', 'mm']
        if cleaned_transcript.lower() in noise_patterns:
            logger.websocket.info(f"⚠️ [AI Agent Handler] Detected noise pattern ('{cleaned_transcript}'), waiting for actual speech")
            return True  # Continue waiting for actual speech
        
        logger.websocket.info(f"✅ [AI Agent Handler] Valid transcript received: '{cleaned_transcript}'")
        
        # Get the AI agent for this session
        ai_agent = ai_agent_manager.get_agent(call_sid)
        
        if not ai_agent:
            logger.error.error(f"❌ [AI Agent Handler] No AI agent found for session {call_sid}")
            logger.websocket.info(f"🔍 [AI Agent Handler] Available agents: {list(ai_agent_manager.active_agents.keys())}")
            
            # Try to find agent with alternative session ID patterns
            for agent_id in ai_agent_manager.active_agents.keys():
                if call_sid in agent_id or agent_id in call_sid:
                    logger.websocket.info(f"🔄 [AI Agent Handler] Found agent with alternative ID: {agent_id}")
                    ai_agent = ai_agent_manager.get_agent(agent_id)
                    break
            
            if not ai_agent:
                logger.error.error(f"❌ [AI Agent Handler] No AI agent found even with fallback search")
                logger.websocket.info(f"⚠️ [AI Agent Handler] Attempting to create new agent for session {call_sid}")
                
                # Try to create a new agent if none exists
                try:
                    from utils.agent_transfer import trigger_ai_agent_mode
                    ai_agent = await trigger_ai_agent_mode(websocket, customer_info, call_sid, call_detected_lang)
                    if ai_agent:
                        logger.websocket.info(f"✅ [AI Agent Handler] Successfully created new AI agent")
                    else:
                        logger.error.error(f"❌ [AI Agent Handler] Failed to create new AI agent")
                        return False
                except Exception as create_error:
                    logger.error.error(f"❌ [AI Agent Handler] Error creating new AI agent: {create_error}")
                    return False
        
        # Check if we should escalate to human based on conversation content
        conversation_turns = len([msg for msg in ai_agent.conversation_history if msg["role"] in ["user", "assistant"]])
        if should_escalate_to_human(transcript, conversation_turns):
            logger.websocket.info(f"👥 [AI Agent Handler] Escalating to human agent based on conversation analysis")
            return False
        
        # Process customer input and generate response
        success = await ai_agent.handle_conversation_turn(transcript, websocket)
        
        if success:
            logger.websocket.info(f"✅ [AI Agent Handler] AI agent handled conversation turn successfully")
            return True
        else:
            logger.error.error(f"❌ [AI Agent Handler] AI agent failed to handle conversation turn")
            # Don't immediately fail - give it another chance
            logger.websocket.info(f"🔄 [AI Agent Handler] Giving AI agent another chance...")
            return True
            
    except Exception as e:
        logger.error.error(f"❌ [AI Agent Handler] Error in AI agent conversation: {e}")
        import traceback
        logger.error.error(f"🔍 [AI Agent Handler] Full traceback: {traceback.format_exc()}")
        return False

async def cleanup_ai_agent_session(call_sid: str):
    """Clean up AI agent session when call ends"""
    try:
        ai_agent_manager.remove_agent(call_sid)
        logger.websocket.info(f"🧹 Cleaned up AI agent session for {call_sid}")
    except Exception as e:
        logger.error.error(f"❌ Error cleaning up AI agent session: {e}")

def should_escalate_to_human(transcript: str, conversation_turns: int) -> bool:
    """
    Determine if conversation should be escalated to human agent
    
    Args:
        transcript: Latest customer input
        conversation_turns: Number of conversation turns
        
    Returns:
        bool: True if should escalate to human
    """
    # Escalation triggers
    escalation_keywords = [
        "human", "person", "real agent", "live agent", "manager", 
        "supervisor", "complaint", "escalate", "transfer me",
        "not satisfied", "this is not working", "frustrated"
    ]
    
    # Check for escalation keywords
    transcript_lower = transcript.lower()
    if any(keyword in transcript_lower for keyword in escalation_keywords):
        return True
    
    # Escalate after too many turns without resolution
    if conversation_turns > 10:
        return True
    
    return False
