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
        self.api_key = api_key
        self.client = SarvamAI(api_subscription_key=api_key)
        
        # Rate limiting configuration
        self.rate_limit_tracker = {
            'last_call_time': 0,
            'calls_in_window': 0,
            'window_start': 0,
            'backoff_until': 0,
            'consecutive_failures': 0
        }
        
        # Rate limiting settings (adjusted to be less aggressive)
        self.max_calls_per_minute = 20  # More generous limit
        self.min_interval_between_calls = 3.0  # 3 seconds between calls instead of 6
        self.rate_limit_window = 60  # 1 minute window
        self.max_backoff_time = 60  # 1 minute max backoff instead of 5 minutes
        
        # Audio buffering settings (more responsive)
        self.min_audio_duration = 1.0  # Minimum 1 second instead of 2
        self.max_audio_duration = 8.0  # Maximum 8 seconds to prevent memory issues
        self.audio_quality_threshold = 500  # Lower threshold for better sensitivity
        
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
            logger.tts.warning(f"⚠️ Sarvam API rate limit exceeded - returning empty transcript")
            # Don't wait during rate limiting to keep conversation flowing
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
            
            # Call Sarvam REST API with correct method
            with open(wav_path, "rb") as wav_file:
                response = self.client.speech_to_text.transcribe(
                    file=wav_file,
                    model="saarika:v2.5",
                    language_code="unknown"
                )
            
            # Clean up temp file
            os.unlink(wav_path)
            
            # Update rate limit tracker for successful call
            self._update_rate_limit_tracker(True)
            
            transcript = response.transcript.strip() if hasattr(response, 'transcript') else ""
            
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
        """Smart TTS synthesis with translation support"""
        logger.tts.info("🔁 Starting text-to-speech synthesis (with translation)")

        try:
            # Normalize language code to BCP-47 format
            lang_code = self._normalize_language_code(lang)
            
            # Check if translation is needed
            if not self._is_text_in_target_language(text, lang_code):
                logger.tts.info(f"� Text needs translation to {lang_code}")
                try:
                    response = self.client.translate.translate(
                        input=text,
                        source_language_code="en-IN",  # Assume English source
                        target_language_code=lang_code,
                        model="mayura:v1",
                        enable_preprocessing=True
                    )
                    
                    if response and hasattr(response, 'translated_text'):
                        translated_text = response.translated_text
                        logger.tts.info(f"🔤 Translated text: {translated_text}")
                    else:
                        logger.tts.warning("❌ Translation response is empty, using original text")
                        translated_text = text
                        
                except Exception as e:
                    logger.tts.error(f"❌ Translation failed: {e}")
                    logger.tts.info(f"🔤 Using original text: {text}")
                    translated_text = text
            else:
                logger.tts.info(f"✅ Text already in target language ({lang_code})")
                translated_text = text

            logger.tts.info("🎤 Generating TTS audio...")
            
            # Generate TTS with optimized parameters for bulbul:v2
            response = self.client.text_to_speech.convert(
                text=translated_text,
                target_language_code=lang_code,
                model="bulbul:v2",
                speaker="anushka",  # Compatible speaker for bulbul:v2
                pitch=1.0,        # Natural pitch
                pace=1.0,         # Natural speaking pace
                loudness=1.0,     # Natural volume
                speech_sample_rate=8000, # Optimized for telephony (correct parameter name)
                enable_preprocessing=True  # Better handling of mixed content
            )
            
            if not response or not hasattr(response, 'audios') or not response.audios:
                logger.tts.error("❌ No audio data returned from Sarvam TTS")
                return None
                
            audio_data = response.audios[0]
            logger.tts.info(f"✅ Received audio data from Sarvam API (length: {len(audio_data)})")
            
            # Handle base64 encoded audio
            if isinstance(audio_data, str):
                try:
                    audio_bytes = base64.b64decode(audio_data)
                    logger.tts.info(f"🔓 Decoded base64 audio ({len(audio_bytes)} bytes)")
                except Exception as e:
                    logger.tts.error(f"❌ Failed to decode base64 audio: {e}")
                    return None
            else:
                audio_bytes = audio_data
                
            # Step 3: Convert to SLIN format with better error handling
            try:
                logger.tts.info("🎧 Converting audio to SLIN format...")
                
                # Try direct conversion from bytes first (if it's already PCM)
                try:
                    # Check if audio_bytes is already in a usable format
                    if len(audio_bytes) > 0:
                        # Try to load directly from bytes
                        audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
                        logger.tts.info(f"📊 Direct audio loaded: {audio_segment.frame_rate}Hz, {audio_segment.channels}ch, {len(audio_segment)}ms")
                        
                        # Convert to SLIN format (8kHz, mono, 16-bit)
                        slin_audio = audio_segment.set_frame_rate(8000).set_channels(1).set_sample_width(2)
                        final_bytes = slin_audio.raw_data
                        
                        logger.tts.info(f"✅ SLIN audio ready: {len(final_bytes)} bytes, 8kHz mono")
                        return final_bytes
                        
                except Exception as direct_error:
                    logger.tts.info(f"Direct conversion failed, trying temp file method: {direct_error}")
                    
                    # Fallback to temp file method with improved cleanup
                    import tempfile
                    import os
                    import time
                    import gc
                    
                    temp_file_path = None
                    try:
                        # Create temp file
                        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                            temp_file_path = temp_file.name
                            temp_file.write(audio_bytes)
                            temp_file.flush()
                        
                        # Load and convert audio
                        try:
                            audio_segment = AudioSegment.from_file(temp_file_path)
                            logger.tts.info(f"📊 Temp file audio: {audio_segment.frame_rate}Hz, {audio_segment.channels}ch, {len(audio_segment)}ms")
                        except:
                            audio_segment = AudioSegment.from_wav(temp_file_path)
                            logger.tts.info(f"📊 WAV audio loaded: {audio_segment.frame_rate}Hz, {audio_segment.channels}ch, {len(audio_segment)}ms")
                        
                        # Convert to SLIN format
                        slin_audio = audio_segment.set_frame_rate(8000).set_channels(1).set_sample_width(2)
                        final_bytes = slin_audio.raw_data
                        
                        # Explicitly clean up objects
                        del audio_segment
                        del slin_audio
                        gc.collect()  # Force garbage collection
                        
                    finally:
                        # Clean up temp file with retry mechanism
                        if temp_file_path and os.path.exists(temp_file_path):
                            max_retries = 5
                            for attempt in range(max_retries):
                                try:
                                    os.unlink(temp_file_path)
                                    logger.tts.debug(f"✅ Temp file deleted: {temp_file_path}")
                                    break
                                except (PermissionError, OSError) as cleanup_error:
                                    if attempt < max_retries - 1:
                                        time.sleep(0.2)  # Wait 200ms before retry
                                        continue
                                    else:
                                        logger.tts.warning(f"⚠️ Could not delete temp file {temp_file_path} after {max_retries} attempts: {cleanup_error}")
                                        # File will be cleaned up by OS eventually
                
                logger.tts.info(f"✅ SLIN audio ready: {len(final_bytes)} bytes, 8kHz mono")
                return final_bytes
            
            except Exception as e:
                logger.tts.error(f"❌ Audio conversion failed: {e}")
                import traceback
                logger.tts.error(f"❌ Conversion traceback: {traceback.format_exc()}")
                return None

        except Exception as e:
            logger.tts.error(f"❌ TTS generation failed: {e}")
            return None

    def _is_text_in_target_language(self, text: str, lang: str) -> bool:
        """Simple heuristic to check if text is already in target language"""
        # For Hindi/Devanagari languages
        if lang.startswith('hi'):
            return any('\u0900' <= char <= '\u097F' for char in text)
        # For Tamil
        elif lang.startswith('ta'):
            return any('\u0B80' <= char <= '\u0BFF' for char in text)
        # For Telugu
        elif lang.startswith('te'):
            return any('\u0C00' <= char <= '\u0C7F' for char in text)
        # For Kannada
        elif lang.startswith('kn'):
            return any('\u0C80' <= char <= '\u0CFF' for char in text)
        # For Malayalam
        elif lang.startswith('ml'):
            return any('\u0D00' <= char <= '\u0D7F' for char in text)
        # For Gujarati
        elif lang.startswith('gu'):
            return any('\u0A80' <= char <= '\u0AFF' for char in text)
        # For Marathi (uses Devanagari like Hindi)
        elif lang.startswith('mr'):
            return any('\u0900' <= char <= '\u097F' for char in text)
        # For Bengali
        elif lang.startswith('bn'):
            return any('\u0980' <= char <= '\u09FF' for char in text)
        # For Punjabi/Gurmukhi
        elif lang.startswith('pa'):
            return any('\u0A00' <= char <= '\u0A7F' for char in text)
        # For Oriya
        elif lang.startswith('or'):
            return any('\u0B00' <= char <= '\u0B7F' for char in text)
        # Default: assume English text needs translation to non-English languages
        return lang.startswith('en')

    async def synthesize_tts_kushal(self, text: str, lang: str) -> bytes:
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
            
            # Use synchronous client with correct method call
            response = self.client.text_to_speech.convert(
                text=text,
                target_language_code=normalized_lang,
                speaker="anushka",  # Compatible speaker for bulbul:v2
                model="bulbul:v2",
                enable_preprocessing=True
            )
            
            # Update rate limit tracker for successful call
            self._update_rate_limit_tracker(True)
            
            if hasattr(response, 'audios') and response.audios:
                # Get base64 audio data
                audio_base64 = response.audios[0]
                
                # Decode base64 to get audio bytes
                audio_bytes = base64.b64decode(audio_base64)
                
                logger.tts.info(f"🎵 Received audio: {len(audio_bytes)} bytes, first 16 bytes: {audio_bytes[:16].hex()}")
                
                # Check if it's already raw PCM or if it's MP3/WAV
                if audio_bytes.startswith(b'ID3') or audio_bytes.startswith(b'\xff\xfb'):
                    # It's MP3 format, convert to PCM
                    try:
                        audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
                        slin_audio = audio_segment.set_frame_rate(8000).set_channels(1).set_sample_width(2)
                        raw_pcm = slin_audio.raw_data
                        logger.tts.info(f"✅ MP3 converted to PCM: {len(raw_pcm)} bytes")
                        return raw_pcm
                    except Exception as audio_error:
                        logger.tts.error(f"❌ MP3 conversion error: {audio_error}")
                        # Try returning raw bytes as PCM
                        logger.tts.info("🔄 Attempting to use raw bytes as PCM")
                        return audio_bytes
                        
                elif audio_bytes.startswith(b'RIFF'):
                    # It's WAV format, convert to PCM
                    try:
                        audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
                        slin_audio = audio_segment.set_frame_rate(8000).set_channels(1).set_sample_width(2)
                        raw_pcm = slin_audio.raw_data
                        logger.tts.info(f"✅ WAV converted to PCM: {len(raw_pcm)} bytes")
                        return raw_pcm
                    except Exception as audio_error:
                        logger.tts.error(f"❌ WAV conversion error: {audio_error}")
                        return audio_bytes
                        
                else:
                    # Assume it's already raw PCM for telephony
                    logger.tts.info(f"✅ Using raw PCM data: {len(audio_bytes)} bytes")
                    return audio_bytes
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

    def _transcribe_audio(self, wav_path: str, language_code: str) -> Any:
        """Helper to invoke Sarvam STT with the desired language code."""
        with open(wav_path, "rb") as wav_file:
            return self.client.speech_to_text.transcribe(
                file=wav_file,
                model="saarika:v2.5",
                language_code=language_code
            )

    @staticmethod
    def _looks_like_english(text: str) -> bool:
        """Heuristic to decide if transcript is predominantly English (Latin script)."""
        if not text:
            return False
        total_letters = sum(1 for ch in text if ch.isalpha())
        if total_letters == 0:
            return False
        latin_letters = sum(1 for ch in text if ch.isalpha() and ch.isascii())
        return (latin_letters / total_letters) >= 0.6

    async def transcribe_from_payload(self, audio_buffer: bytes) -> str:
        logger.tts.info("🎙️ Converting SLIN base64 to WAV")

        # Convert SLIN (raw 8kHz PCM mono) to WAV
        audio = AudioSegment(
            data=audio_buffer,
            sample_width=2,  # 16-bit PCM
            frame_rate=8000,
            channels=1
        )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            audio.export(f.name, format="wav")
            wav_path = f.name

        english_transcript = ""
        fallback_transcript = ""
        fallback_language = None

        try:
            logger.tts.info("🚀 Sending WAV to Sarvam API (forced English)")
            english_response = self._transcribe_audio(wav_path, "en-IN")
            english_transcript = (english_response.transcript or "").strip()
            logger.tts.info(f"📝 English transcript candidate: '{english_transcript}'")

            if english_transcript:
                detected_lang = await self.detect_language_from_text(english_transcript)
            else:
                detected_lang = "en-IN"

            if self._looks_like_english(english_transcript) and detected_lang.startswith("en"):
                logger.tts.info("✅ English transcript selected based on heuristic and language detection")
                return english_transcript

            logger.tts.info(
                f"ℹ️ English transcript not dominant (lang_detected={detected_lang}); retrying with auto language detection"
            )
            fallback_response = self._transcribe_audio(wav_path, "unknown")
            fallback_transcript = (fallback_response.transcript or "").strip()
            fallback_language = getattr(fallback_response, "language_code", None)
            logger.tts.info(
                f"📝 Fallback transcript: '{fallback_transcript}' (lang={fallback_language})"
            )

            if fallback_transcript:
                return fallback_transcript

            return english_transcript
        finally:
            try:
                os.unlink(wav_path)
            except OSError as cleanup_err:
                logger.tts.warning(f"⚠️ Failed to delete temp wav file {wav_path}: {cleanup_err}")

    # Additional legacy TTS methods for compatibility
    async def synthesize_tts_direct(self, text: str, lang: str) -> bytes:
        """Legacy method - redirect to synthesize_tts"""
        return await self.synthesize_tts(text, lang)

    async def synthesize_tts_end(self, text: str, lang: str) -> bytes:
        """Legacy method - redirect to synthesize_tts"""
        return await self.synthesize_tts(text, lang)
