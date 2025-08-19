#!/bin/bash
# Quick AWS Setup Verification Script
# Run this after deployment to verify everything is working

echo "🔍 Voice Assistant AWS Setup Verification"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Server details
SERVER_IP="3.108.35.213"
SERVER_PORT="8000"
BASE_URL="http://$SERVER_IP:$SERVER_PORT"

echo -e "🌐 Server: ${YELLOW}$SERVER_IP:$SERVER_PORT${NC}"
echo ""

# Test 1: Ping server
echo "1️⃣  Testing server connectivity..."
if ping -c 1 $SERVER_IP > /dev/null 2>&1; then
    echo -e "   ✅ Server is ${GREEN}reachable${NC}"
else
    echo -e "   ❌ Server is ${RED}unreachable${NC}"
fi

# Test 2: Check port 8000
echo "2️⃣  Testing port 8000..."
if nc -z $SERVER_IP $SERVER_PORT 2>/dev/null; then
    echo -e "   ✅ Port 8000 is ${GREEN}open${NC}"
else
    echo -e "   ❌ Port 8000 is ${RED}closed${NC}"
fi

# Test 3: Health endpoint
echo "3️⃣  Testing health endpoint..."
if curl -s "$BASE_URL/health" > /dev/null 2>&1; then
    echo -e "   ✅ Health endpoint is ${GREEN}responding${NC}"
    
    # Get detailed health info
    health_response=$(curl -s "$BASE_URL/health")
    status=$(echo $health_response | jq -r '.status' 2>/dev/null || echo "unknown")
    if [ "$status" = "healthy" ]; then
        echo -e "   ✅ Application status: ${GREEN}healthy${NC}"
    else
        echo -e "   ⚠️  Application status: ${YELLOW}$status${NC}"
    fi
else
    echo -e "   ❌ Health endpoint is ${RED}not responding${NC}"
fi

# Test 4: WebSocket URL endpoint
echo "4️⃣  Testing WebSocket URL generator..."
ws_response=$(curl -s "$BASE_URL/ws-url?CallSid=test123&From=+917983394461" 2>/dev/null)
if [ $? -eq 0 ]; then
    echo -e "   ✅ WebSocket URL generator is ${GREEN}working${NC}"
    echo "   📍 Generated URL: $ws_response"
else
    echo -e "   ❌ WebSocket URL generator is ${RED}not working${NC}"
fi

# Test 5: Database connection (if psql is available)
echo "5️⃣  Testing database connection..."
if command -v psql > /dev/null 2>&1; then
    if psql "$DATABASE_URL" -c "SELECT 1;" > /dev/null 2>&1; then
        echo -e "   ✅ Database connection is ${GREEN}working${NC}"
    else
        echo -e "   ❌ Database connection ${RED}failed${NC}"
    fi
else
    echo -e "   ⚠️  psql not available - ${YELLOW}skipping database test${NC}"
fi

# Test 6: Redis connection
echo "6️⃣  Testing Redis connection..."
if command -v redis-cli > /dev/null 2>&1; then
    if redis-cli ping > /dev/null 2>&1; then
        echo -e "   ✅ Redis connection is ${GREEN}working${NC}"
    else
        echo -e "   ❌ Redis connection ${RED}failed${NC}"
    fi
else
    echo -e "   ⚠️  redis-cli not available - ${YELLOW}skipping Redis test${NC}"
fi

# Test 7: Service status
echo "7️⃣  Testing systemd service..."
if systemctl is-active voice-assistant > /dev/null 2>&1; then
    echo -e "   ✅ Voice Assistant service is ${GREEN}active${NC}"
else
    echo -e "   ❌ Voice Assistant service is ${RED}inactive${NC}"
fi

echo ""
echo "🔧 CONFIGURATION SUMMARY"
echo "========================"
echo "📍 Base URL: $BASE_URL"
echo "🌐 WebSocket URL: ws://$SERVER_IP:$SERVER_PORT/ws/voice/{call_sid}"
echo "🎯 Exotel Webhooks:"
echo "   • Incoming Call: $BASE_URL/exotel/incoming_call"
echo "   • Call Status: $BASE_URL/exotel/call_status"
echo "   • Recording: $BASE_URL/exotel/recording"
echo "   • WebSocket URL: $BASE_URL/ws-url"

echo ""
echo "💡 NEXT STEPS"
echo "============="
echo "1. Update Exotel dashboard with webhook URLs above"
echo "2. Configure AWS Security Group to allow port 8000"
echo "3. Test voice calls with your Exotel number"
echo "4. Monitor logs: journalctl -u voice-assistant -f"

echo ""
echo "📊 For continuous monitoring, run: python3 monitor_aws.py --continuous"
echo "🔧 For Exotel configuration help, run: python3 configure_exotel.py"
echo ""
echo "✨ Setup verification complete!"
