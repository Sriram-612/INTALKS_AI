#!/usr/bin/env python3
"""
Fix File Uploads Schema - Add Missing Columns
Adds missing columns to the file_uploads table to match the current schema
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
load_dotenv()

from database.schemas import engine

def check_missing_columns():
    """Check which columns are missing from file_uploads table"""
    
    print("🔍 Checking file_uploads table structure...")
    
    inspector = inspect(engine)
    
    # Get current columns in the table
    try:
        current_columns = [col['name'] for col in inspector.get_columns('file_uploads')]
        print(f"✅ Current columns in file_uploads: {current_columns}")
    except Exception as e:
        print(f"❌ Error checking table structure: {e}")
        return False, []
    
    # Expected columns from schema
    expected_columns = [
        'id', 'filename', 'original_filename', 'uploaded_by', 'uploaded_at',
        'total_records', 'processed_records', 'success_records', 'failed_records',
        'status', 'processing_errors'
    ]
    
    # Find missing columns
    missing_columns = [col for col in expected_columns if col not in current_columns]
    
    if missing_columns:
        print(f"❌ Missing columns: {missing_columns}")
        return False, missing_columns
    else:
        print("✅ All columns present")
        return True, []

def add_missing_columns():
    """Add missing columns to file_uploads table"""
    
    print("🔧 Adding missing columns to file_uploads table...")
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Check if original_filename column exists
            result = connection.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'file_uploads' 
                AND column_name = 'original_filename'
            """))
            
            if not result.fetchone():
                print("➕ Adding original_filename column...")
                connection.execute(text("""
                    ALTER TABLE file_uploads 
                    ADD COLUMN original_filename VARCHAR(255)
                """))
                print("✅ Added original_filename column")
            else:
                print("ℹ️  original_filename column already exists")
            
            # Update existing records to have original_filename = filename if null
            print("🔄 Updating existing records...")
            connection.execute(text("""
                UPDATE file_uploads 
                SET original_filename = filename 
                WHERE original_filename IS NULL
            """))
            print("✅ Updated existing records")
            
            trans.commit()
            print("✅ Migration completed successfully!")
            
        except Exception as e:
            trans.rollback()
            print(f"❌ Migration failed: {e}")
            raise

def verify_schema():
    """Verify the schema is now correct"""
    
    print("\n🔍 Verifying updated schema...")
    
    try:
        with engine.connect() as connection:
            # Test query that was failing
            result = connection.execute(text("""
                SELECT id, filename, original_filename, uploaded_by, uploaded_at,
                       total_records, processed_records, success_records, 
                       failed_records, status, processing_errors
                FROM file_uploads 
                LIMIT 1
            """))
            
            print("✅ Schema verification successful - all columns accessible")
            
            # Show sample data if any exists
            row = result.fetchone()
            if row:
                print(f"📊 Sample row: {dict(row._mapping)}")
            else:
                print("📊 No data in table yet")
                
    except Exception as e:
        print(f"❌ Schema verification failed: {e}")
        return False
    
    return True

def main():
    """Main migration function"""
    
    print("🚀 File Uploads Table Schema Fix")
    print("=" * 50)
    
    # Check current status
    is_valid, missing_cols = check_missing_columns()
    
    if not is_valid:
        print(f"\n🔧 Need to add {len(missing_cols)} missing columns")
        
        # Add missing columns
        add_missing_columns()
        
        # Verify the fix
        if verify_schema():
            print("\n🎉 Schema fix completed successfully!")
            print("The application should now work without column errors.")
        else:
            print("\n❌ Schema fix verification failed")
            return False
    else:
        print("\n✅ Schema is already correct!")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\n🚀 Ready to restart your application!")
        else:
            print("\n❌ Please check the errors above and try again")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
