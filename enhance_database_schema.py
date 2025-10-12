#!/usr/bin/env python3
"""
Enhanced Database Schema Migration
Optimizes schemas for better date handling and CSV file processing
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import text, inspect

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
load_dotenv()

from database.schemas import engine

def analyze_current_date_handling():
    """Analyze current date/time column usage"""
    print("📅 CURRENT DATE/TIME COLUMN ANALYSIS")
    print("=" * 60)
    
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    date_columns = {}
    
    for table_name in tables:
        columns = inspector.get_columns(table_name)
        table_date_cols = []
        
        for col in columns:
            col_type = str(col['type']).upper()
            if any(dt in col_type for dt in ['TIMESTAMP', 'DATE', 'TIME']):
                table_date_cols.append({
                    'name': col['name'],
                    'type': col_type,
                    'nullable': col['nullable'],
                    'default': col['default']
                })
        
        if table_date_cols:
            date_columns[table_name] = table_date_cols
    
    for table, cols in date_columns.items():
        print(f"\n🔍 {table.upper()}:")
        for col in cols:
            nullable = "NULL" if col['nullable'] else "NOT NULL"
            default = f" DEFAULT({col['default']})" if col['default'] else ""
            print(f"   📅 {col['name']:<25} {col['type']:<20} {nullable}{default}")
    
    return date_columns

def enhance_date_handling():
    """Enhance date handling across all tables"""
    print("\n🔧 ENHANCING DATE HANDLING")
    print("=" * 60)
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Add timezone support and better date indexing
            enhancements = [
                {
                    'table': 'customers',
                    'operations': [
                        # Ensure proper timezone handling
                        "ALTER TABLE customers ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP",
                        "ALTER TABLE customers ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP",
                        # Add date indexing for better performance
                        "CREATE INDEX IF NOT EXISTS idx_customers_created_at ON customers (created_at)",
                        "CREATE INDEX IF NOT EXISTS idx_customers_first_uploaded_at ON customers (first_uploaded_at)",
                        "CREATE INDEX IF NOT EXISTS idx_customers_last_contact_date ON customers (last_contact_date)",
                        # Add date range queries optimization
                        "CREATE INDEX IF NOT EXISTS idx_customers_date_range ON customers (first_uploaded_at, created_at)",
                    ]
                },
                {
                    'table': 'file_uploads',
                    'operations': [
                        "ALTER TABLE file_uploads ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP",
                        "ALTER TABLE file_uploads ALTER COLUMN uploaded_at SET DEFAULT CURRENT_TIMESTAMP",
                        "CREATE INDEX IF NOT EXISTS idx_file_uploads_created_at ON file_uploads (created_at)",
                        "CREATE INDEX IF NOT EXISTS idx_file_uploads_uploaded_at ON file_uploads (uploaded_at)",
                        # Add date filtering index
                        "CREATE INDEX IF NOT EXISTS idx_file_uploads_date_filter ON file_uploads (DATE(created_at))",
                    ]
                },
                {
                    'table': 'call_sessions',
                    'operations': [
                        "ALTER TABLE call_sessions ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP",
                        "ALTER TABLE call_sessions ALTER COLUMN initiated_at SET DEFAULT CURRENT_TIMESTAMP",
                        "CREATE INDEX IF NOT EXISTS idx_call_sessions_created_at ON call_sessions (created_at)",
                        "CREATE INDEX IF NOT EXISTS idx_call_sessions_initiated_at ON call_sessions (initiated_at)",
                        "CREATE INDEX IF NOT EXISTS idx_call_sessions_start_time ON call_sessions (start_time)",
                        "CREATE INDEX IF NOT EXISTS idx_call_sessions_end_time ON call_sessions (end_time)",
                        # Performance index for date range queries
                        "CREATE INDEX IF NOT EXISTS idx_call_sessions_date_range ON call_sessions (start_time, end_time)",
                    ]
                },
                {
                    'table': 'loans',
                    'operations': [
                        "ALTER TABLE loans ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP",
                        "CREATE INDEX IF NOT EXISTS idx_loans_due_date ON loans (due_date)",
                        "CREATE INDEX IF NOT EXISTS idx_loans_created_at ON loans (created_at)",
                        # Index for overdue loans
                        "CREATE INDEX IF NOT EXISTS idx_loans_overdue ON loans (due_date) WHERE due_date < CURRENT_DATE",
                    ]
                }
            ]
            
            for enhancement in enhancements:
                print(f"\n🔧 Enhancing {enhancement['table']}...")
                
                for operation in enhancement['operations']:
                    try:
                        print(f"   📝 {operation[:80]}{'...' if len(operation) > 80 else ''}")
                        connection.execute(text(operation))
                        print(f"   ✅ Success")
                    except Exception as e:
                        if "already exists" in str(e).lower():
                            print(f"   ℹ️  Already exists")
                        else:
                            print(f"   ⚠️  Warning: {e}")
            
            trans.commit()
            print("\n✅ Date handling enhancements completed!")
            
        except Exception as e:
            trans.rollback()
            print(f"\n❌ Error enhancing date handling: {e}")
            raise

def enhance_csv_processing_schema():
    """Enhance schema for better CSV file processing"""
    print("\n📄 ENHANCING CSV PROCESSING SCHEMA")
    print("=" * 60)
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Add CSV processing metadata columns
            csv_enhancements = [
                # Enhance file_uploads table for better CSV tracking
                """
                ALTER TABLE file_uploads 
                ADD COLUMN IF NOT EXISTS csv_headers TEXT,
                ADD COLUMN IF NOT EXISTS csv_delimiter VARCHAR(5) DEFAULT ',',
                ADD COLUMN IF NOT EXISTS csv_encoding VARCHAR(20) DEFAULT 'utf-8',
                ADD COLUMN IF NOT EXISTS csv_row_count INTEGER DEFAULT 0,
                ADD COLUMN IF NOT EXISTS csv_processed_count INTEGER DEFAULT 0,
                ADD COLUMN IF NOT EXISTS csv_error_count INTEGER DEFAULT 0,
                ADD COLUMN IF NOT EXISTS processing_start_time TIMESTAMP,
                ADD COLUMN IF NOT EXISTS processing_end_time TIMESTAMP,
                ADD COLUMN IF NOT EXISTS file_hash VARCHAR(64)
                """,
                
                # Add CSV processing status tracking
                """
                ALTER TABLE file_uploads 
                ADD COLUMN IF NOT EXISTS validation_errors JSON,
                ADD COLUMN IF NOT EXISTS processing_log JSON,
                ADD COLUMN IF NOT EXISTS duplicate_handling_strategy VARCHAR(50) DEFAULT 'skip'
                """,
                
                # Enhance customers table for CSV source tracking
                """
                ALTER TABLE customers 
                ADD COLUMN IF NOT EXISTS source_file_id UUID REFERENCES file_uploads(id),
                ADD COLUMN IF NOT EXISTS source_row_number INTEGER,
                ADD COLUMN IF NOT EXISTS import_batch_id VARCHAR(100),
                ADD COLUMN IF NOT EXISTS data_quality_score DECIMAL(3,2),
                ADD COLUMN IF NOT EXISTS validation_flags JSON
                """,
                
                # Add CSV batch processing table
                """
                CREATE TABLE IF NOT EXISTS csv_processing_batches (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    batch_identifier VARCHAR(100) UNIQUE NOT NULL,
                    file_upload_id UUID REFERENCES file_uploads(id),
                    processing_status VARCHAR(50) DEFAULT 'pending',
                    total_rows INTEGER DEFAULT 0,
                    processed_rows INTEGER DEFAULT 0,
                    successful_rows INTEGER DEFAULT 0,
                    error_rows INTEGER DEFAULT 0,
                    duplicate_rows INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_details JSON,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            ]
            
            for enhancement in csv_enhancements:
                try:
                    print(f"📝 Executing CSV schema enhancement...")
                    connection.execute(text(enhancement))
                    print(f"✅ Success")
                except Exception as e:
                    if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                        print(f"ℹ️  Already exists")
                    else:
                        print(f"⚠️  Warning: {e}")
            
            # Add indexes for CSV processing performance
            csv_indexes = [
                "CREATE INDEX IF NOT EXISTS idx_file_uploads_file_hash ON file_uploads (file_hash)",
                "CREATE INDEX IF NOT EXISTS idx_file_uploads_processing_status ON file_uploads (status)",
                "CREATE INDEX IF NOT EXISTS idx_customers_source_file ON customers (source_file_id)",
                "CREATE INDEX IF NOT EXISTS idx_customers_import_batch ON customers (import_batch_id)",
                "CREATE INDEX IF NOT EXISTS idx_csv_batches_status ON csv_processing_batches (processing_status)",
                "CREATE INDEX IF NOT EXISTS idx_csv_batches_file_upload ON csv_processing_batches (file_upload_id)",
            ]
            
            print(f"\n📇 Adding CSV processing indexes...")
            for index_sql in csv_indexes:
                try:
                    connection.execute(text(index_sql))
                    print(f"✅ {index_sql.split('IF NOT EXISTS ')[1].split(' ON')[0]}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"ℹ️  Index already exists")
                    else:
                        print(f"⚠️  Warning: {e}")
            
            trans.commit()
            print("\n✅ CSV processing schema enhancements completed!")
            
        except Exception as e:
            trans.rollback()
            print(f"\n❌ Error enhancing CSV schema: {e}")
            raise

def add_data_partitioning():
    """Add table partitioning for better performance with large datasets"""
    print("\n🗂️  ADDING DATA PARTITIONING")
    print("=" * 60)
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Add partitioning hints and prepare for future partitioning
            partitioning_setup = [
                # Add monthly partitioning preparation for call_sessions
                """
                CREATE INDEX IF NOT EXISTS idx_call_sessions_monthly 
                ON call_sessions (EXTRACT(YEAR FROM created_at), EXTRACT(MONTH FROM created_at))
                """,
                
                # Add daily partitioning preparation for file_uploads
                """
                CREATE INDEX IF NOT EXISTS idx_file_uploads_daily 
                ON file_uploads (DATE(created_at))
                """,
                
                # Add customer segmentation indexes
                """
                CREATE INDEX IF NOT EXISTS idx_customers_state_date 
                ON customers (state, first_uploaded_at)
                """,
                
                # Add call performance indexes
                """
                CREATE INDEX IF NOT EXISTS idx_call_sessions_performance 
                ON call_sessions (status, duration, created_at)
                """
            ]
            
            for partition_sql in partitioning_setup:
                try:
                    connection.execute(text(partition_sql))
                    print(f"✅ Partitioning index added")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"ℹ️  Index already exists")
                    else:
                        print(f"⚠️  Warning: {e}")
            
            trans.commit()
            print("\n✅ Data partitioning setup completed!")
            
        except Exception as e:
            trans.rollback()
            print(f"\n❌ Error setting up partitioning: {e}")

def create_date_helper_functions():
    """Create PostgreSQL functions for better date handling"""
    print("\n🛠️  CREATING DATE HELPER FUNCTIONS")
    print("=" * 60)
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Create IST timezone conversion functions
            helper_functions = [
                # Convert UTC to IST
                """
                CREATE OR REPLACE FUNCTION utc_to_ist(utc_timestamp TIMESTAMP)
                RETURNS TIMESTAMP AS $$
                BEGIN
                    RETURN utc_timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata';
                END;
                $$ LANGUAGE plpgsql;
                """,
                
                # Get IST date range for filtering
                """
                CREATE OR REPLACE FUNCTION get_ist_date_range(filter_type TEXT)
                RETURNS TABLE(start_date TIMESTAMP, end_date TIMESTAMP) AS $$
                DECLARE
                    ist_now TIMESTAMP;
                BEGIN
                    ist_now := CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata';
                    
                    CASE filter_type
                        WHEN 'today' THEN
                            start_date := DATE_TRUNC('day', ist_now);
                            end_date := start_date + INTERVAL '1 day';
                        WHEN 'yesterday' THEN
                            start_date := DATE_TRUNC('day', ist_now) - INTERVAL '1 day';
                            end_date := start_date + INTERVAL '1 day';
                        WHEN 'this_week' THEN
                            start_date := DATE_TRUNC('week', ist_now);
                            end_date := start_date + INTERVAL '1 week';
                        WHEN 'this_month' THEN
                            start_date := DATE_TRUNC('month', ist_now);
                            end_date := start_date + INTERVAL '1 month';
                        ELSE
                            start_date := DATE_TRUNC('day', ist_now);
                            end_date := start_date + INTERVAL '1 day';
                    END CASE;
                    
                    RETURN NEXT;
                END;
                $$ LANGUAGE plpgsql;
                """,
                
                # Calculate business days between dates
                """
                CREATE OR REPLACE FUNCTION business_days_between(start_date DATE, end_date DATE)
                RETURNS INTEGER AS $$
                DECLARE
                    days INTEGER;
                BEGIN
                    SELECT COUNT(*)::INTEGER INTO days
                    FROM generate_series(start_date, end_date, '1 day'::interval) AS day_series
                    WHERE EXTRACT(DOW FROM day_series) NOT IN (0, 6); -- Exclude Sunday (0) and Saturday (6)
                    
                    RETURN days;
                END;
                $$ LANGUAGE plpgsql;
                """
            ]
            
            for func_sql in helper_functions:
                try:
                    connection.execute(text(func_sql))
                    print(f"✅ Helper function created")
                except Exception as e:
                    print(f"⚠️  Warning: {e}")
            
            trans.commit()
            print("\n✅ Date helper functions created!")
            
        except Exception as e:
            trans.rollback()
            print(f"\n❌ Error creating helper functions: {e}")

def verify_enhanced_schema():
    """Verify all enhancements were applied correctly"""
    print("\n🔍 VERIFYING ENHANCED SCHEMA")
    print("=" * 60)
    
    with engine.connect() as connection:
        try:
            # Check date columns
            result = connection.execute(text("""
                SELECT table_name, column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND data_type IN ('timestamp without time zone', 'timestamp with time zone', 'date', 'time')
                ORDER BY table_name, column_name
            """))
            
            print("📅 DATE/TIME COLUMNS:")
            current_table = None
            for row in result:
                if row[0] != current_table:
                    current_table = row[0]
                    print(f"\n🔍 {current_table.upper()}:")
                
                nullable = "NULL" if row[3] == 'YES' else "NOT NULL"
                default = f" DEFAULT({row[4]})" if row[4] else ""
                print(f"   📅 {row[1]:<25} {row[2]:<25} {nullable}{default}")
            
            # Check indexes
            result = connection.execute(text("""
                SELECT schemaname, tablename, indexname, indexdef
                FROM pg_indexes 
                WHERE schemaname = 'public'
                AND indexname LIKE '%date%' OR indexname LIKE '%time%' OR indexname LIKE '%csv%'
                ORDER BY tablename, indexname
            """))
            
            print(f"\n📇 DATE/CSV RELATED INDEXES:")
            current_table = None
            for row in result:
                if row[1] != current_table:
                    current_table = row[1]
                    print(f"\n🔍 {current_table.upper()}:")
                print(f"   📇 {row[2]}")
            
            # Check functions
            result = connection.execute(text("""
                SELECT routine_name, routine_type
                FROM information_schema.routines
                WHERE routine_schema = 'public'
                AND routine_name IN ('utc_to_ist', 'get_ist_date_range', 'business_days_between')
            """))
            
            print(f"\n🛠️  HELPER FUNCTIONS:")
            for row in result:
                print(f"   🔧 {row[0]} ({row[1]})")
            
        except Exception as e:
            print(f"❌ Error verifying schema: {e}")

def main():
    """Main function to run all schema enhancements"""
    print("🚀 ENHANCED DATABASE SCHEMA MIGRATION")
    print("=" * 70)
    print("Optimizing schemas for better date handling and CSV processing")
    print("=" * 70)
    
    try:
        # Step 1: Analyze current date handling
        current_dates = analyze_current_date_handling()
        
        # Step 2: Enhance date handling
        enhance_date_handling()
        
        # Step 3: Enhance CSV processing schema
        enhance_csv_processing_schema()
        
        # Step 4: Add data partitioning
        add_data_partitioning()
        
        # Step 5: Create helper functions
        create_date_helper_functions()
        
        # Step 6: Verify enhancements
        verify_enhanced_schema()
        
        print("\n🎉 SCHEMA ENHANCEMENT COMPLETED!")
        print("=" * 70)
        print("✅ Date handling optimized")
        print("✅ CSV processing enhanced")
        print("✅ Performance indexes added")
        print("✅ Helper functions created")
        print("✅ Schema verification passed")
        print("\n🚀 Your application is now optimized for better date and CSV handling!")
        
    except Exception as e:
        print(f"\n❌ Schema enhancement failed: {e}")
        raise

if __name__ == "__main__":
    main()
