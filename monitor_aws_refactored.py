#!/usr/bin/env python3
"""
AWS Production Monitoring Script
Monitors Voice Assistant application health and performance with structured logging and error handling.
"""

import os
import time
import json
import requests
import psutil
import subprocess
import logging
from datetime import datetime
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()
BASE_URL = os.getenv('BASE_URL', 'https://collections.intalksai.com/')
LOG_FILE = "monitor_aws.log"
MONITORING_INTERVAL_SECONDS = 300

# --- Logger Setup ---
def setup_logger():
    """Set up a structured logger."""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # Create handlers
    console_handler = logging.StreamHandler()
    file_handler = logging.FileHandler(LOG_FILE)
    
    # Create formatters
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    
    # Add handlers to the logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logger()

# --- Helper Functions ---
def run_subprocess(command):
    """Run a subprocess command and handle potential errors."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True  # Raise CalledProcessError for non-zero exit codes
        )
        return result.stdout.strip()
    except FileNotFoundError:
        logger.error(f"Command not found: {command[0]}")
        return None
    except subprocess.CalledProcessError as e:
        logger.error(f"Command '{' '.join(command)}' failed with exit code {e.returncode}: {e.stderr.strip()}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while running '{' '.join(command)}': {e}")
        return None

# --- Check Functions ---
def check_system_resources():
    """Check system CPU, memory, and disk usage."""
    try:
        return {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_percent': psutil.disk_usage('/').percent
        }
    except Exception as e:
        logger.error(f"Failed to check system resources: {e}")
        return None

def check_service_status(service_name='voice-assistant'):
    """Check the status of a systemd service."""
    output = run_subprocess(['systemctl', 'is-active', service_name])
    return output == 'active' if output is not None else False

def check_port_listening(port=8000):
    """Check if a specific port is listening."""
    output = run_subprocess(['netstat', '-tlnp'])
    return f":{port}" in output if output is not None else False

def check_application_health():
    """Check the application's health endpoint."""
    try:
        response = requests.get(f'{BASE_URL}/health', timeout=10)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        return True, response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Application health check failed: {e}")
        return False, str(e)

def check_redis_status():
    """Check Redis server status."""
    output = run_subprocess(['redis-cli', 'ping'])
    return output == 'PONG' if output is not None else False

def check_database_connection():
    """Check database connectivity."""
    try:
        import psycopg2
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            return False, "DATABASE_URL not set"
        
        with psycopg2.connect(db_url) as conn:
            return True, "Connected"
    except ImportError:
        logger.error("psycopg2 is not installed. Cannot check database connection.")
        return False, "psycopg2 not installed"
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False, str(e)

def get_recent_logs(service_name='voice-assistant', lines=10):
    """Get recent application logs from journalctl."""
    return run_subprocess(['journalctl', '-u', service_name, f'--lines={lines}', '--no-pager'])

# --- Main Logic ---
def generate_report():
    """Generate and log a comprehensive monitoring report."""
    logger.info("=" * 60)
    logger.info(f"🔍 Voice Assistant Monitoring Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # System Resources
    resources = check_system_resources()
    if resources:
        logger.info(f"📊 SYSTEM RESOURCES: CPU: {resources['cpu_percent']}%, Memory: {resources['memory_percent']}%, Disk: {resources['disk_percent']}%")
        if resources['cpu_percent'] > 80:
            logger.warning("High CPU usage detected.")
        if resources['memory_percent'] > 80:
            logger.warning("High memory usage detected.")
        if resources['disk_percent'] > 80:
            logger.warning("Low disk space detected.")

    # Service Status
    service_active = check_service_status()
    port_listening = check_port_listening()
    redis_running = check_redis_status()
    logger.info(f"⚙️ SERVICE STATUS: App Service: {'✅ ACTIVE' if service_active else '❌ INACTIVE'}, Port 8000: {'✅ LISTENING' if port_listening else '❌ NOT LISTENING'}, Redis: {'✅ RUNNING' if redis_running else '❌ STOPPED'}")
    if not service_active:
        logger.warning("Recommendation: Start the service with 'sudo systemctl start voice-assistant'")
    if not port_listening:
        logger.warning("Recommendation: Check for conflicting processes on port 8000.")
    if not redis_running:
        logger.warning("Recommendation: Start Redis with 'sudo systemctl start redis-server'")

    # Application Health
    health_ok, health_data = check_application_health()
    if health_ok:
        logger.info(f"🏥 APPLICATION HEALTH: ✅ HEALTHY - {health_data}")
    else:
        logger.error(f"🏥 APPLICATION HEALTH: ❌ UNHEALTHY - {health_data}")
        logger.warning("Recommendation: Check application logs with 'journalctl -u voice-assistant -f'")

    # Database Connection
    db_ok, db_msg = check_database_connection()
    logger.info(f"🗄️ DATABASE: PostgreSQL Connection: {'✅' if db_ok else '❌'} {db_msg}")

    # Recent Logs
    recent_logs = get_recent_logs()
    if recent_logs:
        logger.info("📝 RECENT LOGS (Last 10 lines):\n" + recent_logs)

def main():
    """Main function to run the monitoring loop."""
    logger.info("🚀 Starting AWS Production Monitoring Script")
    while True:
        generate_report()
        logger.info(f"Waiting for {MONITORING_INTERVAL_SECONDS} seconds before the next check...")
        time.sleep(MONITORING_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("🛑 Monitoring script stopped by user.")
    except Exception as e:
        logger.critical(f"A critical error occurred in the main loop: {e}", exc_info=True)
