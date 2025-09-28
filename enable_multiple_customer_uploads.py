#!/usr/bin/env python3
"""
Enable Multiple Customer Records for Different Upload Dates
WARNING: This changes the database schema to allow duplicate phone numbers
"""

from sqlalchemy import text
from database.schemas import db_manager

def enable_multiple_customer_uploads():
    """
    Removes the unique constraint on primary_phone to allow 
    the same customer to be uploaded multiple times with different dates
    """
    session = db_manager.get_session()
    
    try:
        print("🔧 Removing unique constraint on primary_phone...")
        
        # Drop the unique constraint
        session.execute(text("""
            ALTER TABLE customers 
            DROP CONSTRAINT IF EXISTS uix_customer_primary_phone;
        """))
        
        session.commit()
        print("✅ Unique constraint removed successfully!")
        print("📝 Now the same customer can be uploaded multiple times")
        print("⚠️  WARNING: This allows duplicate phone numbers in the database")
        
        return True
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error: {e}")
        return False
        
    finally:
        session.close()

def restore_unique_constraint():
    """
    Restores the unique constraint on primary_phone
    WARNING: This will fail if there are duplicate phone numbers
    """
    session = db_manager.get_session()
    
    try:
        print("🔧 Restoring unique constraint on primary_phone...")
        
        # Add the unique constraint back
        session.execute(text("""
            ALTER TABLE customers 
            ADD CONSTRAINT uix_customer_primary_phone 
            UNIQUE (primary_phone);
        """))
        
        session.commit()
        print("✅ Unique constraint restored successfully!")
        
        return True
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error: {e}")
        print("💡 You may have duplicate phone numbers that need to be cleaned up first")
        return False
        
    finally:
        session.close()

if __name__ == "__main__":
    print("🎯 Customer Upload Behavior Configuration")
    print("=" * 50)
    print("1. Current: Same customer = UPDATE existing record")
    print("2. Option: Same customer = CREATE new record each time")
    print()
    
    choice = input("Remove unique constraint to allow multiple records? (y/N): ").lower()
    
    if choice == 'y':
        if enable_multiple_customer_uploads():
            print("\n🎉 SUCCESS: Same customers can now be uploaded multiple times!")
        else:
            print("\n❌ FAILED: Could not modify constraint")
    else:
        print("\n📝 No changes made. Current behavior maintained.")
