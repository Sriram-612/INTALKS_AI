# EC2 Deployment Guide - Voice Assistant Bot

## 🎯 Quick Diagnosis & Fix for "Bot Skipping Conversation" Issue

### Problem
Bot is working fine locally but on EC2 it skips Claude/Sarvam conversation and immediately asks "tell me your problem why you call" then transfers to agent.

### Root Cause
- Empty/failed ASR transcriptions from Sarvam API
- Hard-coded AWS region mismatch (Bedrock in eu-north-1 vs EC2 in ap-south-1)
- Missing retry logic for API failures
- Environment variables not configured on EC2

---

## 📋 Pre-Deployment Checklist

### 1. Files Modified (Already Done)
- ✅ `utils/handler_asr.py` - Added retry logic for Sarvam transcriptions
- ✅ `utils/bedrock_client.py` - Made region configurable, added error handling
- ✅ `services/call_management.py` - Fixed file upload imports

### 2. Required Environment Variables
```bash
# AWS Configuration
AWS_REGION=eu-north-1                    # Or ap-south-1 based on your EC2 location
BEDROCK_REGION=eu-north-1                # Where Bedrock is deployed
CLAUDE_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0

# Sarvam AI
SARVAM_API_KEY=your_sarvam_api_key_here

# Exotel
EXOTEL_SID=your_exotel_sid
EXOTEL_TOKEN=your_exotel_token
EXOTEL_API_KEY=your_exotel_api_key
EXOTEL_SUBDOMAIN=api.exotel.com

# Cognito
COGNITO_REGION=ap-south-1
COGNITO_USER_POOL_ID=your_user_pool_id
COGNITO_CLIENT_ID=your_client_id

# Database
DATABASE_URL=postgresql://user:password@db-voice-agent.cviea4aicss0.ap-south-1.rds.amazonaws.com:5432/voiceagent

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Logging
LOG_LEVEL=DEBUG
```

---

## 🚀 Step-by-Step Deployment

### Step 1: Connect to EC2
```bash
ssh -i your-key.pem ubuntu@your-ec2-ip
```

### Step 2: Navigate to Project Directory
```bash
cd /path/to/voice-deployment/voice-localenv
# Or wherever your project is deployed on EC2
```

### Step 3: Run Diagnostic Test
```bash
# Make diagnostic script executable
chmod +x ../ec2_diagnostic.py

# Run diagnostics
python3 ../ec2_diagnostic.py
```

**Expected Output:**
```
📊 Tests Passed: 7/7
✅ PASS  Env Vars
✅ PASS  System Deps
✅ PASS  Python Packages
✅ PASS  Sarvam
✅ PASS  Bedrock
✅ PASS  Cognito
✅ PASS  Database

🎉 All tests passed! Your EC2 environment is properly configured.
```

**If Tests Fail:** Follow the recommendations in the diagnostic output before proceeding.

---

### Step 4: Backup Current Code (Safety First)
```bash
# Create backup of current deployment
cp -r . ../voice-backup-$(date +%Y%m%d-%H%M%S)

# Or commit current state
git add .
git commit -m "Backup before production fixes"
```

### Step 5: Pull Updated Code
```bash
# If using git
git pull origin main

# Or manually copy the modified files:
# - utils/handler_asr.py
# - utils/bedrock_client.py
# - services/call_management.py
```

### Step 6: Verify Environment Variables
```bash
# Check if .env file exists
ls -la .env

# If .env exists, verify it has all required variables
nano .env

# Add/update these critical variables:
# BEDROCK_REGION=eu-north-1
# AWS_REGION=eu-north-1  # Or ap-south-1 if your EC2 is in Mumbai
# CLAUDE_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
# SARVAM_API_KEY=your_key_here
```

**Alternative: System-wide environment variables**
```bash
# Edit system environment
sudo nano /etc/environment

# Add variables (one per line):
BEDROCK_REGION="eu-north-1"
AWS_REGION="eu-north-1"
CLAUDE_MODEL_ID="anthropic.claude-3-5-sonnet-20241022-v2:0"

# Save and reload
source /etc/environment
```

### Step 7: Install/Update System Dependencies
```bash
# Update package list
sudo apt update

# Install ffmpeg and audio libraries (if missing)
sudo apt install -y ffmpeg libsndfile1 libsndfile1-dev

# Verify installation
ffmpeg -version
```

### Step 8: Update Python Dependencies
```bash
# Activate virtual environment if using one
source venv/bin/activate  # Or your venv path

# Update dependencies
pip install -r requirements.txt

# Verify critical packages
pip list | grep -E "boto3|sarvamai|fastapi|pydub"
```

### Step 9: Check AWS IAM Role (Critical!)
```bash
# Check if EC2 has IAM role attached
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/

# If you see a role name, check its credentials
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/YOUR_ROLE_NAME

# Verify the role has these permissions:
# - bedrock:InvokeModel
# - bedrock:InvokeModelWithResponseStream
```

**If No IAM Role:**
```bash
# You'll need to set AWS credentials manually
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key

# Or add to .env file
echo "AWS_ACCESS_KEY_ID=your_key" >> .env
echo "AWS_SECRET_ACCESS_KEY=your_secret" >> .env
```

### Step 10: Test Network Connectivity
```bash
# Test Sarvam API
curl -I https://api.sarvam.ai/

# Test AWS Bedrock endpoint (should return 403, not timeout)
curl -I https://bedrock-runtime.eu-north-1.amazonaws.com/

# Test Cognito (replace with your pool ID)
curl https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_XXXXXXXXX/.well-known/jwks.json
```

**If Any Fail:** Check EC2 Security Group outbound rules - must allow HTTPS (port 443).

### Step 11: Restart Application
```bash
# If using systemd
sudo systemctl restart voice-assistant

# Or if using PM2
pm2 restart voice-assistant

# Or manual restart
pkill -f "python3 main.py"
python3 main.py

# Or with uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 12: Monitor Logs
```bash
# Tail application logs
tail -f logs/application.log

# Tail TTS logs
tail -f logs/tts.log

# Or if using systemd
sudo journalctl -u voice-assistant -f

# Or PM2
pm2 logs voice-assistant
```

**Look for these log messages:**
```
✅ Bedrock runtime client initialized in region: eu-north-1
✅ Sarvam client initialized successfully
🔄 ASR transcription attempt 1/2...
✅ Transcription successful on attempt 1
🤖 Invoking Claude model: anthropic.claude-3-5-sonnet-20241022-v2:0
✅ Claude invocation successful
```

**Watch for errors:**
```
❌ Failed to create Bedrock client (region=eu-north-1): ...
❌ Sarvam transcription failed on attempt 1: ...
⚠️ Empty transcript received on attempt 1, retrying...
```

---

## 🧪 Test the Fix

### Manual Test Call
```bash
# Make a test call to verify bot workflow
# Use your existing test customer or create one

# Check logs to verify:
# 1. ASR transcription succeeds (or retries and succeeds)
# 2. Claude gets invoked for intent detection
# 3. Bot speaks greeting and EMI details
# 4. Bot only transfers to agent when user explicitly requests
```

### Test Transcription Endpoint Directly
```bash
# Create a test audio file
# (You can use one from your existing test calls)

# Test ASR
curl -X POST http://localhost:8000/test-transcribe \
  -H "Content-Type: application/json" \
  -d '{"audio_base64": "your_audio_data"}'

# Should show retry attempts in logs if first attempt fails
```

---

## 🔍 Troubleshooting

### Issue: Bot Still Skipping Conversation

**Check 1: Verify environment variables loaded**
```bash
python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print('BEDROCK_REGION:', os.getenv('BEDROCK_REGION')); print('SARVAM_API_KEY:', os.getenv('SARVAM_API_KEY')[:10] if os.getenv('SARVAM_API_KEY') else 'NOT SET')"
```

**Check 2: Test Bedrock directly**
```bash
python3 -c "
import boto3
import os
from dotenv import load_dotenv
load_dotenv()

region = os.getenv('BEDROCK_REGION', 'eu-north-1')
print(f'Testing Bedrock in region: {region}')
try:
    client = boto3.client('bedrock-runtime', region_name=region)
    print('✅ Bedrock client created successfully')
except Exception as e:
    print(f'❌ Bedrock client failed: {e}')
"
```

**Check 3: Test Sarvam directly**
```bash
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv('SARVAM_API_KEY')
if api_key:
    print(f'Sarvam API Key: {api_key[:10]}...{api_key[-4:]}')
else:
    print('❌ SARVAM_API_KEY not set')

try:
    from sarvamai import SarvamAI
    client = SarvamAI(api_subscription_key=api_key)
    print('✅ Sarvam client initialized')
except Exception as e:
    print(f'❌ Sarvam client failed: {e}')
"
```

### Issue: AWS Credentials Not Found

```bash
# Attach IAM role to EC2 instance via AWS Console
# Or set credentials:
aws configure
# Enter: Access Key ID, Secret Access Key, Default region (eu-north-1)
```

### Issue: Sarvam API Timeout

```bash
# Check security group allows outbound HTTPS
aws ec2 describe-security-groups --group-ids sg-XXXXXXXXX

# Test with verbose curl
curl -v https://api.sarvam.ai/ 2>&1 | grep -E "Connected|timeout"
```

### Issue: ffmpeg Not Found

```bash
# Install ffmpeg
sudo apt update && sudo apt install -y ffmpeg

# Verify
which ffmpeg
ffmpeg -version
```

---

## 📊 Success Indicators

Your deployment is successful when:

1. ✅ **Diagnostic script passes all tests**
2. ✅ **Logs show:** "Bedrock runtime client initialized in region: eu-north-1"
3. ✅ **Logs show:** "Sarvam client initialized successfully"
4. ✅ **Test call:** Bot greets in selected language
5. ✅ **Test call:** Bot speaks EMI details from database
6. ✅ **Test call:** Bot offers agent connect (not forces it)
7. ✅ **Test call:** Bot only transfers when user says "yes" to agent connect
8. ✅ **Logs show ASR retries** (if first attempt fails): "ASR transcription attempt 2/2..."

---

## 🔄 Rollback Plan (If Needed)

```bash
# Stop application
sudo systemctl stop voice-assistant
# Or: pm2 stop voice-assistant

# Restore from backup
cd /path/to/voice-deployment
rm -rf voice-localenv
mv voice-backup-YYYYMMDD-HHMMSS voice-localenv

# Restart
cd voice-localenv
sudo systemctl start voice-assistant
```

---

## 📞 Support

If issues persist after following this guide:

1. **Collect full logs:**
   ```bash
   # Copy last 200 lines of application log
   tail -n 200 logs/application.log > debug_app.log
   tail -n 200 logs/tts.log > debug_tts.log
   
   # Copy diagnostic output
   python3 ../ec2_diagnostic.py > diagnostic_results.txt 2>&1
   ```

2. **Share these files** along with:
   - EC2 instance type and region
   - Python version: `python3 --version`
   - OS version: `lsb_release -a`

---

## 🎉 Summary of Fixes Applied

| Component | Issue | Fix |
|-----------|-------|-----|
| **Sarvam ASR** | Intermittent failures causing empty transcripts | Added 2-retry mechanism with exponential backoff |
| **Bedrock Client** | Hard-coded region (eu-north-1) | Made region configurable via `BEDROCK_REGION` env var |
| **Error Handling** | Silent failures leading to agent escalation | Added comprehensive logging at each step |
| **Model Configuration** | Hard-coded model ID | Made configurable via `CLAUDE_MODEL_ID` env var |
| **File Upload** | Missing imports causing NameError | Added all required imports to call_management.py |

All code changes are backward-compatible and will work in both local and EC2 environments.

---

**Last Updated:** After implementing retry logic and region configuration fixes  
**Testing Status:** Ready for EC2 deployment
