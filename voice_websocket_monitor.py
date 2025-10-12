#!/usr/bin/env python3
"""
Voice WebSocket Monitor
======================
Monitors real-time voice interactions via WebSocket connections.
Tracks the voice pipeline: Audio Input → STT → Claude → TTS → Audio Output
"""

import asyncio
import websockets
import json
import time
from typing import Dict, Any
import traceback
from dotenv import load_dotenv

load_dotenv()

class VoiceWebSocketMonitor:
    """
    Monitors voice interactions in real-time via WebSocket
    """
    
    def __init__(self, base_url: str = "wss://9a81252242ca.ngrok-free.app"):
        self.base_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
        self.active_sessions = {}
        self.voice_pipeline_stats = {
            "total_interactions": 0,
            "stt_calls": 0,
            "claude_calls": 0,
            "tts_calls": 0,
            "errors": 0
        }
    
    async def monitor_dashboard_websocket(self, session_id: str = "monitor"):
        """Monitor dashboard WebSocket for call status updates"""
        uri = f"{self.base_url}/ws/dashboard/{session_id}"
        
        print(f"🔌 Connecting to dashboard WebSocket: {uri}")
        
        try:
            async with websockets.connect(uri) as websocket:
                print("✅ Connected to dashboard WebSocket")
                print("📊 Monitoring call status updates...")
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        await self._process_dashboard_message(data)
                    except json.JSONDecodeError:
                        print(f"📨 Raw message: {message}")
                    except Exception as e:
                        print(f"❌ Error processing message: {e}")
                        
        except Exception as e:
            print(f"❌ Dashboard WebSocket error: {e}")
    
    async def monitor_voicebot_websocket(self, session_id: str, call_sid: str = None):
        """Monitor voicebot WebSocket for voice interactions"""
        params = f"?call_sid={call_sid}" if call_sid else ""
        uri = f"{self.base_url}/ws/voicebot/{session_id}{params}"
        
        print(f"🎙️ Connecting to voicebot WebSocket: {uri}")
        
        try:
            async with websockets.connect(uri) as websocket:
                print("✅ Connected to voicebot WebSocket")
                print("🎧 Monitoring voice pipeline...")
                print("   Listening for: Audio → STT → Claude → TTS → Audio")
                
                # Send start message to initiate conversation
                start_message = {
                    "event": "start",
                    "start": {
                        "streamSid": session_id,
                        "callSid": call_sid or session_id
                    }
                }
                await websocket.send(json.dumps(start_message))
                print("📤 Sent start message")
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        await self._process_voicebot_message(data, session_id)
                    except json.JSONDecodeError:
                        print(f"📨 Raw voicebot message: {message}")
                    except Exception as e:
                        print(f"❌ Error processing voicebot message: {e}")
                        
        except Exception as e:
            print(f"❌ Voicebot WebSocket error: {e}")
    
    async def _process_dashboard_message(self, data: Dict[str, Any]):
        """Process dashboard WebSocket messages"""
        message_type = data.get("type", "unknown")
        
        if message_type == "call_status_update":
            call_sid = data.get("call_sid")
            status = data.get("status")
            customer_name = data.get("customer_name", "Unknown")
            
            print(f"📞 Call Status Update:")
            print(f"   Call SID: {call_sid}")
            print(f"   Customer: {customer_name}")
            print(f"   Status: {status}")
            
            if status == "call_in_progress":
                print("🎯 Call is now active - voice pipeline should be starting!")
            elif status == "call_completed":
                print("🏁 Call completed - voice pipeline ended")
            elif status == "call_failed":
                print("❌ Call failed")
        
        elif message_type == "websocket_activity":
            session_id = data.get("session_id")
            activity = data.get("activity")
            print(f"🔌 WebSocket Activity: {session_id} - {activity}")
        
        else:
            print(f"📨 Dashboard message: {data}")
    
    async def _process_voicebot_message(self, data: Dict[str, Any], session_id: str):
        """Process voicebot WebSocket messages"""
        event = data.get("event", "unknown")
        
        if event == "start":
            print(f"🚀 Voice session started: {session_id}")
            self.active_sessions[session_id] = {
                "start_time": time.time(),
                "interactions": 0,
                "last_activity": time.time()
            }
        
        elif event == "media":
            # Audio data received from customer
            media_data = data.get("media", {})
            payload = media_data.get("payload", "")
            
            if payload:
                print(f"🎤 Audio received: {len(payload)} bytes (base64)")
                self._update_session_activity(session_id)
        
        elif event == "transcript":
            # STT result
            transcript = data.get("transcript", "")
            language = data.get("language", "unknown")
            
            print(f"📝 STT Result:")
            print(f"   Transcript: '{transcript}'")
            print(f"   Language: {language}")
            
            self.voice_pipeline_stats["stt_calls"] += 1
            self._update_session_activity(session_id)
        
        elif event == "claude_response":
            # Claude LLM response
            response = data.get("response", "")
            
            print(f"🤖 Claude Response:")
            print(f"   Response: '{response}'")
            
            self.voice_pipeline_stats["claude_calls"] += 1
            self._update_session_activity(session_id)
        
        elif event == "tts_audio":
            # TTS audio generated
            audio_length = data.get("audio_length", 0)
            
            print(f"🔊 TTS Audio Generated:")
            print(f"   Length: {audio_length} bytes")
            
            self.voice_pipeline_stats["tts_calls"] += 1
            self._update_session_activity(session_id)
        
        elif event == "error":
            error_msg = data.get("message", "Unknown error")
            print(f"❌ Voice Pipeline Error: {error_msg}")
            self.voice_pipeline_stats["errors"] += 1
        
        elif event == "stop":
            print(f"🛑 Voice session ended: {session_id}")
            if session_id in self.active_sessions:
                session_info = self.active_sessions[session_id]
                duration = time.time() - session_info["start_time"]
                print(f"   Duration: {duration:.1f} seconds")
                print(f"   Interactions: {session_info['interactions']}")
                del self.active_sessions[session_id]
        
        else:
            print(f"📨 Voicebot event '{event}': {data}")
    
    def _update_session_activity(self, session_id: str):
        """Update session activity"""
        if session_id in self.active_sessions:
            self.active_sessions[session_id]["last_activity"] = time.time()
            self.active_sessions[session_id]["interactions"] += 1
            self.voice_pipeline_stats["total_interactions"] += 1
    
    def print_stats(self):
        """Print voice pipeline statistics"""
        print("\n📊 Voice Pipeline Statistics:")
        print(f"   Total Interactions: {self.voice_pipeline_stats['total_interactions']}")
        print(f"   STT Calls: {self.voice_pipeline_stats['stt_calls']}")
        print(f"   Claude Calls: {self.voice_pipeline_stats['claude_calls']}")
        print(f"   TTS Calls: {self.voice_pipeline_stats['tts_calls']}")
        print(f"   Errors: {self.voice_pipeline_stats['errors']}")
        print(f"   Active Sessions: {len(self.active_sessions)}")
    
    async def monitor_call(self, call_sid: str, duration_minutes: int = 5):
        """Monitor a specific call"""
        print(f"🎯 Monitoring call {call_sid} for {duration_minutes} minutes")
        
        # Create monitoring tasks
        tasks = [
            asyncio.create_task(self.monitor_dashboard_websocket()),
            asyncio.create_task(self.monitor_voicebot_websocket(call_sid, call_sid))
        ]
        
        # Monitor for specified duration
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=duration_minutes * 60
            )
        except asyncio.TimeoutError:
            print(f"⏰ Monitoring timeout after {duration_minutes} minutes")
        
        # Cancel remaining tasks
        for task in tasks:
            if not task.done():
                task.cancel()
        
        self.print_stats()

async def main():
    """Main monitoring function"""
    print("🎧 Voice WebSocket Monitor")
    print("=" * 50)
    
    monitor = VoiceWebSocketMonitor()
    
    print("Select monitoring mode:")
    print("1. Monitor dashboard only")
    print("2. Monitor specific call")
    print("3. Monitor both dashboard and voicebot")
    
    choice = input("Enter choice (1-3): ").strip()
    
    try:
        if choice == "1":
            await monitor.monitor_dashboard_websocket()
        
        elif choice == "2":
            call_sid = input("Enter call SID to monitor: ").strip()
            duration = int(input("Monitor duration (minutes): ").strip() or "5")
            await monitor.monitor_call(call_sid, duration)
        
        elif choice == "3":
            # Monitor both
            tasks = [
                asyncio.create_task(monitor.monitor_dashboard_websocket()),
                asyncio.create_task(monitor.monitor_voicebot_websocket("test_session"))
            ]
            
            await asyncio.gather(*tasks, return_exceptions=True)
        
        else:
            print("Invalid choice. Monitoring dashboard...")
            await monitor.monitor_dashboard_websocket()
            
    except KeyboardInterrupt:
        print("\n👋 Monitoring stopped")
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
