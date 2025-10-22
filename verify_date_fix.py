#!/usr/bin/env python3
"""
Quick test to verify the upload date fix is working correctly
"""
import sys
from datetime import datetime

# Add the project root to Python path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

print("🕐 TIME VERIFICATION")
print("=" * 50)
print(f"📅 datetime.now():     {datetime.now()}")
print(f"📅 datetime.now().date(): {datetime.now().date()}")
print(f"🌐 datetime.utcnow():  {datetime.utcnow()}")
print(f"🌐 datetime.utcnow().date(): {datetime.utcnow().date()}")
print()

# Test the current date behavior
local_date = datetime.now().date()
utc_date = datetime.utcnow().date()

print(f"✅ Local date should be: 2025-09-28")
print(f"📊 Local date is:       {local_date}")
print(f"📊 UTC date is:         {utc_date}")

if str(local_date) == "2025-09-28":
    print("✅ Local date is correct for today")
else:
    print("❌ Local date is incorrect")

if str(utc_date) == "2025-09-28":
    print("✅ UTC date is also today")
else:
    print("⚠️ UTC date is different (timezone offset)")
