#!/bin/bash

# Deploy Voice Assistant Fixes to EC2
# This script updates the EC2 instance with the latest fixes

set -e  # Exit on any error

echo "🚀 Starting EC2 Deployment..."
echo ""

# Configuration
EC2_USER="ubuntu"
EC2_IP="ip-172-31-38-205"  # Update if different
EC2_PATH="~/voice_bot"
LOCAL_PATH="$(pwd)/voice-localenv"

echo "📋 Deployment Configuration:"
echo "   Local Path: $LOCAL_PATH"
echo "   Remote: $EC2_USER@$EC2_IP:$EC2_PATH"
echo ""

# Step 1: Backup on EC2
echo "1️⃣  Creating backup on EC2..."
ssh $EC2_USER@$EC2_IP << 'EOF'
    cd ~/voice_bot
    BACKUP_DIR="backup-$(date +%Y%m%d-%H%M%S)"
    echo "   Creating backup: $BACKUP_DIR"
    mkdir -p ../backups
    cp -r . ../backups/$BACKUP_DIR
    echo "   ✅ Backup created at ~/backups/$BACKUP_DIR"
EOF

echo ""

# Step 2: Copy updated files
echo "2️⃣  Uploading updated files..."

echo "   📄 Uploading utils/handler_asr.py..."
scp $LOCAL_PATH/utils/handler_asr.py $EC2_USER@$EC2_IP:$EC2_PATH/utils/handler_asr.py

echo "   📄 Uploading utils/bedrock_client.py..."
scp $LOCAL_PATH/utils/bedrock_client.py $EC2_USER@$EC2_IP:$EC2_PATH/utils/bedrock_client.py

echo "   📄 Uploading services/call_management.py..."
scp $LOCAL_PATH/services/call_management.py $EC2_USER@$EC2_IP:$EC2_PATH/services/call_management.py

echo "   ✅ Files uploaded successfully"
echo ""

# Step 3: Verify environment variables
echo "3️⃣  Verifying critical environment variables..."
ssh $EC2_USER@$EC2_IP << 'EOF'
    cd ~/voice_bot
    source .venv/bin/activate
    
    echo "   Checking .env file..."
    if [ -f .env ]; then
        echo "   ✅ .env file exists"
        
        # Check critical variables
        if grep -q "BEDROCK_REGION" .env; then
            echo "   ✅ BEDROCK_REGION is set"
        else
            echo "   ⚠️  BEDROCK_REGION not found in .env"
            echo "   Adding BEDROCK_REGION=eu-north-1 to .env"
            echo "BEDROCK_REGION=eu-north-1" >> .env
        fi
        
        if grep -q "CLAUDE_MODEL_ID" .env; then
            echo "   ✅ CLAUDE_MODEL_ID is set"
        else
            echo "   ⚠️  CLAUDE_MODEL_ID not found in .env"
            echo "   Adding default CLAUDE_MODEL_ID to .env"
            echo "CLAUDE_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0" >> .env
        fi
    else
        echo "   ❌ .env file not found!"
        echo "   Please create .env file with required variables"
    fi
EOF

echo ""

# Step 4: Restart application
echo "4️⃣  Restarting application..."
ssh $EC2_USER@$EC2_IP << 'EOF'
    cd ~/voice_bot
    source .venv/bin/activate
    
    echo "   Stopping current process..."
    pkill -f "python.*main.py" || echo "   (No running process found)"
    
    echo "   Starting application in background..."
    nohup python3 main.py > logs/app.log 2>&1 &
    
    sleep 3
    
    # Check if process started
    if pgrep -f "python.*main.py" > /dev/null; then
        echo "   ✅ Application started successfully"
        echo "   Process ID: $(pgrep -f 'python.*main.py')"
    else
        echo "   ❌ Application failed to start"
        echo "   Check logs: tail -f ~/voice_bot/logs/app.log"
        exit 1
    fi
EOF

echo ""

# Step 5: Verify logs
echo "5️⃣  Checking application logs (last 30 lines)..."
echo ""
ssh $EC2_USER@$EC2_IP << 'EOF'
    cd ~/voice_bot
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    tail -n 30 logs/app.log
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
EOF

echo ""
echo "🎉 Deployment Complete!"
echo ""
echo "📊 Next Steps:"
echo "   1. Monitor logs: ssh $EC2_USER@$EC2_IP 'tail -f $EC2_PATH/logs/application.log'"
echo "   2. Make a test call to verify bot behavior"
echo "   3. Look for these success indicators in logs:"
echo "      ✅ 'Bedrock runtime client initialized in region: eu-north-1'"
echo "      ✅ 'ASR transcription attempt X/2...'"
echo "      ✅ 'Invoking Claude model...'"
echo ""
echo "🔍 If issues persist, check:"
echo "   - Logs: $EC2_PATH/logs/application.log"
echo "   - Process status: ssh $EC2_USER@$EC2_IP 'ps aux | grep python'"
echo ""
