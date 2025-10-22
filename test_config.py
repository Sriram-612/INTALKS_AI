"""
Test Configuration for Speech-to-Speech Pipeline
==============================================
Configuration settings and test scenarios for the speech-to-speech pipeline test.
"""

import os
from typing import Dict, List, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Test Customer Data
TEST_CUSTOMER_DATA = {
    "name": "Vijay",
    "phone": "+919384531725",
    "loan_id": "LOAN123456",
    "amount": "15000",
    "due_date": "2024-01-15",
    "state": "Karnataka",
    "language_code": "en-IN"
}

# Collections System Prompt (from agent_config.py)
COLLECTIONS_SYSTEM_PROMPT = """You are a Collections Voice Agent for an Indian lender (SIF).
- Greet, ask for consent, then verify identity before sharing details.
- Be concise (<=2 sentences). Offer payment options and human handoff.
- No threats; be empathetic. Support language: {lang}.
- If user interrupts, pause and let them speak (barge-in friendly)."""

# Test Scenarios for different customer interactions
TEST_SCENARIOS = [
    {
        "name": "Initial Contact",
        "input": "Hello, I received a call about my loan payment",
        "expected_topics": ["greeting", "loan", "payment"],
        "language": "en-IN"
    },
    {
        "name": "Payment Inquiry",
        "input": "I want to know about my outstanding amount",
        "expected_topics": ["outstanding", "amount", "balance"],
        "language": "en-IN"
    },
    {
        "name": "Extension Request",
        "input": "Can I get an extension on my payment?",
        "expected_topics": ["extension", "payment", "options"],
        "language": "en-IN"
    },
    {
        "name": "Financial Difficulty",
        "input": "I'm facing financial difficulties, can you help?",
        "expected_topics": ["help", "financial", "solutions"],
        "language": "en-IN"
    },
    {
        "name": "Payment Options",
        "input": "What are my payment options?",
        "expected_topics": ["payment", "options", "methods"],
        "language": "en-IN"
    },
    {
        "name": "Escalation Request",
        "input": "I want to speak to a manager",
        "expected_topics": ["manager", "escalation", "transfer"],
        "language": "en-IN"
    },
    {
        "name": "Hindi Query",
        "input": "मुझे अपने लोन के बारे में जानकारी चाहिए",
        "expected_topics": ["loan", "information"],
        "language": "hi-IN"
    },
    {
        "name": "Partial Payment",
        "input": "I can pay half amount now, rest next month",
        "expected_topics": ["partial", "payment", "installment"],
        "language": "en-IN"
    },
    {
        "name": "Confusion",
        "input": "I don't understand why you're calling me",
        "expected_topics": ["explanation", "loan", "clarification"],
        "language": "en-IN"
    },
    {
        "name": "Angry Customer",
        "input": "Stop calling me! This is harassment!",
        "expected_topics": ["empathy", "understanding", "solution"],
        "language": "en-IN"
    }
]

# Environment Variables Check
REQUIRED_ENV_VARS = [
    "SARVAM_API_KEY",
    "AWS_ACCESS_KEY_ID", 
    "AWS_SECRET_ACCESS_KEY",
    "CLAUDE_MODEL_ID"
]

# Claude Model Configuration
CLAUDE_CONFIG = {
    "model_id": "arn:aws:bedrock:eu-north-1:844605843483:inference-profile/eu.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "max_tokens": 1000,
    "temperature": 0.7
}

# Sarvam API Configuration
SARVAM_CONFIG = {
    "tts_model": "bulbul:v2",
    "speaker": "anushka",  # Updated speaker
    "sample_rate": 8000,
    "language_codes": [
        "en-IN", "hi-IN", "ta-IN", "te-IN", "kn-IN", 
        "ml-IN", "mr-IN", "bn-IN", "gu-IN", "pa-IN", "or-IN"
    ]
}

# Test Output Configuration
OUTPUT_CONFIG = {
    "save_audio": True,
    "output_directory": "test_outputs",
    "log_level": "INFO",
    "detailed_logging": True
}

def get_test_config() -> Dict[str, Any]:
    """Get complete test configuration"""
    return {
        "customer_data": TEST_CUSTOMER_DATA,
        "system_prompt": COLLECTIONS_SYSTEM_PROMPT,
        "test_scenarios": TEST_SCENARIOS,
        "claude_config": CLAUDE_CONFIG,
        "sarvam_config": SARVAM_CONFIG,
        "output_config": OUTPUT_CONFIG,
        "required_env_vars": REQUIRED_ENV_VARS
    }

def validate_environment() -> tuple[bool, List[str]]:
    """Validate required environment variables"""
    missing_vars = []
    for var in REQUIRED_ENV_VARS:
        if not os.getenv(var):
            missing_vars.append(var)
    
    return len(missing_vars) == 0, missing_vars

def get_enhanced_system_prompt(customer_data: Dict[str, Any], language: str) -> str:
    """Get enhanced system prompt with customer context"""
    base_prompt = COLLECTIONS_SYSTEM_PROMPT.format(lang=language)
    
    enhanced_prompt = f"""{base_prompt}

CUSTOMER CONTEXT:
- Name: {customer_data.get('name', 'Customer')}
- Loan ID: {customer_data.get('loan_id', 'N/A')}
- Outstanding Amount: ₹{customer_data.get('amount', 0)}
- Due Date: {customer_data.get('due_date', 'N/A')}
- Phone: {customer_data.get('phone', 'N/A')}
- State: {customer_data.get('state', 'N/A')}

IMPORTANT GUIDELINES:
- Always be professional and empathetic
- Offer practical payment solutions
- Keep responses concise for voice calls
- Ask for consent before sharing sensitive information
- Provide clear next steps
- If customer is upset, acknowledge their feelings first
- Always offer human agent transfer as an option
"""
    
    return enhanced_prompt
