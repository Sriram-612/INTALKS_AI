#!/usr/bin/env python3
"""
Fix for TTS Audio Streaming Issues
"""

async def enhanced_stream_audio_to_websocket(websocket, audio_bytes):
    """
    Enhanced audio streaming function with better format compliance
    """
    import asyncio
    import base64
    
    CHUNK_SIZE = 320  # 20ms of audio at 8kHz 16-bit mono (more typical for telephony)
    if not audio_bytes: 
        print("⚠️ No audio bytes to stream.")
        return
    
    # Check if WebSocket is still connected before streaming
    if websocket.client_state.name not in ['CONNECTED', 'CONNECTING']:
        print(f"⚠️ WebSocket not connected (state: {websocket.client_state.name}). Skipping audio stream.")
        return
    
    try:
        total_chunks = len(audio_bytes) // CHUNK_SIZE + (1 if len(audio_bytes) % CHUNK_SIZE else 0)
        print(f"📡 Starting ENHANCED audio stream: {len(audio_bytes)} bytes in {total_chunks} chunks, duration: {len(audio_bytes) / 16000:.2f}s")
        
        for i in range(0, len(audio_bytes), CHUNK_SIZE):
            # Check connection state before each chunk
            if websocket.client_state.name != 'CONNECTED':
                print(f"⚠️ WebSocket disconnected during streaming (state: {websocket.client_state.name}). Stopping audio stream.")
                break
                
            chunk = audio_bytes[i:i + CHUNK_SIZE]
            if not chunk:
                continue
                
            # Pad the last chunk if it's smaller than expected
            if len(chunk) < CHUNK_SIZE:
                chunk = chunk + b'\x00' * (CHUNK_SIZE - len(chunk))
            
            b64_chunk = base64.b64encode(chunk).decode("utf-8")
            
            # Use the exact format expected by Exotel/Twilio-style WebSockets
            response_msg = {
                "event": "media",
                "streamSid": getattr(websocket, 'stream_sid', 'default'),
                "media": {
                    "track": "outbound",
                    "chunk": str(i // CHUNK_SIZE + 1),
                    "timestamp": str(i * 1000 // 16000),  # Timestamp in milliseconds
                    "payload": b64_chunk
                }
            }
            
            await websocket.send_json(response_msg)
            
            # More precise timing: 20ms per chunk (320 bytes at 16000 bytes/sec)
            await asyncio.sleep(0.02)  # 20ms delay
            
        # Add a small buffer to ensure complete playback
        buffer_time = min(2.0, len(audio_bytes) / 16000 * 0.1)  # 10% buffer, max 2 seconds
        print(f"🛡️ Adding {buffer_time:.1f}s buffer time to ensure complete playback")
        await asyncio.sleep(buffer_time)
            
        print("✅ ENHANCED audio stream completed successfully: {} chunks delivered".format(total_chunks))
    except Exception as e:
        print(f"❌ Error streaming audio to WebSocket: {e}")
        raise

# Usage: Replace the stream_audio_to_websocket function in main.py with this enhanced version
