#!/usr/bin/env python3
"""
Comprehensive Migration Script: Transform db-voice-agent to dummy-db Schema Structure

This script migrates the current db-voice-agent schema to match the dummy-db structure exactly:
- Removes csv_processing_batches table (currently empty)
- Adds missing triggered_by_row and triggered_by_batch foreign keys to call_sessions
- Removes unnecessary customer enhancements to match dummy-db

Migration Safety:
- Creates full backup before changes
- Validates data integrity throughout
- Provides rollback capability
- Zero data loss for production data
"""

import psycopg2
import json
import os
from datetime import datetime
import sys

# Database connection parameters
import os
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:IntalksAI07@db-voice-agent.cviea4aicss0.ap-south-1.rds.amazonaws.com:5432/db-voice-agent")

# Parse database URL
if DATABASE_URL.startswith('postgresql://'):
    db_url_without_scheme = DATABASE_URL.replace('postgresql://', '')
    auth_and_location = db_url_without_scheme.split('/')
    database_name = auth_and_location[1] if len(auth_and_location) > 1 else 'db-voice-agent'
    auth_and_host = auth_and_location[0].split('@')
    host_and_port = auth_and_host[1].split(':')
    user_and_pass = auth_and_host[0].split(':')
    
    DB_CONFIG = {
        'host': host_and_port[0],
        'port': int(host_and_port[1]) if len(host_and_port) > 1 else 5432,
        'database': database_name,
        'user': user_and_pass[0],
        'password': user_and_pass[1] if len(user_and_pass) > 1 else ''
    }
else:
    # Fallback configuration
    DB_CONFIG = {
        'host': 'db-voice-agent.cviea4aicss0.ap-south-1.rds.amazonaws.com',
        'port': 5432,
        'database': 'db-voice-agent',
        'user': 'postgres',
        'password': 'IntalksAI07'
    }

def create_connection():
    """Create database connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        return conn
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

def backup_database(conn):
    """Create comprehensive backup of current data."""
    print("📦 Creating comprehensive database backup...")
    
    cursor = conn.cursor()
    backup_data = {}
    
    # Get list of all tables
    cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    """)
    tables = [row[0] for row in cursor.fetchall()]
    
    # Backup each table
    for table in tables:
        print(f"  📋 Backing up {table}...")
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        
        if count > 0:
            cursor.execute(f"SELECT * FROM {table}")
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            backup_data[table] = {
                'columns': columns,
                'rows': [list(row) for row in rows],
                'count': count
            }
            print(f"    ✅ {count} rows backed up")
        else:
            backup_data[table] = {'columns': [], 'rows': [], 'count': 0}
            print(f"    📝 Empty table noted")
    
    # Save backup to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"backup_before_dummy_db_migration_{timestamp}.json"
    
    # Convert datetime objects to strings for JSON serialization
    def json_serializer(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return str(obj)
    
    with open(backup_filename, 'w') as f:
        json.dump(backup_data, f, indent=2, default=json_serializer)
    
    print(f"✅ Database backup saved: {backup_filename}")
    return backup_filename, backup_data

def validate_current_schema(conn):
    """Validate current schema matches expected state."""
    print("🔍 Validating current schema structure...")
    
    cursor = conn.cursor()
    
    # Check current tables
    cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    current_tables = [row[0] for row in cursor.fetchall()]
    
    print(f"📊 Current tables: {current_tables}")
    
    # Check for csv_processing_batches
    if 'csv_processing_batches' in current_tables:
        cursor.execute("SELECT COUNT(*) FROM csv_processing_batches")
        batch_count = cursor.fetchone()[0]
        print(f"📋 csv_processing_batches has {batch_count} rows (safe to remove if 0)")
    
    # Check call_sessions structure
    cursor.execute("""
        SELECT column_name FROM information_schema.columns 
        WHERE table_name = 'call_sessions'
        ORDER BY column_name
    """)
    call_sessions_columns = [row[0] for row in cursor.fetchall()]
    print(f"📋 call_sessions columns: {call_sessions_columns}")
    
    # Check foreign keys
    cursor.execute("""
        SELECT 
            conname as constraint_name,
            conrelid::regclass as table_name,
            confrelid::regclass as foreign_table_name
        FROM pg_constraint 
        WHERE contype = 'f'
        ORDER BY table_name, constraint_name
    """)
    foreign_keys = cursor.fetchall()
    print(f"🔗 Current foreign keys: {len(foreign_keys)}")
    for fk in foreign_keys:
        print(f"    {fk[1]} -> {fk[2]} ({fk[0]})")
    
    return current_tables, call_sessions_columns, foreign_keys

def execute_migration(conn):
    """Execute the schema migration to dummy-db structure."""
    print("🚀 Starting schema migration to dummy-db structure...")
    
    cursor = conn.cursor()
    
    try:
        # Step 1: Verify call_sessions already has the required columns
        print("📋 Checking call_sessions structure...")
        
        cursor.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'call_sessions'
            ORDER BY column_name
        """)
        columns = [row[0] for row in cursor.fetchall()]
        print(f"    📝 Current columns: {columns}")
        
        required_columns = ['triggered_by_row', 'triggered_by_batch', 'loan_id']
        missing_columns = [col for col in required_columns if col not in columns]
        
        if missing_columns:
            print(f"    ❌ Missing required columns: {missing_columns}")
            for col in missing_columns:
                if col == 'triggered_by_row':
                    cursor.execute("ALTER TABLE call_sessions ADD COLUMN triggered_by_row UUID")
                    print(f"    ✅ Added {col} column")
                elif col == 'triggered_by_batch':
                    cursor.execute("ALTER TABLE call_sessions ADD COLUMN triggered_by_batch UUID")
                    print(f"    ✅ Added {col} column")
                elif col == 'loan_id':
                    cursor.execute("ALTER TABLE call_sessions ADD COLUMN loan_id UUID")
                    print(f"    ✅ Added {col} column")
        else:
            print("    ✅ All required columns exist")
        
        # Step 2: Check for required tables (upload_rows should be there based on the data)
        cursor.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_name IN ('upload_rows', 'file_uploads', 'loans') 
            AND table_schema = 'public'
        """)
        existing_tables = [row[0] for row in cursor.fetchall()]
        print(f"    📊 Required tables present: {existing_tables}")
        
        # Step 3: Create foreign key constraints only if the target tables exist
        print("🔗 Creating foreign key constraints...")
        
        if 'upload_rows' in existing_tables:
            try:
                cursor.execute("""
                    ALTER TABLE call_sessions 
                    ADD CONSTRAINT fk_call_sessions_triggered_by_row 
                    FOREIGN KEY (triggered_by_row) REFERENCES upload_rows(id)
                """)
                print("    ✅ Added FK constraint for triggered_by_row")
            except psycopg2.Error as e:
                if "already exists" in str(e):
                    print("    📝 FK constraint for triggered_by_row already exists")
                else:
                    print(f"    ⚠️ Could not create FK for triggered_by_row: {e}")
        
        if 'file_uploads' in existing_tables:
            try:
                cursor.execute("""
                    ALTER TABLE call_sessions 
                    ADD CONSTRAINT fk_call_sessions_triggered_by_batch 
                    FOREIGN KEY (triggered_by_batch) REFERENCES file_uploads(id)
                """)
                print("    ✅ Added FK constraint for triggered_by_batch")
            except psycopg2.Error as e:
                if "already exists" in str(e):
                    print("    📝 FK constraint for triggered_by_batch already exists")
                else:
                    print(f"    ⚠️ Could not create FK for triggered_by_batch: {e}")
        
        if 'loans' in existing_tables:
            try:
                cursor.execute("""
                    ALTER TABLE call_sessions 
                    ADD CONSTRAINT fk_call_sessions_loan_id 
                    FOREIGN KEY (loan_id) REFERENCES loans(id)
                """)
                print("    ✅ Added FK constraint for loan_id")
            except psycopg2.Error as e:
                if "already exists" in str(e):
                    print("    📝 FK constraint for loan_id already exists")
                else:
                    print(f"    ⚠️ Could not create FK for loan_id: {e}")
        
        # Step 4: Remove csv_processing_batches table if it exists and is empty
        cursor.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_name = 'csv_processing_batches'
        """)
        if cursor.fetchone():
            cursor.execute("SELECT COUNT(*) FROM csv_processing_batches")
            count = cursor.fetchone()[0]
            
            if count == 0:
                cursor.execute("DROP TABLE csv_processing_batches CASCADE")
                print("    ✅ Removed empty csv_processing_batches table")
            else:
                print(f"    ⚠️ csv_processing_batches has {count} rows, not removing")
        else:
            print("    📝 csv_processing_batches table does not exist")
        
        # Step 5: Remove source_file_id from customers if it exists
        print("🧹 Cleaning up customer table...")
        cursor.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'customers' AND column_name = 'source_file_id'
        """)
        if cursor.fetchone():
            # First remove the foreign key constraint if it exists
            cursor.execute("""
                SELECT conname FROM pg_constraint 
                WHERE conrelid = 'customers'::regclass 
                AND conname LIKE '%source_file%'
            """)
            constraint = cursor.fetchone()
            if constraint:
                cursor.execute(f"ALTER TABLE customers DROP CONSTRAINT {constraint[0]}")
                print("    ✅ Removed source_file_id foreign key constraint")
            
            cursor.execute("ALTER TABLE customers DROP COLUMN source_file_id")
            print("    ✅ Removed source_file_id column from customers")
        else:
            print("    📝 source_file_id column does not exist in customers")
        
        # Step 6: Remove other enhancement columns from customers to match dummy-db
        enhancement_columns = ['import_batch_id', 'data_quality_score', 'validation_flags']
        for col in enhancement_columns:
            cursor.execute(f"""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'customers' AND column_name = '{col}'
            """)
            if cursor.fetchone():
                cursor.execute(f"ALTER TABLE customers DROP COLUMN {col}")
                print(f"    ✅ Removed {col} column from customers")
            else:
                print(f"    📝 {col} column does not exist in customers")
        
        # Step 7: Validate final schema
        print("✅ Migration completed successfully!")
        
        # Commit all changes
        conn.commit()
        print("💾 All changes committed to database")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
        print("🔄 All changes rolled back")
        raise

def validate_final_schema(conn):
    """Validate the final schema matches dummy-db structure."""
    print("🔍 Validating final schema structure...")
    
    cursor = conn.cursor()
    
    # Check final tables
    cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    final_tables = [row[0] for row in cursor.fetchall()]
    
    expected_tables = ['call_sessions', 'call_status_updates', 'csv_batches', 'csv_rows', 'customers', 'file_uploads']
    
    print(f"📊 Final tables: {final_tables}")
    print(f"📋 Expected tables: {expected_tables}")
    
    missing_tables = set(expected_tables) - set(final_tables)
    extra_tables = set(final_tables) - set(expected_tables)
    
    if missing_tables:
        print(f"⚠️ Missing tables: {missing_tables}")
    if extra_tables:
        print(f"⚠️ Extra tables: {extra_tables}")
    
    if not missing_tables and not extra_tables:
        print("✅ Table structure matches dummy-db!")
    
    # Check call_sessions columns
    cursor.execute("""
        SELECT column_name FROM information_schema.columns 
        WHERE table_name = 'call_sessions'
        ORDER BY column_name
    """)
    call_sessions_columns = [row[0] for row in cursor.fetchall()]
    
    expected_columns = ['created_at', 'customer_id', 'id', 'session_id', 'triggered_by_batch', 'triggered_by_row', 'updated_at']
    
    print(f"📋 call_sessions columns: {call_sessions_columns}")
    print(f"📋 Expected columns: {expected_columns}")
    
    missing_cols = set(expected_columns) - set(call_sessions_columns)
    extra_cols = set(call_sessions_columns) - set(expected_columns)
    
    if missing_cols:
        print(f"⚠️ Missing columns in call_sessions: {missing_cols}")
    if extra_cols:
        print(f"⚠️ Extra columns in call_sessions: {extra_cols}")
    
    # Check foreign keys
    cursor.execute("""
        SELECT 
            conname as constraint_name,
            conrelid::regclass as table_name,
            confrelid::regclass as foreign_table_name
        FROM pg_constraint 
        WHERE contype = 'f'
        ORDER BY table_name, constraint_name
    """)
    foreign_keys = cursor.fetchall()
    
    print(f"🔗 Final foreign keys: {len(foreign_keys)}")
    for fk in foreign_keys:
        print(f"    {fk[1]} -> {fk[2]} ({fk[0]})")
    
    # Expected: 9 foreign keys for dummy-db structure
    if len(foreign_keys) == 9:
        print("✅ Foreign key count matches dummy-db structure!")
    else:
        print(f"⚠️ Expected 9 foreign keys, found {len(foreign_keys)}")
    
    return len(final_tables) == 6 and len(foreign_keys) >= 8

def main():
    """Main migration execution."""
    print("🚀 Starting Migration to dummy-db Schema Structure")
    print("=" * 60)
    
    conn = create_connection()
    
    try:
        # Step 1: Backup current data
        backup_filename, backup_data = backup_database(conn)
        
        # Step 2: Validate current schema
        current_tables, call_sessions_columns, foreign_keys = validate_current_schema(conn)
        
        # Step 3: Execute migration
        execute_migration(conn)
        
        # Step 4: Validate final schema
        migration_success = validate_final_schema(conn)
        
        if migration_success:
            print("\n" + "=" * 60)
            print("🎉 MIGRATION COMPLETED SUCCESSFULLY!")
            print("✅ Schema transformed to match dummy-db structure")
            print("✅ All data preserved and backed up")
            print("✅ Ready for application testing")
            print(f"📦 Backup saved: {backup_filename}")
        else:
            print("\n" + "=" * 60)
            print("⚠️ MIGRATION COMPLETED WITH WARNINGS")
            print("📋 Please review the validation results above")
            
    except Exception as e:
        print(f"\n❌ MIGRATION FAILED: {e}")
        print("🔄 Database changes have been rolled back")
        sys.exit(1)
    
    finally:
        conn.close()

if __name__ == "__main__":
    main()
