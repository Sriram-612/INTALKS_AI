#!/usr/bin/env python3
"""
Debug Audio Streaming Issues
Tests the complete audio pipeline from TTS to WebSocket streaming
"""
import asyncio
import base64
import json
import os
import tempfile
import websockets
import sys
from dotenv import load_dotenv
from utils.production_asr import ProductionSarvamHandler

load_dotenv()

async def test_audio_streaming_pipeline():
    """Test the complete audio streaming pipeline"""
    print("🔧 Testing Audio Streaming Pipeline...")
    
    # Initialize TTS handler
    api_key = os.getenv("SARVAM_API_KEY")
    handler = ProductionSarvamHandler(api_key)
    
    # Test 1: Generate TTS audio
    print("\n🎵 Step 1: Testing TTS Generation...")
    test_text = "नमस्ते, मैं प्रिया हूं, और साउथ इंडिया फिनवेस्ट बैंक की ओर से बात कर रही हूं।"
    try:
        audio_bytes = await handler.synthesize_tts(test_text, "hi-IN")
        if audio_bytes and len(audio_bytes) > 0:
            print(f"✅ TTS Success: Generated {len(audio_bytes)} bytes")
            print(f"   First 16 bytes: {audio_bytes[:16].hex()}")
            print(f"   Last 16 bytes: {audio_bytes[-16:].hex()}")
        else:
            print("❌ TTS Failed: No audio bytes generated")
            return False
    except Exception as e:
        print(f"❌ TTS Error: {e}")
        return False
    
    # Test 2: Check audio format and properties
    print("\n🔍 Step 2: Analyzing Audio Format...")
    chunk_size = 8000  # Same as used in WebSocket streaming
    total_chunks = len(audio_bytes) // chunk_size + (1 if len(audio_bytes) % chunk_size else 0)
    estimated_duration = len(audio_bytes) / (8000 * 2)  # 8kHz, 16-bit (2 bytes per sample)
    
    print(f"   Audio size: {len(audio_bytes)} bytes")
    print(f"   Estimated duration: {estimated_duration:.2f} seconds")
    print(f"   Total chunks for streaming: {total_chunks}")
    print(f"   Chunk size: {chunk_size} bytes")
    
    # Test 3: Simulate WebSocket message formatting
    print("\n📦 Step 3: Testing WebSocket Message Format...")
    try:
        # Test encoding first chunk
        first_chunk = audio_bytes[:chunk_size]
        b64_chunk = base64.b64encode(first_chunk).decode("utf-8")
        response_msg = {
            "event": "media",
            "media": {"payload": b64_chunk}
        }
        
        # Validate JSON serialization
        json_str = json.dumps(response_msg)
        print(f"✅ Message Format Valid")
        print(f"   Chunk size: {len(first_chunk)} bytes")
        print(f"   Base64 size: {len(b64_chunk)} characters")
        print(f"   JSON message size: {len(json_str)} characters")
        print(f"   Sample message: {json_str[:100]}...")
        
    except Exception as e:
        print(f"❌ Message Format Error: {e}")
        return False
    
    # Test 4: Save audio file for manual verification
    print("\n💾 Step 4: Saving Audio for Manual Verification...")
    try:
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
            f.write(audio_bytes)
            raw_file = f.name
        
        print(f"✅ Audio saved as: {raw_file}")
        print(f"   To play manually: ffplay -f s16le -ar 8000 -ac 1 {raw_file}")
        
        # Try to create a WAV file for easier testing
        try:
            from pydub import AudioSegment
            audio_segment = AudioSegment(
                audio_bytes,
                sample_width=2,
                frame_rate=8000,
                channels=1
            )
            wav_file = raw_file.replace('.raw', '.wav')
            audio_segment.export(wav_file, format="wav")
            print(f"✅ WAV file created: {wav_file}")
            print(f"   To play WAV: ffplay {wav_file}")
        except Exception as wav_error:
            print(f"⚠️ WAV conversion failed: {wav_error}")
            
    except Exception as e:
        print(f"❌ File Save Error: {e}")
    
    # Test 5: Check if there are any issues with specific audio characteristics
    print("\n🔬 Step 5: Audio Quality Analysis...")
    
    # Check for silence (all zeros)
    zero_count = audio_bytes.count(b'\x00')
    silence_percentage = (zero_count / len(audio_bytes)) * 100
    print(f"   Silence percentage: {silence_percentage:.1f}%")
    
    # Check for clipping (max/min values)
    import struct
    samples = struct.unpack('<' + 'h' * (len(audio_bytes) // 2), audio_bytes)
    max_sample = max(samples)
    min_sample = min(samples)
    print(f"   Sample range: {min_sample} to {max_sample}")
    print(f"   Peak amplitude: {max(abs(max_sample), abs(min_sample))}")
    
    # Check for reasonable volume level
    avg_amplitude = sum(abs(s) for s in samples) / len(samples)
    print(f"   Average amplitude: {avg_amplitude:.1f}")
    
    if silence_percentage > 80:
        print("❌ WARNING: Audio appears to be mostly silent!")
        return False
    elif avg_amplitude < 100:
        print("⚠️ WARNING: Audio amplitude is very low (might be inaudible)")
    elif avg_amplitude > 20000:
        print("⚠️ WARNING: Audio amplitude is very high (might be distorted)")
    else:
        print("✅ Audio amplitude looks reasonable")
    
    print("\n🎉 Audio Pipeline Test Complete!")
    return True

async def test_websocket_connection():
    """Test if we can connect to the WebSocket endpoint"""
    print("\n🔌 Testing WebSocket Connection...")
    
    try:
        # Test local WebSocket connection
        uri = "ws://localhost:8000/stream"
        print(f"   Connecting to: {uri}")
        
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket connection successful")
            
            # Send a test message
            test_message = {
                "event": "connected",
                "data": "test"
            }
            await websocket.send(json.dumps(test_message))
            print("✅ Test message sent")
            
            # Try to receive a response (with timeout)
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                print(f"✅ Received response: {response[:100]}...")
            except asyncio.TimeoutError:
                print("⚠️ No response received (timeout)")
                
    except Exception as e:
        print(f"❌ WebSocket connection failed: {e}")
        return False
    
    return True

def analyze_recent_logs():
    """Analyze recent logs for clues about audio issues"""
    print("\n📊 Analyzing Recent Logs...")
    
    log_files = [
        "logs/tts.log",
        "logs/websocket.log", 
        "logs/errors.log"
    ]
    
    for log_file in log_files:
        if os.path.exists(log_file):
            print(f"\n📁 Checking {log_file}:")
            try:
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    recent_lines = lines[-10:]  # Last 10 lines
                    
                    if recent_lines:
                        for line in recent_lines:
                            if any(keyword in line.lower() for keyword in ['error', 'fail', 'audio', 'tts', 'stream']):
                                print(f"   {line.strip()}")
                    else:
                        print("   No recent entries")
            except Exception as e:
                print(f"   Error reading log: {e}")
        else:
            print(f"\n📁 {log_file}: Not found")

async def main():
    """Run all audio debugging tests"""
    print("🚀 Voice Assistant Audio Debug Suite")
    print("=" * 50)
    
    # Test 1: Audio Pipeline
    pipeline_ok = await test_audio_streaming_pipeline()
    
    # Test 2: WebSocket Connection
    websocket_ok = await test_websocket_connection()
    
    # Test 3: Log Analysis
    analyze_recent_logs()
    
    # Summary
    print("\n" + "=" * 50)
    print("🏁 DEBUG SUMMARY:")
    print(f"   Audio Pipeline: {'✅ PASS' if pipeline_ok else '❌ FAIL'}")
    print(f"   WebSocket Connection: {'✅ PASS' if websocket_ok else '❌ FAIL'}")
    
    if pipeline_ok and websocket_ok:
        print("\n✅ All tests passed! The issue might be:")
        print("   1. Exotel WebSocket compatibility")
        print("   2. Audio timing/buffering issues")
        print("   3. Call flow logic problems")
        print("\nNext steps:")
        print("   1. Test with actual phone calls")
        print("   2. Check Exotel WebSocket logs")
        print("   3. Monitor real-time streaming during calls")
    else:
        print("\n❌ Issues found! Fix these before testing calls:")
        if not pipeline_ok:
            print("   - Audio generation/formatting problems")
        if not websocket_ok:
            print("   - WebSocket connection issues")

if __name__ == "__main__":
    asyncio.run(main())
