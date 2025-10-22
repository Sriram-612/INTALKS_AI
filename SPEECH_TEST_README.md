# Speech-to-Speech Pipeline Testing

This directory contains comprehensive test files for the complete speech-to-speech pipeline: **Speech → Sarvam STT → Claude LLM → Sarvam TTS → Audio Output**.

## Files Created

### 1. `test_speech_to_speech_pipeline.py`
Main test file that implements the complete pipeline testing framework.

**Features:**
- Complete pipeline testing (STT → Claude → TTS)
- Interactive testing mode
- Predefined test scenarios
- Audio output generation and saving
- Comprehensive error handling and logging
- Multi-language support

### 2. `test_config.py`
Configuration file containing test scenarios, customer data, and system prompts.

**Contains:**
- Test customer data
- Collections system prompt (from agent_config.py)
- Predefined test scenarios
- Environment validation
- Claude and Sarvam configurations

### 3. `run_speech_test.py`
Simple runner script for quick testing.

**Usage modes:**
- Default: Run all predefined tests
- Interactive: Chat-like testing
- Single test: Test one specific input
- Quick test: Run first 3 scenarios only

## Prerequisites

### Environment Variables
The test files automatically load environment variables from your `.env` file. Ensure your `.env` file contains:

```bash
SARVAM_API_KEY=your_sarvam_api_key
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
CLAUDE_MODEL_ID=arn:aws:bedrock:eu-north-1:844605843483:inference-profile/eu.anthropic.claude-3-7-sonnet-20250219-v1:0
```

**Note**: The test files use `python-dotenv` to automatically load these variables, so you don't need to manually export them.

### Python Dependencies
Ensure you have all required dependencies installed:
- `boto3` (for AWS Bedrock)
- `sarvamai` (for Sarvam API)
- `python-dotenv` (for loading .env file)
- `asyncio` (for async operations)

Install missing dependencies:
```bash
pip install python-dotenv boto3 sarvamai
```

## How to Run Tests

### 1. Quick Test (Recommended for first run)
```bash
python run_speech_test.py --quick
```

### 2. Full Test Suite
```bash
python run_speech_test.py
```

### 3. Interactive Testing
```bash
python run_speech_test.py --interactive
```

### 4. Single Test
```bash
python run_speech_test.py --single "Hello, I need help with my loan payment"
```

### 5. Direct Pipeline Test
```bash
python test_speech_to_speech_pipeline.py
```

## Pipeline Flow

The test demonstrates this complete flow:

```
Customer Input Text
        ↓
🎤 Simulate Audio (Text → Audio via Sarvam TTS)
        ↓
📝 Speech-to-Text (Sarvam STT)
        ↓
🤖 Claude LLM Processing (with Collections Prompt)
        ↓
🔊 Text-to-Speech (Sarvam TTS)
        ↓
💾 Audio Output (Saved to test_outputs/)
```

## Test Scenarios

The test includes various customer interaction scenarios:

1. **Initial Contact**: "Hello, I received a call about my loan payment"
2. **Payment Inquiry**: "I want to know about my outstanding amount"
3. **Extension Request**: "Can I get an extension on my payment?"
4. **Financial Difficulty**: "I'm facing financial difficulties, can you help?"
5. **Payment Options**: "What are my payment options?"
6. **Escalation**: "I want to speak to a manager"
7. **Hindi Query**: "मुझे अपने लोन के बारे में जानकारी चाहिए"
8. **Partial Payment**: "I can pay half amount now, rest next month"
9. **Confusion**: "I don't understand why you're calling me"
10. **Angry Customer**: "Stop calling me! This is harassment!"

## Output

### Console Output
- Real-time pipeline progress
- Transcript results
- Claude responses
- Success/failure status
- Error details (if any)

### Audio Files
Generated audio files are saved in `test_outputs/` directory:
- `response_[timestamp].raw` - Raw audio data
- SLIN format (8kHz, 16-bit, mono)

### Example Output
```
🎯 Running Complete Pipeline for: 'Hello, I need help with my loan payment'
============================================================
🎤 Simulating customer speech: 'Hello, I need help with my loan payment'
✅ Generated 45632 bytes of simulated customer audio
🔄 Step 1: Converting speech to text...
📝 Transcript: 'Hello, I need help with my loan payment'
🤖 Step 2: Processing with Claude LLM...
🔮 Invoking Claude model: arn:aws:bedrock:eu-north-1:...
💬 Claude Response: 'Hello Rajesh! I understand you need help with your loan payment for LOAN123456. I can offer you flexible payment options including partial payments or extensions. Would you like me to explain the available options, or would you prefer to speak with a human agent?'
🔊 Step 3: Converting response to speech...
✅ Generated 67890 bytes of response audio
💾 Audio saved to: test_outputs/response_1703123456.raw
✅ Pipeline completed successfully!
```

## Troubleshooting

### Common Issues

1. **Missing Environment Variables**
   - Ensure all required env vars are set
   - Check AWS credentials and region

2. **Sarvam API Issues**
   - Verify API key is valid
   - Check rate limits

3. **Claude/Bedrock Issues**
   - Verify AWS credentials
   - Check model ID and region
   - Ensure Bedrock access is enabled

4. **Audio Issues**
   - Check if `test_outputs/` directory is created
   - Verify audio file permissions

### Debug Mode
For detailed debugging, modify the logger level in the test files or add print statements.

## Customization

### Adding New Test Scenarios
Edit `test_config.py` and add new scenarios to `TEST_SCENARIOS` list.

### Changing Customer Data
Modify `TEST_CUSTOMER_DATA` in `test_config.py`.

### Updating System Prompt
Edit `COLLECTIONS_SYSTEM_PROMPT` in `test_config.py` or `get_enhanced_system_prompt()` function.

## Integration with Main System

These test files use the same components as your main voice bot:
- `utils/production_asr.py` (Sarvam handler)
- `utils/bedrock_client.py` (Claude integration)
- Same environment variables and configurations

This ensures the test results accurately reflect how the pipeline will work in your production system.

## Next Steps

1. Run the tests to verify the pipeline works
2. Check the generated audio files
3. Review Claude responses for quality
4. Adjust system prompts if needed
5. Test with different languages
6. Integrate successful pipeline into main voice bot system
