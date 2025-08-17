#!/usr/bin/env python3
"""
Test Sarvam TTS Audio Format
"""
import asyncio
import base64
import io
import os
from dotenv import load_dotenv

load_dotenv()

# Add project path
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.production_asr import ProductionSarvamHandler

async def test_sarvam_audio_format():
    """Test what format Sarvam TTS returns"""
    print("🔧 Testing Sarvam TTS Audio Format...")
    
    api_key = os.getenv("SARVAM_API_KEY")
    handler = ProductionSarvamHandler(api_key)
    
    # Test TTS
    text = "नमस्ते, यह एक टेस्ट है।"
    print(f"🎵 Generating TTS for: {text}")
    
    try:
        audio_bytes = await handler.synthesize_tts(text, "hi-IN")
        
        if audio_bytes and len(audio_bytes) > 0:
            print(f"✅ TTS Success: {len(audio_bytes)} bytes")
            
            # Check first 16 bytes for format identification
            first_16 = audio_bytes[:16]
            print(f"📊 First 16 bytes: {first_16.hex()}")
            print(f"📊 First 16 bytes ASCII: {repr(first_16)}")
            
            # Check for specific format headers
            if audio_bytes.startswith(b'RIFF'):
                print("🎵 Format: WAV file detected")
            elif audio_bytes.startswith(b'ID3') or audio_bytes.startswith(b'\xff\xfb'):
                print("🎵 Format: MP3 file detected")
            else:
                print("🎵 Format: Raw PCM or unknown format")
                
            # Save for manual inspection
            with open('/tmp/sarvam_audio_debug.raw', 'wb') as f:
                f.write(audio_bytes)
            print(f"💾 Audio saved to: /tmp/sarvam_audio_debug.raw")
            
            # Try to analyze sample rate and format
            try:
                from pydub import AudioSegment
                
                # Try as WAV first
                if audio_bytes.startswith(b'RIFF'):
                    audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
                    print(f"📊 WAV Analysis:")
                    print(f"   Sample Rate: {audio.frame_rate} Hz")
                    print(f"   Channels: {audio.channels}")
                    print(f"   Sample Width: {audio.sample_width} bytes")
                    print(f"   Duration: {len(audio)} ms")
                    
                    # Convert to telephony format
                    telephony_audio = audio.set_frame_rate(8000).set_channels(1).set_sample_width(2)
                    pcm_data = telephony_audio.raw_data
                    
                    print(f"🔄 Telephony Conversion:")
                    print(f"   Original size: {len(audio_bytes)} bytes")
                    print(f"   PCM size: {len(pcm_data)} bytes")
                    print(f"   Duration: {len(pcm_data) / (8000 * 2):.2f} seconds")
                    
                    # Save converted PCM
                    with open('/tmp/sarvam_pcm_debug.raw', 'wb') as f:
                        f.write(pcm_data)
                    print(f"💾 PCM audio saved to: /tmp/sarvam_pcm_debug.raw")
                    print(f"🎵 To play: ffplay -f s16le -ar 8000 -ac 1 /tmp/sarvam_pcm_debug.raw")
                    
                else:
                    # Try to load as raw PCM
                    try:
                        audio = AudioSegment(
                            audio_bytes,
                            sample_width=2,
                            frame_rate=8000,
                            channels=1
                        )
                        print(f"📊 Raw PCM Analysis:")
                        print(f"   Assumed: 8000 Hz, 16-bit, mono")
                        print(f"   Duration: {len(audio)} ms")
                        print(f"   Size matches expected: {len(audio_bytes) == len(audio) * 8000 * 2 // 1000}")
                        
                    except Exception as pcm_error:
                        print(f"❌ PCM Analysis failed: {pcm_error}")
                        
            except ImportError:
                print("⚠️ pydub not available for format analysis")
            except Exception as e:
                print(f"❌ Audio analysis failed: {e}")
                
        else:
            print("❌ No audio bytes generated")
            
    except Exception as e:
        print(f"❌ TTS Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_sarvam_audio_format())
