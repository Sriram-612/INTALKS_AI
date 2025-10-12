#!/usr/bin/env python3
"""
Audio Streaming Fix for Voice Bot
This file contains the fixed audio streaming function to replace the problematic one in main.py
"""

import asyncio
import base64

CHUNK_SIZE = 1600

async def stream_audio_to_websocket_fixed(websocket, audio_bytes):
    """
    Fixed audio streaming function with better error handling and debugging
    Addresses the issue where TTS audio is generated but not played through WebSocket
    """
    print("🎵 [AUDIO_STREAM_FIXED] Starting audio stream to WebSocket")
    
    if not audio_bytes:
        print("❌ [AUDIO_STREAM_FIXED] No audio bytes to stream.")
        return False
    
    print(f"🎵 [AUDIO_STREAM_FIXED] Audio data received: {len(audio_bytes)} bytes")
    
    # Calculate duration for pacing
    duration_ms = len(audio_bytes) / 16000 * 1000  # 16kBps → ~8kHz mono SLIN
    print(f"🎵 [AUDIO_STREAM_FIXED] Calculated audio duration: {duration_ms:.0f}ms")
    
    chunk_count = 0
    successful_chunks = 0
    
    for i in range(0, len(audio_bytes), CHUNK_SIZE):
        chunk = audio_bytes[i:i + CHUNK_SIZE]
        if not chunk:
            continue
            
        chunk_count += 1
        b64_chunk = base64.b64encode(chunk).decode("utf-8")
        response_msg = {
            "event": "media",
            "media": {"payload": b64_chunk}
        }
        
        # Send audio chunk with improved error handling
        try:
            await websocket.send_json(response_msg)
            successful_chunks += 1
            if chunk_count % 10 == 0:  # Log every 10th chunk to avoid spam
                print(f"🎵 [AUDIO_STREAM_FIXED] Sent chunk {chunk_count} ({len(chunk)} bytes)")
        except Exception as e:
            print(f"❌ [AUDIO_STREAM_FIXED] Send failed on chunk {chunk_count}: {e}")
            print(f"❌ [AUDIO_STREAM_FIXED] WebSocket state: {getattr(websocket, 'client_state', 'unknown')}")
            # Continue with remaining chunks instead of breaking completely
            continue
            
        # Pace the audio streaming to match real-time playback
        await asyncio.sleep(0.02)  # 20ms between chunks
    
    success_rate = (successful_chunks / chunk_count) * 100 if chunk_count > 0 else 0
    print(f"🎵 [AUDIO_STREAM_FIXED] Completed streaming {successful_chunks}/{chunk_count} chunks ({success_rate:.1f}% success)")
    print(f"🎵 [AUDIO_STREAM_FIXED] Total audio duration: ~{duration_ms:.0f}ms")
    
    # Wait for audio playback to complete + buffer time for user to process
    playback_wait = max(duration_ms / 1000, 1.0)  # At least 1 second
    print(f"🎵 [AUDIO_STREAM_FIXED] Waiting {playback_wait + 0.5:.1f}s for audio playback completion")
    await asyncio.sleep(playback_wait + 0.5)  # Extra 500ms buffer
    
    return successful_chunks > 0


# Alternative simpler streaming function
async def stream_audio_simple(websocket, audio_bytes):
    """
    Simplified audio streaming function that removes problematic WebSocket state checking
    """
    print("🎵 [SIMPLE_STREAM] Starting simple audio stream")
    
    if not audio_bytes:
        print("❌ [SIMPLE_STREAM] No audio bytes")
        return False
    
    print(f"🎵 [SIMPLE_STREAM] Streaming {len(audio_bytes)} bytes")
    
    try:
        # Send in larger chunks for simplicity
        SIMPLE_CHUNK_SIZE = 3200  # 2x the original size
        chunk_count = 0
        
        for i in range(0, len(audio_bytes), SIMPLE_CHUNK_SIZE):
            chunk = audio_bytes[i:i + SIMPLE_CHUNK_SIZE]
            if not chunk:
                continue
                
            chunk_count += 1
            b64_chunk = base64.b64encode(chunk).decode("utf-8")
            
            message = {
                "event": "media",
                "media": {"payload": b64_chunk}
            }
            
            await websocket.send_json(message)
            print(f"🎵 [SIMPLE_STREAM] Sent chunk {chunk_count}")
            
            # Shorter delay for faster streaming
            await asyncio.sleep(0.05)
        
        print(f"🎵 [SIMPLE_STREAM] Successfully sent {chunk_count} chunks")
        
        # Wait for audio to play
        duration_seconds = len(audio_bytes) / 16000
        await asyncio.sleep(max(duration_seconds + 1, 2))
        
        return True
        
    except Exception as e:
        print(f"❌ [SIMPLE_STREAM] Error: {e}")
        return False


# Instructions for manual fix
MANUAL_FIX_INSTRUCTIONS = """
MANUAL FIX INSTRUCTIONS:
========================

To fix the audio streaming issue, you need to replace the stream_audio_to_websocket function in main.py.

1. Find this function in main.py (around line 437):
   async def stream_audio_to_websocket(websocket, audio_bytes):

2. Replace the problematic WebSocket state checking section:
   
   FIND THIS CODE:
   ```
   try:
       state = getattr(getattr(websocket, 'client_state', None), 'name', 'CONNECTED')
       if state not in ['CONNECTED', 'CONNECTING']:
           print(f"[stream_audio_to_websocket] WebSocket not connected (state={state}). Stopping stream.")
           break
       await websocket.send_json(response_msg)
   except Exception as _e:
       print(f"[stream_audio_to_websocket] Send failed: {_e}")
       break
   ```
   
   REPLACE WITH:
   ```
   try:
       await websocket.send_json(response_msg)
       print(f"🎵 Sent chunk {i//CHUNK_SIZE + 1}")
   except Exception as _e:
       print(f"❌ Send failed on chunk {i//CHUNK_SIZE + 1}: {_e}")
       continue  # Continue instead of break
   ```

3. Or alternatively, import this file and use stream_audio_simple function instead.

The main issue is the WebSocket state checking that's preventing audio from being sent.
"""

if __name__ == "__main__":
    print(MANUAL_FIX_INSTRUCTIONS)
