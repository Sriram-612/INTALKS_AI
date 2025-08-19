# AWS Security Group Configuration for Voice Assistant
# Required inbound rules for EC2 instance (3.108.35.213)

## Security Group Rules (Inbound)

| Port  | Protocol | Source    | Description                    |
|-------|----------|-----------|--------------------------------|
| 22    | TCP      | Your IP   | SSH Access                     |
| 8000  | TCP      | 0.0.0.0/0 | FastAPI Application            |
| 80    | HTTP     | 0.0.0.0/0 | HTTP (optional, for redirects) |
| 443   | HTTPS    | 0.0.0.0/0 | HTTPS (for SSL certificates)  |

## Exotel Webhook Configuration

Update your Exotel webhooks to use the following URLs:

### For Voice Calls:
- **Incoming Call**: `http://3.108.35.213:8000/exotel/incoming_call`
- **Call Status**: `http://3.108.35.213:8000/exotel/call_status`
- **Recording**: `http://3.108.35.213:8000/exotel/recording`

### For WebSocket Connections:
- **Voice Stream**: `ws://3.108.35.213:8000/ws/voice/{call_sid}`
- **Status Updates**: `ws://3.108.35.213:8000/ws/status/{call_sid}`

## RDS Database Access

Ensure your RDS security group allows connections from EC2:
- **Port**: 5432 (PostgreSQL)
- **Source**: Security Group of EC2 instance or specific IP (3.108.35.213)

## Monitoring Commands

```bash
# Check service status
sudo systemctl status voice-assistant

# View real-time logs
sudo journalctl -u voice-assistant -f

# Check port availability
sudo netstat -tlnp | grep :8000

# Test API health
curl http://3.108.35.213:8000/health

# Test WebSocket (from local machine)
wscat -c ws://3.108.35.213:8000/ws/voice/test123
```

## SSL Certificate (Optional - for HTTPS)

To enable HTTPS, install SSL certificate:

```bash
# Install Certbot
sudo apt install certbot

# Get SSL certificate (requires domain name)
sudo certbot certonly --standalone -d yourdomain.com

# Update nginx configuration for SSL termination
```

## Environment Variables Check

Verify all required environment variables are set:

```bash
# Check .env file
cat /opt/voice-assistant/.env

# Test database connection
python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('DATABASE_URL'))"
```
