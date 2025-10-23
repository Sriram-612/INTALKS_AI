#!/usr/bin/env python3
"""
Fix status columns in customers table
"""
import os
import sys
sys.path.append('.')
from database.schemas import db_manager
from sqlalchemy import text

def fix_status_columns():
    """Add status and call_status columns to customers table"""
    session = db_manager.get_session()
    try:
        print("[INIT] Fixing status columns in customers table...")
        
        # Add status column if it doesn't exist
        try:
            session.execute(text("""
                ALTER TABLE customers 
                ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'ready'
            """))
            print("[SUCCESS] Added status column")
        except Exception as e:
            if "already exists" in str(e) or "duplicate column" in str(e).lower():
                print("[INFO] status column already exists")
            else:
                print(f"[ERROR] Error adding status column: {e}")
        
        # Add call_status column if it doesn't exist
        try:
            session.execute(text("""
                ALTER TABLE customers 
                ADD COLUMN IF NOT EXISTS call_status VARCHAR(50) DEFAULT 'ready'
            """))
            print("[SUCCESS] Added call_status column")
        except Exception as e:
            if "already exists" in str(e) or "duplicate column" in str(e).lower():
                print("[INFO] call_status column already exists")
            else:
                print(f"[ERROR] Error adding call_status column: {e}")
        
        # Update existing customers to have 'ready' status if NULL
        try:
            result = session.execute(text("""
                UPDATE customers 
                SET status = 'ready', call_status = 'ready'
                WHERE status IS NULL OR call_status IS NULL
            """))
            print(f"[SUCCESS] Updated {result.rowcount} customers with default status")
        except Exception as e:
            print(f"[ERROR] Error updating customers: {e}")
        
        session.commit()
        print("[SUCCESS] Status columns fixed successfully")
        
    except Exception as e:
        print(f"[ERROR] {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    fix_status_columns()

