#!/usr/bin/env python3
"""
Test script to verify the language detection fix for English responses
This tests the specific issue where users saying "yes" in English
were getting Hindi responses due to state-based language override.
"""

import sys
import os

# Add the project directory to the path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

from main import detect_language, get_initial_language_from_state

def test_language_detection_fix():
    """Test the enhanced English detection and conversation flow"""
    
    print("🧪 Testing Language Detection Fixes")
    print("=" * 60)
    
    # Test cases for English detection
    english_test_cases = [
        "yes",
        "yeah",
        "yes I am speaking",
        "okay sure",
        "hello yes",
        "no thank you",
        "sure, that's fine",
        "okay I understand"
    ]
    
    # Test cases for other languages
    other_language_cases = [
        ("हाँ", "hi-IN"),  # Hindi yes
        ("நான் தமிழில் பேசுகிறேன்", "ta-IN"),  # Tamil
        ("नमस्ते", "hi-IN"),  # Hindi hello
        ("வணக்கம்", "ta-IN"),  # Tamil hello
    ]
    
    print("🔍 Testing English Detection:")
    print("-" * 30)
    
    all_english_detected = True
    for text in english_test_cases:
        detected = detect_language(text)
        status = "✅" if detected == "en-IN" else "❌"
        print(f"{status} '{text}' → {detected}")
        if detected != "en-IN":
            all_english_detected = False
    
    print("\n🌐 Testing Other Languages:")
    print("-" * 30)
    
    all_others_correct = True
    for text, expected in other_language_cases:
        detected = detect_language(text)
        status = "✅" if detected == expected else "❌"
        print(f"{status} '{text}' → {detected} (expected: {expected})")
        if detected != expected:
            all_others_correct = False
    
    print("\n🗺️  Testing State-to-Language Mapping:")
    print("-" * 30)
    
    # Test state-based language assignment
    state_tests = [
        ("maharashtra", "mr-IN"),
        ("karnataka", "kn-IN"),
        ("tamil nadu", "ta-IN"),
        ("kerala", "ml-IN"),
        ("unknown_state", "en-IN"),  # Should default to English
        ("", "en-IN"),  # Empty state should default to English
    ]
    
    state_mapping_correct = True
    for state, expected in state_tests:
        detected = get_initial_language_from_state(state)
        status = "✅" if detected == expected else "❌"
        print(f"{status} State: '{state}' → {detected} (expected: {expected})")
        if detected != expected:
            state_mapping_correct = False
    
    print("\n📊 Test Results Summary:")
    print("=" * 60)
    
    if all_english_detected:
        print("✅ English Detection: PASSED - All English words correctly detected")
    else:
        print("❌ English Detection: FAILED - Some English words not detected")
    
    if all_others_correct:
        print("✅ Other Languages: PASSED - Regional languages correctly detected")
    else:
        print("❌ Other Languages: FAILED - Some regional languages incorrectly detected")
    
    if state_mapping_correct:
        print("✅ State Mapping: PASSED - State-to-language mapping working correctly")
    else:
        print("❌ State Mapping: FAILED - State-to-language mapping has issues")
    
    overall_success = all_english_detected and all_others_correct and state_mapping_correct
    
    print("\n🎯 Final Result:")
    if overall_success:
        print("✅ ALL TESTS PASSED - Language detection fix is working correctly!")
        print("   Users saying 'yes' in English will now get English responses.")
    else:
        print("❌ SOME TESTS FAILED - Review the failed cases above.")
    
    return overall_success

if __name__ == "__main__":
    test_language_detection_fix()
