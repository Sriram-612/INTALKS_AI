#!/usr/bin/env python3
"""
Complete File Uploads Schema Migration
Adds all missing columns to match the current schema definition
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

def get_current_schema():
    """Get current file_uploads table schema"""
    
    inspector = inspect(engine)
    
    try:
        columns = inspector.get_columns('file_uploads')
        return {col['name']: col for col in columns}
    except Exception as e:
        print(f"❌ Error getting current schema: {e}")
        return {}

def migrate_file_uploads_schema():
    """Migrate file_uploads table to match the expected schema"""
    
    print("🔧 Migrating file_uploads table schema...")
    
    current_columns = get_current_schema()
    print(f"📊 Current columns: {list(current_columns.keys())}")
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Add missing columns one by one
            migrations = [
                {
                    'column': 'original_filename',
                    'definition': 'VARCHAR(255)',
                    'update': "UPDATE file_uploads SET original_filename = filename WHERE original_filename IS NULL"
                },
                {
                    'column': 'uploaded_by',
                    'definition': 'VARCHAR(100)',
                    'update': "UPDATE file_uploads SET uploaded_by = 'system' WHERE uploaded_by IS NULL"
                },
                {
                    'column': 'uploaded_at',
                    'definition': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
                    'update': "UPDATE file_uploads SET uploaded_at = upload_time WHERE uploaded_at IS NULL"
                },
                {
                    'column': 'success_records',
                    'definition': 'INTEGER DEFAULT 0',
                    'update': "UPDATE file_uploads SET success_records = (total_records - failed_records) WHERE success_records IS NULL"
                },
                {
                    'column': 'status',
                    'definition': 'VARCHAR(50) DEFAULT \'processing\'',
                    'update': "UPDATE file_uploads SET status = upload_status WHERE status IS NULL"
                }
            ]
            
            for migration in migrations:
                column_name = migration['column']
                
                if column_name not in current_columns:
                    print(f"➕ Adding {column_name} column...")
                    
                    # Add the column
                    connection.execute(text(f"""
                        ALTER TABLE file_uploads 
                        ADD COLUMN {column_name} {migration['definition']}
                    """))
                    
                    # Update existing records if there's an update query
                    if migration.get('update'):
                        print(f"🔄 Updating existing {column_name} values...")
                        connection.execute(text(migration['update']))
                    
                    print(f"✅ Added {column_name} column")
                else:
                    print(f"ℹ️  {column_name} column already exists")
            
            trans.commit()
            print("✅ Schema migration completed successfully!")
            
        except Exception as e:
            trans.rollback()
            print(f"❌ Migration failed: {e}")
            raise

def verify_complete_schema():
    """Verify the complete schema is now correct"""
    
    print("\n🔍 Verifying complete schema...")
    
    try:
        with engine.connect() as connection:
            # Test the exact query that was failing
            result = connection.execute(text("""
                SELECT count(*) AS count_1 
                FROM (
                    SELECT file_uploads.id AS file_uploads_id, 
                           file_uploads.filename AS file_uploads_filename, 
                           file_uploads.original_filename AS file_uploads_original_filename, 
                           file_uploads.uploaded_by AS file_uploads_uploaded_by, 
                           file_uploads.uploaded_at AS file_uploads_uploaded_at, 
                           file_uploads.total_records AS file_uploads_total_records, 
                           file_uploads.processed_records AS file_uploads_processed_records, 
                           file_uploads.success_records AS file_uploads_success_records, 
                           file_uploads.failed_records AS file_uploads_failed_records, 
                           file_uploads.status AS file_uploads_status, 
                           file_uploads.processing_errors AS file_uploads_processing_errors 
                    FROM file_uploads 
                    WHERE file_uploads.uploaded_at >= CURRENT_TIMESTAMP - INTERVAL '1 day'
                    ORDER BY file_uploads.uploaded_at DESC
                ) AS anon_1
            """))
            
            count = result.fetchone()[0]
            print(f"✅ Schema verification successful - query returned {count} records")
            
            # Show current table structure
            inspector = inspect(engine)
            columns = inspector.get_columns('file_uploads')
            print(f"📊 Final schema: {[col['name'] for col in columns]}")
                
    except Exception as e:
        print(f"❌ Schema verification failed: {e}")
        return False
    
    return True

def show_sample_data():
    """Show sample data from the table"""
    
    print("\n📊 Sample data from file_uploads table:")
    
    try:
        with engine.connect() as connection:
            result = connection.execute(text("""
                SELECT id, filename, original_filename, uploaded_by, uploaded_at, 
                       total_records, success_records, failed_records, status
                FROM file_uploads 
                ORDER BY uploaded_at DESC 
                LIMIT 3
            """))
            
            rows = result.fetchall()
            if rows:
                for i, row in enumerate(rows, 1):
                    print(f"  {i}. {dict(row._mapping)}")
            else:
                print("  No data in table yet")
                
    except Exception as e:
        print(f"❌ Error showing sample data: {e}")

def main():
    """Main migration function"""
    
    print("🚀 Complete File Uploads Schema Migration")
    print("=" * 60)
    
    # Perform the migration
    migrate_file_uploads_schema()
    
    # Verify the migration worked
    if verify_complete_schema():
        print("\n🎉 Complete schema migration successful!")
        
        # Show sample data
        show_sample_data()
        
        print("\n✅ The application should now work without column errors.")
        print("You can restart your server and the batch details should load correctly.")
        
    else:
        print("\n❌ Schema migration verification failed")
        return False
    
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
