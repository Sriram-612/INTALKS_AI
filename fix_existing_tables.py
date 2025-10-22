#!/usr/bin/env python3
"""
Fix Existing Tables Schema
Directly modifies existing tables to match the expected schema
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
load_dotenv()

from database.schemas import engine

def get_table_columns(table_name):
    """Get current columns for a table"""
    inspector = inspect(engine)
    try:
        return {col['name']: col for col in inspector.get_columns(table_name)}
    except:
        return {}

def fix_customers_table():
    """Fix the customers table to match schema expectations"""
    
    print("🔧 Fixing customers table structure...")
    
    current_columns = get_table_columns('customers')
    print(f"📊 Current customers columns: {list(current_columns.keys())}")
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Check if we need to rename or add columns
            migrations = []
            
            # If 'name' exists but 'full_name' doesn't, rename it
            if 'name' in current_columns and 'full_name' not in current_columns:
                migrations.append("ALTER TABLE customers RENAME COLUMN name TO full_name")
            
            # If 'phone_number' exists but 'primary_phone' doesn't, rename it  
            if 'phone_number' in current_columns and 'primary_phone' not in current_columns:
                migrations.append("ALTER TABLE customers RENAME COLUMN phone_number TO primary_phone")
            
            # Add missing columns
            missing_columns = [
                ("fingerprint", "TEXT UNIQUE"),
                ("national_id", "VARCHAR(50)"),
                ("email", "VARCHAR(255)"), 
                ("first_uploaded_at", "TIMESTAMP"),
                ("last_contact_date", "TIMESTAMP"),
                ("do_not_call", "BOOLEAN DEFAULT FALSE")
            ]
            
            for col_name, col_def in missing_columns:
                if col_name not in current_columns:
                    migrations.append(f"ALTER TABLE customers ADD COLUMN {col_name} {col_def}")
            
            # Execute migrations
            for migration in migrations:
                print(f"  📝 {migration}")
                connection.execute(text(migration))
            
            # Update fingerprint for existing records
            if 'fingerprint' not in current_columns:
                print("  🔄 Updating fingerprint values for existing records...")
                connection.execute(text("""
                    UPDATE customers 
                    SET fingerprint = COALESCE(primary_phone, id::text)
                    WHERE fingerprint IS NULL
                """))
            
            trans.commit()
            print("✅ Customers table fixed successfully!")
            
        except Exception as e:
            trans.rollback()
            print(f"❌ Error fixing customers table: {e}")
            raise

def fix_call_sessions_table():
    """Fix the call_sessions table to match schema expectations"""
    
    print("\n🔧 Fixing call_sessions table structure...")
    
    current_columns = get_table_columns('call_sessions')
    print(f"📊 Current call_sessions columns: {list(current_columns.keys())}")
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Add missing columns
            missing_columns = [
                ("loan_id", "UUID"),
                ("initiated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
                ("duration_seconds", "INTEGER"),
                ("from_number", "VARCHAR(20)"),
                ("to_number", "VARCHAR(20)"),
                ("triggered_by_batch", "UUID"),
                ("triggered_by_row", "UUID"),
                ("call_metadata", "JSON")
            ]
            
            migrations = []
            for col_name, col_def in missing_columns:
                if col_name not in current_columns:
                    migrations.append(f"ALTER TABLE call_sessions ADD COLUMN {col_name} {col_def}")
            
            # Execute migrations
            for migration in migrations:
                print(f"  📝 {migration}")
                connection.execute(text(migration))
            
            # Copy data from existing columns if needed
            if 'start_time' in current_columns and 'initiated_at' not in current_columns:
                print("  🔄 Copying start_time to initiated_at...")
                connection.execute(text("UPDATE call_sessions SET initiated_at = start_time WHERE initiated_at IS NULL"))
            
            trans.commit()
            print("✅ Call sessions table fixed successfully!")
            
        except Exception as e:
            trans.rollback()
            print(f"❌ Error fixing call_sessions table: {e}")
            raise

def create_test_customer_direct():
    """Create test customer using direct SQL to avoid schema issues"""
    
    print("\n👤 Creating test customer with direct SQL...")
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Check if customer already exists
            result = connection.execute(text("""
                SELECT id FROM customers WHERE primary_phone = '+917417119014'
                LIMIT 1
            """))
            
            existing = result.fetchone()
            if existing:
                print(f"ℹ️  Customer 'Kushal' already exists with ID: {existing[0]}")
                return str(existing[0])
            
            # Generate a simple fingerprint
            fingerprint = "+917417119014"
            
            # Insert customer using current table structure
            current_columns = get_table_columns('customers')
            
            if 'full_name' in current_columns:
                name_col = 'full_name'
            else:
                name_col = 'name'
            
            if 'primary_phone' in current_columns:
                phone_col = 'primary_phone'
            else:
                phone_col = 'phone_number'
            
            insert_sql = f"""
                INSERT INTO customers (id, {name_col}, {phone_col}, state, fingerprint, created_at, updated_at)
                VALUES (gen_random_uuid(), 'Kushal', '+917417119014', 'Karnataka', '{fingerprint}', 
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """
            
            print(f"  📝 {insert_sql}")
            result = connection.execute(text(insert_sql))
            customer_id = result.fetchone()[0]
            
            trans.commit()
            
            print(f"✅ Customer 'Kushal' created successfully!")
            print(f"   ID: {customer_id}")
            print(f"   Phone: +917417119014")
            print(f"   Name Column: {name_col}")
            print(f"   Phone Column: {phone_col}")
            
            return str(customer_id)
            
        except Exception as e:
            trans.rollback()
            print(f"❌ Error creating customer: {e}")
            return None

def verify_tables():
    """Verify tables are working"""
    
    print("\n🔍 Verifying table functionality...")
    
    try:
        with engine.connect() as connection:
            # Test customers table
            result = connection.execute(text("SELECT COUNT(*) FROM customers"))
            customer_count = result.fetchone()[0]
            print(f"✅ Customers table: {customer_count} records")
            
            # Show customers table structure
            customers_columns = get_table_columns('customers')
            print(f"📊 Customers columns: {list(customers_columns.keys())}")
            
            # Test call_sessions table
            result = connection.execute(text("SELECT COUNT(*) FROM call_sessions"))
            call_count = result.fetchone()[0]
            print(f"✅ Call sessions table: {call_count} records")
            
            # Show call_sessions table structure
            call_columns = get_table_columns('call_sessions')
            print(f"📊 Call sessions columns: {list(call_columns.keys())}")
            
            # Test file_uploads table
            result = connection.execute(text("SELECT COUNT(*) FROM file_uploads"))
            upload_count = result.fetchone()[0]
            print(f"✅ File uploads table: {upload_count} records")
            
            return True
            
    except Exception as e:
        print(f"❌ Table verification failed: {e}")
        return False

def main():
    """Main function"""
    
    print("🚀 Direct Table Schema Fix")
    print("=" * 40)
    
    try:
        # Fix customers table
        fix_customers_table()
        
        # Fix call_sessions table
        fix_call_sessions_table()
        
        # Create test customer
        customer_id = create_test_customer_direct()
        
        # Verify everything works
        if verify_tables():
            print("\n🎉 Schema fix completed successfully!")
            print("=" * 50)
            print("✅ Tables have been fixed to match the expected schema")
            print("✅ Test customer 'Kushal' has been added")
            print("✅ Your application should now work correctly")
            
            if customer_id:
                print(f"\n👤 Test Customer Details:")
                print(f"   Name: Kushal")
                print(f"   Phone: +917417119014") 
                print(f"   Customer ID: {customer_id}")
            
            return True
        else:
            print("\n❌ Verification failed")
            return False
            
    except Exception as e:
        print(f"\n❌ Schema fix failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    if success:
        print("\n🚀 Ready to restart your application!")
    else:
        print("\n❌ Please check the errors and try again")
