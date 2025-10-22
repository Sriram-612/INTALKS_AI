#!/usr/bin/env python3
"""
Voice Pipeline Test - Direct Voice Processing
============================================
Tests the voice processing pipeline directly without WebSocket complexity:
Customer Input → STT → Claude → TTS → Audio Output

This simulates the exact same processing that happens in main.py
"""

import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from enhanced_voice_test import EnhancedVoiceTest

async def test_single_interaction():
    """Test a single voice interaction"""
    print("🎯 Testing Single Voice Interaction")
    print("=" * 50)
    
    tester = EnhancedVoiceTest()
    
    # Customer data
    customer_data = tester.voice_tester.test_customers["test_customer_1"]
    print(f"👤 Customer: {customer_data['name']}")
    print(f"📞 Phone: {customer_data['phone']}")
    print(f"💰 Loan: {customer_data['loan_id']} - ₹{customer_data['amount']}")
    
    # Simulate customer input
    customer_input = "Hello, I received a call about my loan payment. I need help with payment options."
    
    print(f"\n🎤 Customer says: '{customer_input}'")
    print("\n🔄 Processing through voice pipeline...")
    
    # Step 1: STT (Speech-to-Text)
    print("📝 Step 1: Speech-to-Text...")
    transcript = await tester._simulate_stt(customer_input, customer_data['language_code'])
    print(f"   Result: '{transcript}'")
    
    # Step 2: Claude LLM Processing
    print("🤖 Step 2: Claude LLM Processing...")
    conversation_id = f"test_{int(asyncio.get_event_loop().time())}"
    
    # Initialize conversation with system prompt
    system_prompt = tester._build_customer_system_prompt(customer_data)
    tester.conversation_history[conversation_id] = [{
        "role": "system",
        "content": system_prompt
    }]
    
    ai_response = await tester._process_with_claude(transcript, conversation_id)
    print(f"   Result: '{ai_response}'")
    
    # Step 3: TTS (Text-to-Speech)
    print("🔊 Step 3: Text-to-Speech...")
    audio_bytes = await tester._simulate_tts(ai_response, customer_data['language_code'])
    print(f"   Result: {len(audio_bytes)} bytes of audio generated")
    
    # Save the result
    tester._save_conversation_audio(conversation_id, 1, audio_bytes, ai_response)
    
    print("\n✅ Voice interaction completed successfully!")
    print(f"💾 Audio saved to: conversation_outputs/{conversation_id}/")
    
    return ai_response

async def test_conversation_flow():
    """Test a complete conversation flow"""
    print("\n🎬 Testing Complete Conversation Flow")
    print("=" * 50)
    
    tester = EnhancedVoiceTest()
    
    # Conversation script
    conversation = [
        "Hello, I got a call about my loan payment",
        "I want to know my outstanding amount",
        "What payment options do I have?",
        "Can I pay in installments?",
        "Thank you for your help"
    ]
    
    conversation_id = await tester.simulate_customer_conversation("test_customer_1", conversation)
    
    print(f"\n✅ Conversation completed!")
    print(f"📁 Files saved in: conversation_outputs/{conversation_id}/")
    
    return conversation_id

async def main():
    """Main test function"""
    print("🎙️ Voice Pipeline Direct Testing")
    print("=" * 60)
    print("This tests the actual voice processing pipeline:")
    print("   Customer Speech → STT → Claude → TTS → Audio")
    print("=" * 60)
    
    try:
        # Test 1: Single interaction
        await test_single_interaction()
        
        # Test 2: Complete conversation
        await test_conversation_flow()
        
        print("\n🎯 All tests completed successfully!")
        print("\n📊 What was tested:")
        print("   ✅ Speech-to-Text processing")
        print("   ✅ Claude LLM with collections prompt")
        print("   ✅ Text-to-Speech generation")
        print("   ✅ Multi-turn conversation handling")
        print("   ✅ Audio file generation")
        
        print("\n💡 This demonstrates the same pipeline used in main.py")
        print("   The only difference is main.py handles real audio via WebSocket")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
