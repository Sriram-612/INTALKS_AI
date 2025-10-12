#!/usr/bin/env python3
"""
Schema Analysis and Migration to Dummy-DB Structure
Analyzes current db-voice-agent schema and creates migration plan to match dummy-db
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import text, inspect

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
load_dotenv()

from database.schemas import engine

def analyze_current_schema():
    """Analyze current db-voice-agent schema structure"""
    print("🔍 CURRENT DB-VOICE-AGENT SCHEMA ANALYSIS")
    print("=" * 60)
    
    inspector = inspect(engine)
    
    # Get all tables
    tables = inspector.get_table_names()
    print(f"📊 Current Tables ({len(tables)}):")
    for table in sorted(tables):
        print(f"   📋 {table}")
    
    # Analyze foreign keys
    print(f"\n🔗 Current Foreign Key Relationships:")
    total_fks = 0
    
    for table_name in sorted(tables):
        foreign_keys = inspector.get_foreign_keys(table_name)
        if foreign_keys:
            for fk in foreign_keys:
                total_fks += 1
                constrained_col = fk['constrained_columns'][0]
                referred_table = fk['referred_table']
                referred_col = fk['referred_columns'][0]
                print(f"   🔗 {table_name}.{constrained_col} → {referred_table}.{referred_col}")
    
    print(f"\n📊 Total Foreign Keys: {total_fks}")
    
    # Get row counts
    print(f"\n📈 Current Row Counts:")
    with engine.connect() as connection:
        for table in sorted(tables):
            try:
                result = connection.execute(text(f'SELECT COUNT(*) FROM {table}'))
                count = result.scalar()
                print(f"   📊 {table:<25} {count:>6} rows")
            except Exception as e:
                print(f"   ❌ {table:<25} Error: {e}")

def create_dummy_db_target_schema():
    """Define the target dummy-db schema structure"""
    print("\n🎯 TARGET DUMMY-DB SCHEMA STRUCTURE")
    print("=" * 60)
    
    target_schema = {
        "tables": [
            "call_sessions",
            "call_status_updates", 
            "customers",
            "file_uploads",
            "loans",
            "upload_rows"
        ],
        "foreign_keys": [
            "call_sessions.loan_id → loans.id",
            "call_sessions.triggered_by_row → upload_rows.id",
            "call_sessions.triggered_by_batch → file_uploads.id",
            "call_sessions.customer_id → customers.id",
            "call_status_updates.call_session_id → call_sessions.id",
            "loans.customer_id → customers.id",
            "upload_rows.match_customer_id → customers.id",
            "upload_rows.match_loan_id → loans.id",
            "upload_rows.file_upload_id → file_uploads.id"
        ]
    }
    
    print(f"📊 Target Tables ({len(target_schema['tables'])}):")
    for table in target_schema['tables']:
        print(f"   📋 {table}")
    
    print(f"\n🔗 Target Foreign Keys ({len(target_schema['foreign_keys'])}):")
    for fk in target_schema['foreign_keys']:
        print(f"   🔗 {fk}")
    
    return target_schema

def identify_schema_differences():
    """Identify what needs to be changed to match dummy-db"""
    print("\n🔄 SCHEMA MIGRATION REQUIREMENTS")
    print("=" * 60)
    
    inspector = inspect(engine)
    current_tables = set(inspector.get_table_names())
    target_tables = {
        "call_sessions", "call_status_updates", "customers", 
        "file_uploads", "loans", "upload_rows"
    }
    
    # Tables to remove
    tables_to_remove = current_tables - target_tables
    if tables_to_remove:
        print("🗑️  TABLES TO REMOVE:")
        for table in tables_to_remove:
            print(f"   ❌ {table}")
    
    # Foreign Keys to add
    print("\n➕ FOREIGN KEYS TO ADD:")
    missing_fks = [
        ("call_sessions", "triggered_by_row", "upload_rows", "id"),
        ("call_sessions", "triggered_by_batch", "file_uploads", "id"),
        ("call_sessions", "loan_id", "loans", "id")
    ]
    
    for table, col, ref_table, ref_col in missing_fks:
        print(f"   ➕ {table}.{col} → {ref_table}.{ref_col}")
    
    # Foreign Keys to remove  
    print("\n➖ FOREIGN KEYS TO REMOVE:")
    fks_to_remove = [
        ("customers", "source_file_id", "file_uploads", "id"),
        ("csv_processing_batches", "file_upload_id", "file_uploads", "id")
    ]
    
    for table, col, ref_table, ref_col in fks_to_remove:
        print(f"   ➖ {table}.{col} → {ref_table}.{ref_col}")
    
    # Columns to add
    print("\n📝 COLUMNS TO ADD/VERIFY:")
    columns_to_add = [
        ("call_sessions", "triggered_by_row", "UUID", "REFERENCES upload_rows(id)"),
        ("call_sessions", "triggered_by_batch", "UUID", "REFERENCES file_uploads(id)"),
    ]
    
    for table, col, data_type, constraint in columns_to_add:
        print(f"   📝 {table}.{col} ({data_type}) {constraint}")
    
    # Columns to remove
    print("\n🗑️  COLUMNS TO REMOVE:")
    columns_to_remove = [
        ("customers", "source_file_id"),
        ("customers", "import_batch_id"),
        ("customers", "data_quality_score"),
        ("customers", "validation_flags")
    ]
    
    for table, col in columns_to_remove:
        print(f"   🗑️  {table}.{col}")

def check_data_dependencies():
    """Check what data might be affected by schema changes"""
    print("\n💾 DATA DEPENDENCY ANALYSIS")
    print("=" * 60)
    
    with engine.connect() as connection:
        try:
            # Check if csv_processing_batches has data
            result = connection.execute(text('SELECT COUNT(*) FROM csv_processing_batches'))
            csv_batch_count = result.scalar()
            print(f"📊 csv_processing_batches: {csv_batch_count} rows")
            if csv_batch_count > 0:
                print("   ⚠️  Data will be lost when dropping this table!")
            else:
                print("   ✅ Safe to drop - no data")
            
            # Check customers.source_file_id usage
            result = connection.execute(text('''
                SELECT COUNT(*) FROM customers 
                WHERE source_file_id IS NOT NULL
            '''))
            source_file_usage = result.scalar()
            print(f"📊 customers with source_file_id: {source_file_usage} rows")
            if source_file_usage > 0:
                print("   ⚠️  Data relationship will be lost!")
            else:
                print("   ✅ Safe to remove - no data relationships")
            
            # Check call_sessions for missing columns
            result = connection.execute(text('''
                SELECT 
                    COUNT(*) as total_calls,
                    COUNT(triggered_by_row) as with_triggered_row,
                    COUNT(triggered_by_batch) as with_triggered_batch
                FROM call_sessions
            '''))
            call_stats = result.fetchone()
            print(f"📊 call_sessions analysis:")
            print(f"   Total calls: {call_stats[0]}")
            print(f"   With triggered_by_row: {call_stats[1]}")
            print(f"   With triggered_by_batch: {call_stats[2]}")
            
        except Exception as e:
            print(f"❌ Error analyzing data dependencies: {e}")

def generate_migration_plan():
    """Generate step-by-step migration plan"""
    print("\n📋 MIGRATION EXECUTION PLAN")
    print("=" * 60)
    
    steps = [
        "1. 💾 Create full database backup",
        "2. 🛑 Stop application to prevent data corruption",
        "3. 📝 Add missing columns to call_sessions",
        "4. 🔗 Add missing foreign key constraints",
        "5. 🗑️  Remove unnecessary columns from customers",
        "6. 🗑️  Drop csv_processing_batches table",
        "7. 📊 Update database statistics",
        "8. 🔄 Update application code schemas",
        "9. 🧪 Test application functionality",
        "10. ✅ Verify performance and restart application"
    ]
    
    for step in steps:
        print(f"   {step}")
    
    print(f"\n⚠️  IMPORTANT CONSIDERATIONS:")
    print(f"   • Full backup is CRITICAL before starting")
    print(f"   • Application downtime will be required")
    print(f"   • Some data relationships will be lost")
    print(f"   • Thorough testing needed after migration")

def main():
    """Main analysis function"""
    print("🔍 SCHEMA MIGRATION ANALYSIS: DB-VOICE-AGENT → DUMMY-DB")
    print("=" * 70)
    print("Analyzing current schema and planning migration to match dummy-db structure")
    print("=" * 70)
    
    try:
        # Step 1: Analyze current schema
        analyze_current_schema()
        
        # Step 2: Define target schema
        target_schema = create_dummy_db_target_schema()
        
        # Step 3: Identify differences
        identify_schema_differences()
        
        # Step 4: Check data dependencies
        check_data_dependencies()
        
        # Step 5: Generate migration plan
        generate_migration_plan()
        
        print("\n🎉 ANALYSIS COMPLETED!")
        print("=" * 70)
        print("✅ Schema differences identified")
        print("✅ Data dependencies analyzed")
        print("✅ Migration plan generated")
        print("\n🚀 Ready to proceed with migration script creation!")
        
    except Exception as e:
        print(f"\n❌ Analysis failed: {e}")
        raise

if __name__ == "__main__":
    main()
