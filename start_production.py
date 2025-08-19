#!/usr/bin/env python3
"""
Production startup script for Voice Assistant
Optimized for AWS EC2 deployment
"""

import uvicorn
import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def setup_production_logging():
    """Configure production logging"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('/opt/voice-assistant/logs/production.log'),
            logging.StreamHandler()
        ]
    )

def validate_environment():
    """Validate all required environment variables"""
    required_vars = [
        'DATABASE_URL',
        'EXOTEL_SID',
        'EXOTEL_TOKEN',
        'BASE_URL',
        'AWS_ACCESS_KEY_ID',
        'AWS_SECRET_ACCESS_KEY'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        raise EnvironmentError(f"Missing required environment variables: {missing_vars}")
    
    logging.info("✅ All required environment variables are set")

def main():
    """Main startup function"""
    print("🚀 Starting Voice Assistant in Production Mode...")
    
    # Setup logging
    setup_production_logging()
    
    # Validate environment
    try:
        validate_environment()
    except EnvironmentError as e:
        logging.error(f"❌ Environment validation failed: {e}")
        exit(1)
    
    # Get configuration
    host = "0.0.0.0"  # Listen on all interfaces
    port = int(os.getenv("PORT", 8000))
    workers = int(os.getenv("WORKERS", 1))
    
    logging.info(f"🌐 Starting server on {host}:{port} with {workers} workers")
    
    # Start the server
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        workers=workers,
        log_level="info",
        access_log=True,
        reload=False,  # Disable reload in production
        proxy_headers=True,
        forwarded_allow_ips="*"
    )

if __name__ == "__main__":
    main()
