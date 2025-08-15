#!/usr/bin/env python3
"""
Production-Ready Rate Limiting and Audio Processing Handler
Implements comprehensive rate limiting, fallback mechanisms, and language detection
"""
import asyncio
import time
import base64
import tempfile
import io
import os
import json
import httpx
from typing import Optional, Dict, Any, Tuple
from pydub import AudioSegment
from sarvamai import SarvamAI
from sarvamai import AsyncSarvamAI, AudioOutput
from fastapi import Body
from .logger import logger


class ProductionSarvamHandler:
    def __init__(self, api_key):
        self.client = SarvamAI(api_subscription_key=api_key)
        self.api_key = api_key
        
        # Rate limiting configuration
        self.rate_limit_tracker = {
            'last_call_time': 0,
            'calls_in_window': 0,
            'window_start': 0,
            'backoff_until': 0,
            'consecutive_failures': 0
        }
        
        # Rate limiting settings (adjust based on your Sarvam subscription)
        self.max_calls_per_minute = 10  # Conservative limit
        self.min_interval_between_calls = 6.0  # 6 seconds between calls
        self.rate_limit_window = 60  # 1 minute window
        self.max_backoff_time = 300  # 5 minutes max backoff
        
        # Audio buffering settings
        self.min_audio_duration = 2.0  # Minimum 2 seconds of audio before transcription
        self.max_audio_duration = 8.0  # Maximum 8 seconds to prevent memory issues
        self.audio_quality_threshold = 1000  # Minimum audio bytes for quality check
        
        # Language code mapping for proper BCP-47 format
        self.language_map = {
            'en': 'en-IN',
            'hi': 'hi-IN', 
            'bn': 'bn-IN',
            'ta': 'ta-IN',
            'te': 'te-IN',
            'gu': 'gu-IN',
            'kn': 'kn-IN',
            'ml': 'ml-IN',
            'mr': 'mr-IN',
            'or': 'od-IN',
            'pa': 'pa-IN'
        }

    def _normalize_language_code(self, lang: str) -> str:
        """Normalize language code to proper BCP-47 format"""
        if not lang or lang in ["auto", "unknown", ""]:
            return 'en-IN'
        
        # If already in proper format, return as is
        if '-' in lang and len(lang) == 5:
            return lang
        
        # Map short codes to full codes
        return self.language_map.get(lang.lower(), 'en-IN')

    def _check_rate_limit(self) -> Tuple[bool, float]:
        """Check if we can make an API call based on rate limiting"""
        current_time = time.time()
        
        # Check if we're in backoff period
        if current_time < self.rate_limit_tracker['backoff_until']:
            wait_time = self.rate_limit_tracker['backoff_until'] - current_time
            logger.tts.warning(f"🚫 In backoff period, waiting {wait_time:.1f}s")
            return False, wait_time
        
        # Check minimum interval between calls
        time_since_last = current_time - self.rate_limit_tracker['last_call_time']
        if time_since_last < self.min_interval_between_calls:
            wait_time = self.min_interval_between_calls - time_since_last
            logger.tts.info(f"⏱️ Rate limit: waiting {wait_time:.1f}s")
            return False, wait_time
        
        # Check calls per minute window
        if current_time - self.rate_limit_tracker['window_start'] >= self.rate_limit_window:
            # Reset window
            self.rate_limit_tracker['window_start'] = current_time
            self.rate_limit_tracker['calls_in_window'] = 0
        
        if self.rate_limit_tracker['calls_in_window'] >= self.max_calls_per_minute:
            wait_time = self.rate_limit_window - (current_time - self.rate_limit_tracker['window_start'])
            logger.tts.warning(f"📊 Rate limit exceeded: waiting {wait_time:.1f}s")
            return False, wait_time
        
        return True, 0

    def _update_rate_limit_tracker(self, success: bool):
        """Update rate limiting tracker after API call"""
        current_time = time.time()
        self.rate_limit_tracker['last_call_time'] = current_time
        self.rate_limit_tracker['calls_in_window'] += 1
        
        if success:
            self.rate_limit_tracker['consecutive_failures'] = 0
        else:
            self.rate_limit_tracker['consecutive_failures'] += 1
            # Exponential backoff on failures
            backoff_time = min(
                2 ** self.rate_limit_tracker['consecutive_failures'], 
                self.max_backoff_time
            )
            self.rate_limit_tracker['backoff_until'] = current_time + backoff_time
            logger.tts.error(f"🚫 API failure #{self.rate_limit_tracker['consecutive_failures']}, backing off for {backoff_time}s")

    def _estimate_audio_duration(self, audio_bytes: bytes) -> float:
        """Estimate audio duration from raw audio bytes"""
        # For 8kHz, 16-bit mono: 2 bytes per sample, 8000 samples per second
        samples = len(audio_bytes) / 2
        duration = samples / 8000
        return duration

    def _is_audio_quality_sufficient(self, audio_bytes: bytes) -> bool:
        """Check if audio has sufficient quality for transcription"""
        if len(audio_bytes) < self.audio_quality_threshold:
            return False
        
        # Basic silence detection - check if audio has some variation
        if len(set(audio_bytes[:100])) < 5:  # Too uniform, likely silence
            return False
        
        return True

    async def detect_language_from_text(self, text: str) -> str:
        """
        Use Sarvam text-lid API to detect language from transcript
        """
        if not text or len(text.strip()) < 3:
            return "en-IN"  # Default fallback
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.sarvam.ai/text-lid",
                    headers={
                        "api-subscription-key": self.api_key,
                        "Content-Type": "application/json"
                    },
                    json={"input": text[:1000]},  # Max 1000 chars as per API
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    detected_lang = result.get('language_code', 'en-IN')
                    script = result.get('script_code', 'Latn')
                    
                    # Additional validation - ensure valid language code
                    if not detected_lang or detected_lang == "auto" or detected_lang == "unknown":
                        detected_lang = "en-IN"
                        logger.tts.info("🔤 Invalid language detected, defaulting to English")
                    
                    logger.tts.info(f"🌐 Language detected: {detected_lang} (script: {script})")
                    return detected_lang
                else:
                    logger.tts.warning(f"⚠️ Language detection failed: {response.status_code}")
                    return "en-IN"
                    
        except Exception as e:
            logger.tts.error(f"❌ Language detection error: {e}")
            return "en-IN"

    async def transcribe_with_fallback(self, audio_buffer: bytes, customer_language: str = None) -> tuple[str, str]:
        """
        Enhanced transcription with rate limiting, fallback, and language detection
        Returns: (transcript, detected_language)
        """
        # Check audio quality first
        if not self._is_audio_quality_sufficient(audio_buffer):
            logger.tts.warning("🔇 Audio quality insufficient for transcription")
            return "", customer_language or "en-IN"
        
        # Check audio duration
        duration = self._estimate_audio_duration(audio_buffer)
        if duration < self.min_audio_duration:
            logger.tts.info(f"⏱️ Audio too short ({duration:.1f}s), skipping transcription")
            return "", customer_language or "en-IN"
        
        # Check rate limits
        can_call, wait_time = self._check_rate_limit()
        if not can_call:
            logger.tts.warning("⚠️ Sarvam API rate limit exceeded - returning empty transcript")
            return "", customer_language or "en-IN"
        
        try:
            logger.tts.info("🎙️ Converting SLIN base64 to WAV")
            
            # Convert SLIN (raw 8kHz PCM mono) to WAV
            audio = AudioSegment(
                data=audio_buffer,
                sample_width=2,
                frame_rate=8000,
                channels=1
            )
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = f.name
                audio.export(wav_path, format="wav")
            
            logger.tts.info("🚀 Sending WAV to Sarvam API")
            
            # Call Sarvam REST API
            with open(wav_path, "rb") as wav_file:
                response = self.client.speech_to_text(
                    wav_file, 
                    model="saaras:v1"
                )
            
            # Clean up temp file
            os.unlink(wav_path)
            
            # Update rate limit tracker for successful call
            self._update_rate_limit_tracker(True)
            
            transcript = response.get("transcript", "").strip()
            
            if transcript:
                # Detect language from transcript using Sarvam text-lid
                detected_language = await self.detect_language_from_text(transcript)
                logger.tts.info(f"✅ Transcription successful: '{transcript}' (lang: {detected_language})")
                return transcript, detected_language
            else:
                logger.tts.warning("⚠️ Empty transcription received")
                return "", customer_language or "en-IN"
            
        except Exception as e:
            # Update rate limit tracker for failed call
            self._update_rate_limit_tracker(False)
            logger.tts.error(f"❌ Transcription error: {e}")
            
            # Fallback to customer's preferred language
            fallback_lang = customer_language or "en-IN"
            return "", fallback_lang

    async def synthesize_tts(self, text: str, lang: str) -> bytes:
        """
        Enhanced TTS synthesis with rate limiting and error handling
        """
        if not text or not text.strip():
            logger.tts.warning("⚠️ Empty text provided for TTS")
            return b""
        
        # Normalize language code
        normalized_lang = self._normalize_language_code(lang)
        
        # Check rate limits
        can_call, wait_time = self._check_rate_limit()
        if not can_call:
            logger.tts.warning(f"⚠️ TTS rate limit exceeded - waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
        
        try:
            logger.tts.info(f"🔁 Starting TTS synthesis for: '{text[:50]}...' in {normalized_lang}")
            
            response = self.client.text_to_speech(
                inputs=[text],
                target_language_code=normalized_lang,
                speaker="meera",
                model="bulbul:v1",
                enable_preprocessing=True
            )
            
            # Update rate limit tracker for successful call
            self._update_rate_limit_tracker(True)
            
            if hasattr(response, 'audios') and response.audios:
                audio_data = response.audios[0]
                logger.tts.info(f"✅ TTS synthesis successful ({len(audio_data)} bytes)")
                return audio_data
            else:
                logger.tts.error("❌ No audio data in TTS response")
                return b""
                
        except Exception as e:
            # Update rate limit tracker for failed call
            self._update_rate_limit_tracker(False)
            logger.tts.error(f"❌ TTS synthesis error: {e}")
            return b""

    def _slin_to_wav_file(self, slin_bytes) -> str:
        """Convert SLIN bytes to WAV file (legacy compatibility)"""
        audio = AudioSegment(
            slin_bytes,
            sample_width=2,
            frame_rate=8000,
            channels=1
        )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
            audio.export(wav_path, format="wav")
        return wav_path

    # Legacy method for backward compatibility
    def transcribe_from_payload(self, audio_buffer: bytes) -> str:
        """Legacy method - use transcribe_with_fallback instead"""
        logger.tts.warning("⚠️ Using legacy transcribe_from_payload - consider upgrading to transcribe_with_fallback")
        # Use sync version of the async method
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            transcript, _ = loop.run_until_complete(self.transcribe_with_fallback(audio_buffer))
            return transcript
        finally:
            loop.close()

    # Additional legacy TTS methods for compatibility
    async def synthesize_tts_direct(self, text: str, lang: str) -> bytes:
        """Legacy method - redirect to synthesize_tts"""
        return await self.synthesize_tts(text, lang)

    async def synthesize_tts_end(self, text: str, lang: str) -> bytes:
        """Legacy method - redirect to synthesize_tts"""
        return await self.synthesize_tts(text, lang)
