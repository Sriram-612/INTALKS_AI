#!/usr/bin/env python3
"""
Enhanced Language Detection System
Combines multiple detection strategies for robust language identification
"""
import re
import unicodedata
from typing import Optional, Dict, Any, List, Tuple
from .logger import logger


class EnhancedLanguageDetector:
    def __init__(self):
        # Language patterns for common phrases in Indian languages
        self.language_patterns = {
            'hi-IN': [
                r'\b(?:हाँ|हां|नहीं|नमस्ते|धन्यवाद|कैसे|क्या|मैं|आप|हूं|है|में|से|को|का|की|के|और|या|लेकिन)\b',
                r'\b(?:namaste|namaskar|dhanyawad|kaise|kya|main|aap|hun|hai|mein|se|ko|ka|ki|ke|aur|ya|lekin)\b'
            ],
            'ta-IN': [
                r'\b(?:ஆம்|இல்லை|வணக்கம்|நன்றி|எப்படி|என்ன|நான்|நீங்கள்|இருக்கிறேன்|இருக்கிறது|இல்|से|को|का|की|के|மற்றும்|அல்லது|ஆனால்)\b',
                r'\b(?:vanakkam|nandri|eppadi|enna|naan|neenga|irukiren|irukkirathu|il|mattrum|allatu|aanaal)\b'
            ],
            'te-IN': [
                r'\b(?:అవును|లేదు|నమస్కారం|ధన్యవాదాలు|ఎలా|ఏమిటి|నేను|మీరు|ఉన్నాను|ఉంది|లో|నుండి|కు|యొక్క|మరియు|లేదా|కానీ)\b',
                r'\b(?:avunu|ledhu|namaskaram|dhanyavadalu|ela|emiti|nenu|meeru|unnanu|undi|lo|nundi|ku|yokka|mariyu|leda|kaani)\b'
            ],
            'bn-IN': [
                r'\b(?:হ্যাঁ|না|নমস্কার|ধন্যবাদ|কেমন|কি|আমি|আপনি|আছি|আছে|মধ্যে|থেকে|কে|এর|এবং|বা|কিন্তু)\b',
                r'\b(?:hyan|na|namaskar|dhonnobad|kemon|ki|ami|apni|achhi|achhe|moddhe|theke|ke|er|ebong|ba|kintu)\b'
            ],
            'gu-IN': [
                r'\b(?:હા|ના|નમસ્તે|આભાર|કેમ|શું|હું|તમે|છું|છે|માં|થી|ને|નું|અને|કે|પણ)\b',
                r'\b(?:ha|na|namaste|abhar|kem|shu|hu|tame|chu|chhe|ma|thi|ne|nu|ane|ke|pan)\b'
            ],
            'kn-IN': [
                r'\b(?:ಹೌದು|ಇಲ್ಲ|ನಮಸ್ಕಾರ|ಧನ್ಯವಾದ|ಹೇಗೆ|ಏನು|ನಾನು|ನೀವು|ಇದ್ದೇನೆ|ಇದೆ|ನಲ್ಲಿ|ಇಂದ|ಗೆ|ಅಂತೆ|ಮತ್ತು|ಅಥವಾ|ಆದರೆ)\b',
                r'\b(?:haudu|illa|namaskara|dhanyavada|hege|enu|naanu|neevu|iddene|ide|nalli|inda|ge|ante|mattu|athava|adare)\b'
            ],
            'ml-IN': [
                r'\b(?:അതെ|ഇല്ല|നമസ്കാരം|നന്ദി|എങ്ങനെ|എന്ത്|ഞാൻ|നിങ്ങൾ|ഉണ്ട്|ആണ്|ൽ|ൽ നിന്ന്|ക്ക്|ന്റെ|ഉം|ഓ|പക്ഷേ)\b',
                r'\b(?:athe|illa|namaskaram|nandi|engane|enthu|njan|ningal|undu|aan|il|ninnu|kku|nte|um|o|pakshe)\b'
            ],
            'mr-IN': [
                r'\b(?:होय|नाही|नमस्कार|धन्यवाद|कसे|काय|मी|तुम्ही|आहे|आहेत|मध्ये|पासून|ला|चा|आणि|किंवा|पण)\b',
                r'\b(?:hoy|nahi|namaskar|dhanyawad|kase|kay|mi|tumhi|aahe|aaheto|madhye|pasun|la|cha|ani|kinva|pan)\b'
            ],
            'pa-IN': [
                r'\b(?:ਹਾਂ|ਨਹੀਂ|ਸਤ ਸ੍ਰੀ ਅਕਾਲ|ਧੰਨਵਾਦ|ਕਿਵੇਂ|ਕੀ|ਮੈਂ|ਤੁਸੀਂ|ਹਾਂ|ਹੈ|ਵਿੱਚ|ਤੋਂ|ਨੂੰ|ਦਾ|ਅਤੇ|ਜਾਂ|ਪਰ)\b',
                r'\b(?:han|nahin|sat sri akal|dhannawad|kiven|ki|main|tusin|han|hai|vich|ton|nu|da|ate|ja|par)\b'
            ],
            'od-IN': [
                r'\b(?:ହଁ|ନା|ନମସ୍କାର|ଧନ୍ୟବାଦ|କେମିତି|କଣ|ମୁଁ|ଆପଣ|ଅଛି|ଅଛେ|ରେ|ରୁ|କୁ|ର|ଏବଂ|କିମ୍ବା|କିନ୍ତୁ)\b',
                r'\b(?:han|na|namaskar|dhanyabad|kemiti|kana|mun|apana|achhi|achhe|re|ru|ku|ra|ebam|kimba|kintu)\b'
            ],
            'en-IN': [
                r'\b(?:yes|no|hello|hi|thank|thanks|how|what|i|you|am|is|are|in|from|to|of|and|or|but|okay|ok|sure|fine)\b'
            ]
        }
        
        # Unicode script detection
        self.script_to_language = {
            'Deva': ['hi-IN', 'mr-IN'],  # Devanagari
            'Taml': ['ta-IN'],           # Tamil
            'Telu': ['te-IN'],           # Telugu
            'Beng': ['bn-IN'],           # Bengali
            'Gujr': ['gu-IN'],           # Gujarati
            'Knda': ['kn-IN'],           # Kannada
            'Mlym': ['ml-IN'],           # Malayalam
            'Guru': ['pa-IN'],           # Gurmukhi
            'Orya': ['od-IN'],           # Odia
            'Latn': ['en-IN']            # Latin (English/Romanized)
        }
        
        # Common transliterations
        self.transliteration_patterns = {
            'hi-IN': [
                'namaste', 'namaskar', 'kaise', 'kya', 'main', 'aap', 'haan', 'nahin',
                'dhanyawad', 'accha', 'theek', 'bilkul', 'zaroor'
            ],
            'ta-IN': [
                'vanakkam', 'nandri', 'eppadi', 'enna', 'naan', 'neenga', 'sari',
                'illa', 'aam', 'kandippa'
            ],
            'te-IN': [
                'namaskaram', 'dhanyavadalu', 'ela', 'emiti', 'nenu', 'meeru',
                'avunu', 'ledhu', 'sare', 'tappakunda'
            ]
        }

    def detect_unicode_script(self, text: str) -> List[str]:
        """Detect Unicode scripts present in text"""
        scripts = set()
        for char in text:
            script = unicodedata.name(char, '').split(' ')[0] if unicodedata.name(char, '') else ''
            if script in self.script_to_language:
                scripts.add(script)
        return list(scripts)

    def detect_by_patterns(self, text: str) -> Dict[str, int]:
        """Detect language using regex patterns"""
        scores = {}
        text_lower = text.lower()
        
        for lang_code, patterns in self.language_patterns.items():
            score = 0
            for pattern in patterns:
                matches = re.findall(pattern, text_lower, re.IGNORECASE)
                score += len(matches)
            scores[lang_code] = score
        
        return scores

    def detect_by_transliteration(self, text: str) -> Dict[str, int]:
        """Detect language using transliteration patterns"""
        scores = {}
        text_lower = text.lower()
        
        for lang_code, words in self.transliteration_patterns.items():
            score = 0
            for word in words:
                if word in text_lower:
                    score += 1
            scores[lang_code] = score
        
        return scores

    def get_customer_language_preference(self, customer_info: Dict[str, Any]) -> Optional[str]:
        """Get language preference from customer data"""
        if not customer_info:
            return None
        
        # Check various possible fields for language info
        lang_fields = ['lang', 'language', 'language_code', 'preferred_language']
        for field in lang_fields:
            if field in customer_info and customer_info[field]:
                return customer_info[field]
        
        return None

    def detect_language_enhanced(self, text: str, customer_info: Dict[str, Any] = None) -> str:
        """
        Enhanced language detection with multiple fallback strategies
        """
        if not text or len(text.strip()) < 2:
            # Fallback to customer preference or default
            customer_lang = self.get_customer_language_preference(customer_info)
            return customer_lang or "en-IN"
        
        text = text.strip()
        logger.websocket.info(f"🔍 Detecting language for: '{text[:50]}...'")
        
        # Strategy 1: Unicode script detection
        scripts = self.detect_unicode_script(text)
        script_candidates = []
        for script in scripts:
            if script in self.script_to_language:
                script_candidates.extend(self.script_to_language[script])
        
        # Strategy 2: Pattern matching
        pattern_scores = self.detect_by_patterns(text)
        
        # Strategy 3: Transliteration detection
        transliteration_scores = self.detect_by_transliteration(text)
        
        # Combine scores
        combined_scores = {}
        all_languages = set(pattern_scores.keys()) | set(transliteration_scores.keys()) | set(script_candidates)
        
        for lang in all_languages:
            score = 0
            
            # Script bonus
            if lang in script_candidates:
                score += 10
            
            # Pattern score
            score += pattern_scores.get(lang, 0) * 3
            
            # Transliteration score
            score += transliteration_scores.get(lang, 0) * 2
            
            combined_scores[lang] = score
        
        # Find best match
        if combined_scores:
            best_lang = max(combined_scores, key=combined_scores.get)
            best_score = combined_scores[best_lang]
            
            if best_score > 0:
                logger.websocket.info(f"🎯 Language detected: {best_lang} (score: {best_score})")
                return best_lang
        
        # Fallback chain
        # 1. Customer preference
        customer_lang = self.get_customer_language_preference(customer_info)
        if customer_lang:
            logger.websocket.info(f"📋 Using customer language preference: {customer_lang}")
            return customer_lang
        
        # 2. Default to English
        logger.websocket.info("🔤 Defaulting to English (en-IN)")
        return "en-IN"


# Global instance
enhanced_language_detector = EnhancedLanguageDetector()

# Convenience function
def detect_language_enhanced(text: str, customer_info: Dict[str, Any] = None) -> str:
    """Convenience function for enhanced language detection"""
    return enhanced_language_detector.detect_language_enhanced(text, customer_info)
