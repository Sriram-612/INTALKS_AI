#!/bin/bash
# Quick Deploy Script - Run this from your LOCAL machine

echo "🚀 Deploying fixed files to EC2..."
echo ""

# Configuration
EC2_HOST="ip-172-31-38-205"
EC2_USER="ubuntu"
EC2_PATH="~/voice_bot"

# Upload the 4 fixed files
echo "📤 Uploading handler_asr.py..."
scp voice-localenv/utils/handler_asr.py $EC2_USER@$EC2_HOST:$EC2_PATH/utils/handler_asr.py

echo "📤 Uploading bedrock_client.py..."
scp voice-localenv/utils/bedrock_client.py $EC2_USER@$EC2_HOST:$EC2_PATH/utils/bedrock_client.py

echo "📤 Uploading call_management.py..."
scp voice-localenv/services/call_management.py $EC2_USER@$EC2_HOST:$EC2_PATH/services/call_management.py

echo "📤 Uploading main.py (bank name fix)..."
scp main.py $EC2_USER@$EC2_HOST:$EC2_PATH/main.py

echo ""
echo "✅ Files uploaded successfully!"
echo ""
echo "📋 Next steps (run on EC2):"
echo "   1. pkill -f 'python.*main.py'"
echo "   2. cd ~/voice_bot && source .venv/bin/activate"
echo "   3. nohup python3 main.py > logs/app.log 2>&1 &"
echo "   4. tail -f logs/application.log"
echo ""
