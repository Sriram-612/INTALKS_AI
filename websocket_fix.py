#!/usr/bin/env python3
"""
WebSocket Close Error Fix
Add this check to your stream_audio_to_websocket function
"""

# SOLUTION 1: Add WebSocket state check before sending
async def stream_audio_to_websocket_with_check(websocket, audio_bytes):
    print("🎵 [AUDIO_STREAM] Starting audio stream to WebSocket")
    if not audio_bytes:
        print("[AUDIO_STREAM] ❌ No audio bytes to stream.")
        return
    
    duration_ms = len(audio_bytes) / 16000 * 1000
    CHUNK_SIZE = 1600
    
    for i in range(0, len(audio_bytes), CHUNK_SIZE):
        chunk = audio_bytes[i:i + CHUNK_SIZE]
        if not chunk:
            continue
            
        b64_chunk = base64.b64encode(chunk).decode("utf-8")
        response_msg = {
            "event": "media",
            "media": {"payload": b64_chunk}
        }
        
        # ✅ CHECK: Is WebSocket still open before sending?
        try:
            # Simple check - if websocket is closed, this will fail immediately
            if hasattr(websocket, 'client_state') and str(websocket.client_state) in ['DISCONNECTED', 'CLOSED']:
                print(f"🛑 [AUDIO_STREAM] WebSocket closed, stopping at chunk {i//CHUNK_SIZE + 1}")
                break
                
            await websocket.send_json(response_msg)
            print(f"🎵 Sent chunk {i//CHUNK_SIZE + 1} ({len(chunk)} bytes)")
            
        except Exception as _e:
            error_msg = str(_e)
            if "close message has been sent" in error_msg or "closed" in error_msg.lower():
                print(f"🛑 [AUDIO_STREAM] WebSocket closed during streaming at chunk {i//CHUNK_SIZE + 1}")
                break  # Stop trying if WebSocket is closed
            else:
                print(f"❌ Send failed on chunk {i//CHUNK_SIZE + 1}: {_e}")
                continue  # Continue for other errors
                
        await asyncio.sleep(0.02)
    
    playback_wait = max(duration_ms / 1000, 1.0)
    await asyncio.sleep(playback_wait + 0.5)

# MANUAL FIX INSTRUCTIONS:
MANUAL_FIX = """
MANUAL FIX FOR WEBSOCKET CLOSE ERROR:
====================================

In your main.py stream_audio_to_websocket function, replace the try-except block with:

        try:
            # Check if WebSocket is still open
            if hasattr(websocket, 'client_state') and str(websocket.client_state) in ['DISCONNECTED', 'CLOSED']:
                print(f"🛑 WebSocket closed, stopping at chunk {i//CHUNK_SIZE + 1}")
                break
                
            await websocket.send_json(response_msg)
            print(f"🎵 Sent chunk {i//CHUNK_SIZE + 1} ({len(chunk)} bytes)")
            
        except Exception as _e:
            error_msg = str(_e)
            if "close message has been sent" in error_msg or "closed" in error_msg.lower():
                print(f"🛑 WebSocket closed during streaming at chunk {i//CHUNK_SIZE + 1}")
                break  # Stop trying if WebSocket is closed
            else:
                print(f"❌ Send failed on chunk {i//CHUNK_SIZE + 1}: {_e}")
                continue  # Continue for other errors

This will:
1. Check WebSocket state before sending
2. Stop gracefully when WebSocket is closed
3. Continue for other types of errors
"""

if __name__ == "__main__":
    print(MANUAL_FIX)
