# 🚀 QUICK EC2 DEPLOYMENT - You're Already SSH'd In!

## ✅ Great News!
Your EC2 diagnostic passed all critical tests:
- ✅ Sarvam API: Connected
- ✅ AWS Bedrock: Connected (region: eu-north-1)
- ✅ Database: Connected
- ✅ All environment variables: Present

## 📦 What You Need to Do Now

You're currently at: `(.venv) ubuntu@ip-172-31-38-205:~/voice_bot$`

### Step 1: Backup Current Code (Safety First!)
```bash
cd ~
mkdir -p backups
cp -r voice_bot backups/voice_bot-backup-$(date +%Y%m%d-%H%M%S)
cd voice_bot
```

### Step 2: Update the 3 Fixed Files

You need to copy these 3 files from your local machine to EC2:

**Option A: Using SCP from your LOCAL machine** (Open a new terminal locally):
```bash
# From your local machine (voice-deployment directory)
cd /home/cyberdude/Documents/Projects/voice-deployment/voice-localenv

# Upload the 3 fixed files
scp utils/handler_asr.py ubuntu@ip-172-31-38-205:~/voice_bot/utils/
scp utils/bedrock_client.py ubuntu@ip-172-31-38-205:~/voice_bot/utils/
scp services/call_management.py ubuntu@ip-172-31-38-205:~/voice_bot/services/
```

**Option B: Using Git** (If your code is in a Git repo):
```bash
# On EC2
cd ~/voice_bot
git pull origin main
```

**Option C: Manual Copy-Paste** (If files are small):
1. Copy each file content from local machine
2. On EC2, edit each file: `nano utils/handler_asr.py` (paste content, save)

### Step 3: Verify Environment Variables
```bash
# Check if critical variables are in .env
cd ~/voice_bot
cat .env | grep -E "BEDROCK_REGION|CLAUDE_MODEL_ID|AWS_REGION"
```

**If BEDROCK_REGION is missing:**
```bash
echo "BEDROCK_REGION=eu-north-1" >> .env
```

**If CLAUDE_MODEL_ID is missing:**
```bash
echo "CLAUDE_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0" >> .env
```

### Step 4: Restart Your Application

**Check what's currently running:**
```bash
ps aux | grep python | grep main
```

**Stop current process:**
```bash
# If using systemd
sudo systemctl restart voice-bot

# OR if running manually
pkill -f "python.*main.py"
```

**Start application:**
```bash
cd ~/voice_bot
source .venv/bin/activate

# Option 1: Run in background with nohup
nohup python3 main.py > logs/app.log 2>&1 &

# Option 2: Run with uvicorn
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > logs/app.log 2>&1 &

# Option 3: If using PM2
pm2 restart voice-bot
```

**Verify it started:**
```bash
ps aux | grep python | grep main
# Should show a running process
```

### Step 5: Monitor Logs for Success

**Tail the logs:**
```bash
tail -f logs/application.log
# Or
tail -f logs/app.log
# Or
tail -f logs/tts.log
```

**Look for these SUCCESS indicators:**
```
✅ Bedrock runtime client initialized in region: eu-north-1
✅ Sarvam client initialized successfully
✅ Connected to database
```

**During a call, you should see:**
```
🔄 ASR transcription attempt 1/2...
✅ Transcription successful on attempt 1
🤖 Invoking Claude model: anthropic.claude-3-5-sonnet-20241022-v2:0
✅ Claude invocation successful
```

### Step 6: Make a Test Call

1. Trigger a test call from your system
2. Watch the logs in real-time
3. Verify:
   - ✅ Bot greets in selected language
   - ✅ Bot speaks EMI details
   - ✅ Bot offers agent connect (doesn't force it)
   - ✅ Bot only transfers when user says "yes"

---

## 🔍 Troubleshooting

### If logs show "Empty transcript" or "Sarvam failed":
```bash
# Check the retry logic is working
grep -i "attempt" logs/application.log | tail -20
# You should see "attempt 1/2" and "attempt 2/2" lines
```

### If logs show "Bedrock client failed":
```bash
# Verify AWS credentials
aws sts get-caller-identity

# Check region is set
echo $AWS_REGION
cat .env | grep REGION
```

### If bot still skips conversation:
```bash
# Enable DEBUG logging
export LOG_LEVEL=DEBUG

# Restart application
pkill -f "python.*main.py"
python3 main.py

# Watch detailed logs
tail -f logs/application.log
```

---

## 📊 What the Fixes Do

1. **`handler_asr.py`** - ASR Retry Logic
   - Now retries transcription 2 times if it fails
   - Waits 0.6 seconds between retries
   - Logs each attempt for debugging

2. **`bedrock_client.py`** - Region Configuration
   - Reads `BEDROCK_REGION` from environment (not hard-coded)
   - Logs success/failure clearly
   - Safe null-checking to prevent crashes

3. **`call_management.py`** - File Upload Fix
   - Added missing imports (already working locally)

---

## 🎯 Expected Result

**BEFORE (Your Current Issue):**
```
Bot: "Hello" → [Sarvam fails] → [No transcript] → [No Claude call] 
Bot: "Tell me your problem why you call" → [Transfers to agent immediately]
```

**AFTER (With Fixes):**
```
Bot: "Hello" → [Sarvam attempt 1] → [Success/Retry if needed] → [Transcript received]
Bot: [Calls Claude] → [Gets intent] → [Speaks EMI details] → [Offers agent connect]
User: "Yes, connect me to agent"
Bot: [Transfers to agent ONLY now]
```

---

## 🆘 Need Help?

**Collect diagnostic info:**
```bash
# Save last 200 lines of logs
tail -n 200 logs/application.log > debug_log.txt
tail -n 200 logs/tts.log >> debug_log.txt

# Get process info
ps aux | grep python >> debug_log.txt

# Get environment variables (sanitized)
env | grep -E "BEDROCK|CLAUDE|SARVAM|AWS" | sed 's/=.*/=***/' >> debug_log.txt
```

Then share `debug_log.txt` for analysis.

---

**You're almost there! Just copy the 3 files and restart. 🚀**
