#!/bin/bash
# Production Deployment Script for AWS EC2
# Server IP: 3.108.35.213

echo "🚀 Starting AWS Production Deployment..."

# Update system packages
echo "📦 Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install Python 3.11 and pip if not already installed
echo "🐍 Setting up Python environment..."
sudo apt install -y python3.11 python3.11-pip python3.11-venv

# Install Redis Server
echo "📦 Installing Redis Server..."
sudo apt install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Install PostgreSQL client (for RDS connection)
echo "🗄️ Installing PostgreSQL client..."
sudo apt install -y postgresql-client

# Create application directory
echo "📁 Setting up application directory..."
sudo mkdir -p /opt/voice-assistant
sudo chown $USER:$USER /opt/voice-assistant
cd /opt/voice-assistant

# Create Python virtual environment
echo "🔧 Creating Python virtual environment..."
python3.11 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo "📋 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Copy application files
echo "📄 Copying application files..."
cp -r /home/cyberdude/Documents/Projects/voice/* .

# Set proper permissions
chmod +x run_server.py
chmod +x main.py

# Create systemd service
echo "⚙️ Creating systemd service..."
sudo tee /etc/systemd/system/voice-assistant.service > /dev/null <<EOF
[Unit]
Description=Voice Assistant API Server
After=network.target redis.service

[Service]
Type=simple
User=$USER
WorkingDirectory=/opt/voice-assistant
Environment=PATH=/opt/voice-assistant/venv/bin
ExecStart=/opt/voice-assistant/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable voice-assistant
sudo systemctl start voice-assistant

# Configure firewall
echo "🔥 Configuring firewall..."
sudo ufw allow 22     # SSH
sudo ufw allow 8000   # FastAPI
sudo ufw allow 80     # HTTP
sudo ufw allow 443    # HTTPS
sudo ufw --force enable

# Create log rotation
echo "📝 Setting up log rotation..."
sudo tee /etc/logrotate.d/voice-assistant > /dev/null <<EOF
/opt/voice-assistant/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 644 $USER $USER
}
EOF

# Test database connection
echo "🔍 Testing database connection..."
python3 -c "
import psycopg2
import os
from dotenv import load_dotenv
load_dotenv()
try:
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    print('✅ Database connection successful')
    conn.close()
except Exception as e:
    print(f'❌ Database connection failed: {e}')
"

# Test Redis connection
echo "🔍 Testing Redis connection..."
redis-cli ping

echo "✅ Production deployment completed!"
echo ""
echo "🌐 Service Details:"
echo "   - Server IP: 3.108.35.213"
echo "   - API Port: 8000"
echo "   - Service Status: systemctl status voice-assistant"
echo "   - View Logs: journalctl -u voice-assistant -f"
echo "   - API Health: curl http://3.108.35.213:8000/health"
echo ""
echo "📋 Next Steps:"
echo "   1. Update Exotel webhooks to use: http://3.108.35.213:8000"
echo "   2. Configure AWS Security Groups to allow port 8000"
echo "   3. Test WebSocket endpoints"
echo "   4. Monitor application logs"
