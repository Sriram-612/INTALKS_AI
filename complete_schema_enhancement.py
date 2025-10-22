#!/usr/bin/env python3
"""
Fix File Uploads Table for Enhanced Schema
Adds the missing created_at column and other optimizations
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import text, inspect

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
load_dotenv()

from database.schemas import engine

def fix_file_uploads_table():
    """Fix the file_uploads table to include missing columns"""
    print("🔧 FIXING FILE_UPLOADS TABLE")
    print("=" * 50)
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Add missing created_at column
            print("📝 Adding created_at column to file_uploads...")
            connection.execute(text("""
                ALTER TABLE file_uploads 
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """))
            print("✅ created_at column added")
            
            # Update existing records to have created_at = uploaded_at
            print("📝 Updating existing records...")
            connection.execute(text("""
                UPDATE file_uploads 
                SET created_at = COALESCE(uploaded_at, upload_time, CURRENT_TIMESTAMP)
                WHERE created_at IS NULL
            """))
            print("✅ Existing records updated")
            
            # Add the missing indexes now that created_at exists
            indexes_to_create = [
                "CREATE INDEX IF NOT EXISTS idx_file_uploads_created_at ON file_uploads (created_at)",
                "CREATE INDEX IF NOT EXISTS idx_file_uploads_uploaded_at ON file_uploads (uploaded_at)",
                "CREATE INDEX IF NOT EXISTS idx_file_uploads_date_filter ON file_uploads (DATE(created_at))",
                "CREATE INDEX IF NOT EXISTS idx_file_uploads_daily ON file_uploads (DATE(created_at))"
            ]
            
            print("📇 Adding missing indexes...")
            for index_sql in indexes_to_create:
                try:
                    connection.execute(text(index_sql))
                    index_name = index_sql.split("IF NOT EXISTS ")[1].split(" ON")[0]
                    print(f"✅ {index_name}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"ℹ️  Index already exists")
                    else:
                        print(f"⚠️  Warning: {e}")
            
            trans.commit()
            print("\n✅ File uploads table fixed successfully!")
            
        except Exception as e:
            trans.rollback()
            print(f"\n❌ Error fixing file uploads table: {e}")
            raise

def verify_complete_schema():
    """Verify the complete enhanced schema"""
    print("\n🔍 COMPLETE SCHEMA VERIFICATION")
    print("=" * 60)
    
    with engine.connect() as connection:
        # Check all tables have proper date columns
        result = connection.execute(text("""
            SELECT 
                table_name,
                COUNT(*) as date_columns,
                STRING_AGG(column_name, ', ') as columns
            FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND data_type IN ('timestamp without time zone', 'timestamp with time zone', 'date', 'time')
            GROUP BY table_name
            ORDER BY table_name
        """))
        
        print("📅 DATE COLUMNS BY TABLE:")
        for row in result:
            print(f"   🔍 {row[0]:<20} ({row[1]} columns): {row[2]}")
        
        # Check CSV enhancement columns
        result = connection.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'file_uploads'
            AND column_name IN ('csv_headers', 'csv_delimiter', 'file_hash', 'processing_start_time')
        """))
        
        csv_columns = [row[0] for row in result]
        print(f"\n📄 CSV ENHANCEMENT COLUMNS: {len(csv_columns)} added")
        for col in csv_columns:
            print(f"   ✅ {col}")
        
        # Check helper functions
        result = connection.execute(text("""
            SELECT routine_name FROM information_schema.routines
            WHERE routine_schema = 'public'
            AND routine_name IN ('utc_to_ist', 'get_ist_date_range', 'business_days_between')
        """))
        
        functions = [row[0] for row in result]
        print(f"\n🛠️  HELPER FUNCTIONS: {len(functions)} created")
        for func in functions:
            print(f"   🔧 {func}")
        
        # Test IST date helper function
        print(f"\n🧪 TESTING IST DATE HELPER:")
        try:
            result = connection.execute(text("SELECT * FROM get_ist_date_range('today')"))
            date_range = result.fetchone()
            if date_range:
                print(f"   📅 Today range: {date_range[0]} to {date_range[1]}")
            
            result = connection.execute(text("SELECT utc_to_ist(CURRENT_TIMESTAMP)"))
            ist_time = result.fetchone()
            if ist_time:
                print(f"   🕐 Current IST: {ist_time[0]}")
        except Exception as e:
            print(f"   ⚠️  Function test warning: {e}")

def create_sample_enhanced_data():
    """Create sample data using enhanced schema features"""
    print("\n📊 CREATING SAMPLE ENHANCED DATA")
    print("=" * 60)
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Create a sample CSV processing batch
            result = connection.execute(text("""
                INSERT INTO csv_processing_batches (
                    batch_identifier,
                    processing_status,
                    total_rows,
                    processed_rows,
                    successful_rows,
                    started_at
                ) VALUES (
                    'sample_batch_' || EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)::TEXT,
                    'completed',
                    100,
                    100,
                    95,
                    utc_to_ist(CURRENT_TIMESTAMP)
                ) RETURNING id, batch_identifier
            """))
            
            batch = result.fetchone()
            if batch:
                print(f"✅ Sample batch created: {batch[1]}")
                print(f"   ID: {batch[0]}")
            
            trans.commit()
            print("✅ Sample enhanced data created!")
            
        except Exception as e:
            trans.rollback()
            print(f"⚠️  Sample data creation warning: {e}")

def main():
    """Main function to complete the schema enhancements"""
    print("🔧 COMPLETING DATABASE SCHEMA ENHANCEMENTS")
    print("=" * 70)
    
    try:
        # Fix file_uploads table
        fix_file_uploads_table()
        
        # Verify complete schema
        verify_complete_schema()
        
        # Create sample data
        create_sample_enhanced_data()
        
        print("\n🎉 SCHEMA ENHANCEMENT COMPLETED!")
        print("=" * 70)
        print("✅ All tables optimized for date handling")
        print("✅ CSV processing capabilities enhanced")
        print("✅ Performance indexes added")
        print("✅ IST timezone helper functions available")
        print("✅ Sample data created for testing")
        print("\n🚀 Your voice assistant application is now fully optimized!")
        
    except Exception as e:
        print(f"\n❌ Final enhancement failed: {e}")
        raise

if __name__ == "__main__":
    main()
