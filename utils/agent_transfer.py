import httpx
import os
from utils.handler_asr import SarvamHandler

SARVAM_API_KEY = "sk_eripea2q_qPQFtS6uPiAFrhgDGZtKMLzx"

sarvam = SarvamHandler(SARVAM_API_KEY)
EXOTEL_SID = os.getenv("EXOTEL_SID")
EXOTEL_TOKEN = os.getenv("EXOTEL_TOKEN")
EXOPHONE = os.getenv("EXOTEL_VIRTUAL_NUMBER")
AGENT_NUMBER = os.getenv("AGENT_PHONE_NUMBER")
EXOTEL_API_KEY = os.getenv("EXOTEL_API_KEY")



async def trigger_exotel_agent_transfer(customer_number: str, agent_number: str):
    print("[Exotel] 📞 Initiating agent call transfer")

    url = f"https://api.exotel.com/v1/Accounts/{EXOTEL_SID}/Calls/connect.json"
    payload = {
        "From": customer_number,
        "To": agent_number,
        "CallerId": EXOPHONE,
    }

    try:
        async with httpx.AsyncClient(auth=(EXOTEL_SID, EXOTEL_TOKEN)) as client:
            response = await client.post(url, data=payload)

        if response.status_code == 200:
            print("[Exotel] ✅ Call transfer request successful")
        else:
            print(f"[Exotel] ❌ Failed to transfer call. Status {response.status_code} - {response.text}")

    except Exception as e:
        print(f"[Exotel] ❌ Exception occurred during call transfer: {e}")  

async def trigger_ai_agent_mode(websocket, customer_data: dict, session_id: str = None, language: str = "en-IN"):
    """Switch to Enhanced AI Agent mode within same WebSocket connection"""
    logger.websocket.info("[AI Agent] 🤖 Switching to Enhanced AI Agent mode")
    
    try:
        # Use call_sid as session_id for consistency
        if not session_id:
            session_id = f"agent_{customer_data.get('id', 'unknown')}"
        
        logger.websocket.info(f"[AI Agent] Creating agent with session_id: {session_id}")
        
        # Create enhanced AI agent
        ai_agent = await ai_agent_manager.create_agent(session_id, customer_data, language)
        
        # Agent introduction message
        customer_name = customer_data.get('name', 'valued customer')
        agent_intro = f"Hello {customer_name}, I'm your specialist collections agent. I have reviewed your loan account and I'm here to work with you on finding the best payment solution. How can I help you today?"
        
        # Generate and stream agent introduction with better error handling
        try:
            audio_bytes = await ai_agent.generate_audio_response(agent_intro)
            if audio_bytes:
                # Check WebSocket state more robustly
                try:
                    # Test if websocket is still active by checking if we can send a small message
                    if hasattr(websocket, 'client_state') and websocket.client_state.name == 'CONNECTED':
                        await ai_agent._stream_audio_to_websocket(websocket, audio_bytes)
                        logger.websocket.info("[AI Agent] ✅ Agent introduction streamed successfully")
                    else:
                        logger.websocket.warning("[AI Agent] ⚠️ WebSocket not in CONNECTED state, skipping audio stream")
                except Exception as stream_error:
                    logger.error.error(f"[AI Agent] ❌ Error streaming agent introduction: {stream_error}")
                    # Continue without failing - AI agent can still work via text
            else:
                logger.websocket.warning("[AI Agent] ⚠️ No audio bytes generated for introduction")
        except Exception as audio_error:
            logger.error.error(f"[AI Agent] ❌ Error generating agent introduction audio: {audio_error}")
            # Continue without audio - AI agent can still work
        
        logger.websocket.info("[AI Agent] ✅ Successfully switched to Enhanced AI Agent mode")
        return ai_agent
        
    except Exception as e:
        logger.error.error(f"[AI Agent] ❌ Exception occurred during AI agent mode switch: {e}")
        import traceback
        logger.error.error(f"[AI Agent] 🔍 Full traceback: {traceback.format_exc()}")
        return None