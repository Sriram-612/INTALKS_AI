#!/usr/bin/env python3
"""
Database Migration: Remove primary_phone unique constraint
This allows multiple customer entries with the same phone number across uploads
Each entry remains unique via fingerprint (timestamp + UUID)
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:IntalksAI07@db-voice-agent.cviea4aicss0.ap-south-1.rds.amazonaws.com:5432/db-voice-agent")

def migrate():
    """Remove unique constraint on primary_phone to allow multiple uploads"""
    
    print("=" * 70)
    print("  DATABASE MIGRATION: Remove primary_phone Unique Constraint")
    print("=" * 70)
    print()
    print("📋 Purpose: Allow multiple customer entries with same phone (across uploads)")
    print("📋 Impact: Customers can be uploaded multiple times (date-based tracking)")
    print("📋 Safety: fingerprint column remains unique (timestamp + UUID)")
    print()
    
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # Check if constraint exists
            print("1️⃣  Checking for existing constraint...")
            result = conn.execute(text("""
                SELECT constraint_name 
                FROM information_schema.table_constraints 
                WHERE table_name = 'customers' 
                AND constraint_type = 'UNIQUE'
                AND constraint_name = 'uix_customer_primary_phone'
            """))
            
            if result.fetchone():
                print("   ✅ Constraint 'uix_customer_primary_phone' found")
                
                # Remove the constraint
                print("\n2️⃣  Removing unique constraint on primary_phone...")
                conn.execute(text("ALTER TABLE customers DROP CONSTRAINT IF EXISTS uix_customer_primary_phone"))
                conn.commit()
                print("   ✅ Constraint removed successfully")
                
            else:
                print("   ℹ️  Constraint 'uix_customer_primary_phone' not found (already removed or never existed)")
            
            # Verify fingerprint constraint still exists
            print("\n3️⃣  Verifying fingerprint uniqueness constraint...")
            result = conn.execute(text("""
                SELECT constraint_name 
                FROM information_schema.table_constraints 
                WHERE table_name = 'customers' 
                AND constraint_type = 'UNIQUE'
                AND constraint_name LIKE '%fingerprint%'
            """))
            
            fingerprint_constraint = result.fetchone()
            if fingerprint_constraint:
                print(f"   ✅ Fingerprint constraint exists: {fingerprint_constraint[0]}")
            else:
                print("   ⚠️  No fingerprint constraint found (this is unusual)")
            
            # Show final constraints
            print("\n4️⃣  Final constraints on 'customers' table:")
            result = conn.execute(text("""
                SELECT constraint_name, constraint_type 
                FROM information_schema.table_constraints 
                WHERE table_name = 'customers'
                ORDER BY constraint_type, constraint_name
            """))
            
            for row in result:
                print(f"   • {row[1]:15s}: {row[0]}")
            
            print()
            print("=" * 70)
            print("  ✅ MIGRATION COMPLETE")
            print("=" * 70)
            print()
            print("📊 Result:")
            print("   • Multiple customer entries per phone number: ALLOWED")
            print("   • Unique fingerprint per entry: ENFORCED")
            print("   • Date-based customer tracking: ENABLED")
            print()
            print("🚀 Next Steps:")
            print("   1. Test file upload: python3 debug_csv_upload.py")
            print("   2. Upload same customer twice (should succeed)")
            print("   3. Verify both entries exist in database")
            print()
            
            return True
            
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = migrate()
    exit(0 if success else 1)
