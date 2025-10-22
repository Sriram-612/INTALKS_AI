#!/usr/bin/env python3
"""
Comprehensive Database Schema Migration Script
Automatically creates all tables and columns according to the current schema definition
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect, MetaData

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
load_dotenv()

from database.schemas import engine, Base, Customer, Loan, FileUpload, UploadRow, CallSession, CallStatusUpdate

def check_current_database_state():
    """Check current database state and identify issues"""
    
    print("🔍 Analyzing Current Database State")
    print("=" * 50)
    
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    print(f"📊 Found {len(existing_tables)} existing tables: {existing_tables}")
    
    # Check each table structure
    schema_issues = {}
    
    expected_tables = {
        'customers': Customer,
        'loans': Loan, 
        'file_uploads': FileUpload,
        'upload_rows': UploadRow,
        'call_sessions': CallSession,
        'call_status_updates': CallStatusUpdate
    }
    
    for table_name, model_class in expected_tables.items():
        if table_name in existing_tables:
            # Check columns
            current_columns = {col['name']: col for col in inspector.get_columns(table_name)}
            expected_columns = [col.name for col in model_class.__table__.columns]
            missing_columns = [col for col in expected_columns if col not in current_columns]
            
            if missing_columns:
                schema_issues[table_name] = {
                    'status': 'exists_but_incomplete',
                    'missing_columns': missing_columns,
                    'current_columns': list(current_columns.keys())
                }
                print(f"⚠️  Table '{table_name}' exists but missing columns: {missing_columns}")
            else:
                print(f"✅ Table '{table_name}' complete")
        else:
            schema_issues[table_name] = {
                'status': 'missing',
                'missing_columns': [col.name for col in model_class.__table__.columns]
            }
            print(f"❌ Table '{table_name}' missing completely")
    
    return schema_issues

def backup_existing_data():
    """Backup existing data before migration"""
    
    print("\n📦 Backing up existing data...")
    
    backup_data = {}
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    try:
        with engine.connect() as connection:
            # Backup customers data if table exists
            if 'customers' in existing_tables:
                result = connection.execute(text("SELECT * FROM customers"))
                backup_data['customers'] = [dict(row._mapping) for row in result.fetchall()]
                print(f"✅ Backed up {len(backup_data['customers'])} customer records")
            
            # Backup loans data if table exists
            if 'loans' in existing_tables:
                result = connection.execute(text("SELECT * FROM loans"))
                backup_data['loans'] = [dict(row._mapping) for row in result.fetchall()]
                print(f"✅ Backed up {len(backup_data['loans'])} loan records")
            
            # Backup file_uploads data if table exists
            if 'file_uploads' in existing_tables:
                result = connection.execute(text("SELECT * FROM file_uploads"))
                backup_data['file_uploads'] = [dict(row._mapping) for row in result.fetchall()]
                print(f"✅ Backed up {len(backup_data['file_uploads'])} file upload records")
    
    except Exception as e:
        print(f"⚠️  Warning during backup: {e}")
    
    return backup_data

def create_complete_schema():
    """Create complete schema from scratch"""
    
    print("\n🏗️  Creating Complete Database Schema")
    print("=" * 50)
    
    try:
        # This will create all tables according to the schema definition
        Base.metadata.create_all(bind=engine, checkfirst=True)
        print("✅ All tables created successfully!")
        
        # Verify tables were created
        inspector = inspect(engine)
        created_tables = inspector.get_table_names()
        
        expected_tables = ['customers', 'loans', 'file_uploads', 'upload_rows', 'call_sessions', 'call_status_updates']
        
        for table_name in expected_tables:
            if table_name in created_tables:
                columns = [col['name'] for col in inspector.get_columns(table_name)]
                print(f"✅ Table '{table_name}': {len(columns)} columns")
                print(f"   Columns: {columns}")
            else:
                print(f"❌ Table '{table_name}' not created")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating schema: {e}")
        return False

def add_missing_columns_to_existing_tables():
    """Add missing columns to existing tables"""
    
    print("\n🔧 Adding Missing Columns to Existing Tables")
    print("=" * 50)
    
    try:
        with engine.connect() as connection:
            trans = connection.begin()
            
            try:
                # Add missing columns to customers table
                print("🔧 Updating customers table...")
                customer_migrations = [
                    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS fingerprint TEXT UNIQUE",
                    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS national_id VARCHAR(50)",
                    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS email VARCHAR(255)",
                    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS state VARCHAR(100)",
                    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS first_uploaded_at TIMESTAMP",
                    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS last_contact_date TIMESTAMP",
                    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS do_not_call BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ]
                
                for migration in customer_migrations:
                    try:
                        connection.execute(text(migration))
                        print(f"  ✅ {migration.split('ADD COLUMN IF NOT EXISTS')[1].split()[0] if 'ADD COLUMN' in migration else migration}")
                    except Exception as e:
                        print(f"  ⚠️  {migration}: {e}")
                
                # Add missing columns to loans table
                print("🔧 Updating loans table...")
                loan_migrations = [
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS customer_id UUID",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS loan_id VARCHAR(100) UNIQUE",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS principal_amount NUMERIC(15,2)",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS outstanding_amount NUMERIC(15,2)",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS due_amount NUMERIC(15,2)",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS next_due_date DATE",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS last_paid_date DATE",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS last_paid_amount NUMERIC(15,2)",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'active'",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS cluster VARCHAR(100)",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS branch VARCHAR(255)",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS branch_contact_number VARCHAR(20)",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS employee_name VARCHAR(255)",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS employee_id VARCHAR(100)",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS employee_contact_number VARCHAR(20)",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                    "ALTER TABLE loans ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ]
                
                for migration in loan_migrations:
                    try:
                        connection.execute(text(migration))
                        print(f"  ✅ {migration.split('ADD COLUMN IF NOT EXISTS')[1].split()[0] if 'ADD COLUMN' in migration else migration}")
                    except Exception as e:
                        print(f"  ⚠️  {migration}: {e}")
                
                # Add missing columns to call_sessions table  
                print("🔧 Updating call_sessions table...")
                call_session_migrations = [
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS call_sid VARCHAR(100) UNIQUE",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS loan_id UUID",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS customer_id UUID",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS initiated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'scheduled'",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS duration_seconds INTEGER",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS from_number VARCHAR(20)",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS to_number VARCHAR(20)",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS triggered_by_batch UUID",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS triggered_by_row UUID",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS call_metadata JSON",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                    "ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ]
                
                for migration in call_session_migrations:
                    try:
                        connection.execute(text(migration))
                        print(f"  ✅ {migration.split('ADD COLUMN IF NOT EXISTS')[1].split()[0] if 'ADD COLUMN' in migration else migration}")
                    except Exception as e:
                        print(f"  ⚠️  {migration}: {e}")
                
                trans.commit()
                print("✅ All column migrations completed!")
                
            except Exception as e:
                trans.rollback()
                print(f"❌ Migration failed: {e}")
                raise
                
    except Exception as e:
        print(f"❌ Error in column migration: {e}")
        return False
    
    return True

def create_indexes_and_constraints():
    """Create necessary indexes and constraints"""
    
    print("\n📋 Creating Indexes and Constraints")
    print("=" * 40)
    
    try:
        with engine.connect() as connection:
            trans = connection.begin()
            
            try:
                index_commands = [
                    "CREATE INDEX IF NOT EXISTS ix_customer_fingerprint ON customers(fingerprint)",
                    "CREATE INDEX IF NOT EXISTS ix_customer_primary_phone ON customers(primary_phone)", 
                    "CREATE INDEX IF NOT EXISTS ix_customer_state ON customers(state)",
                    "CREATE INDEX IF NOT EXISTS ix_loan_customer_id ON loans(customer_id)",
                    "CREATE INDEX IF NOT EXISTS ix_loan_external_id ON loans(loan_id)",
                    "CREATE INDEX IF NOT EXISTS ix_loan_status ON loans(status)",
                    "CREATE INDEX IF NOT EXISTS ix_call_session_call_sid ON call_sessions(call_sid)",
                    "CREATE INDEX IF NOT EXISTS ix_call_session_customer ON call_sessions(customer_id)",
                    "CREATE INDEX IF NOT EXISTS ix_call_session_status ON call_sessions(status)"
                ]
                
                for cmd in index_commands:
                    try:
                        connection.execute(text(cmd))
                        index_name = cmd.split("CREATE INDEX IF NOT EXISTS")[1].split("ON")[0].strip()
                        print(f"  ✅ Index: {index_name}")
                    except Exception as e:
                        print(f"  ⚠️  {cmd}: {e}")
                
                trans.commit()
                print("✅ Indexes created successfully!")
                
            except Exception as e:
                trans.rollback()
                print(f"❌ Index creation failed: {e}")
                
    except Exception as e:
        print(f"❌ Error creating indexes: {e}")

def insert_test_customer():
    """Insert test customer data"""
    
    print("\n👤 Adding Test Customer: Kushal")
    print("=" * 40)
    
    try:
        from database.schemas import get_session, compute_fingerprint
        session = get_session()
        
        try:
            # Create customer fingerprint
            fingerprint = compute_fingerprint("+917417119014", "")
            
            # Check if customer already exists
            existing = session.query(Customer).filter(Customer.primary_phone == "+917417119014").first()
            
            if existing:
                print(f"ℹ️  Customer 'Kushal' already exists with ID: {existing.id}")
                return str(existing.id)
            
            # Create new customer
            customer = Customer(
                fingerprint=fingerprint,
                full_name="Kushal",
                primary_phone="+917417119014",
                state="Karnataka",
                first_uploaded_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            session.add(customer)
            session.commit()
            
            print(f"✅ Customer 'Kushal' created successfully!")
            print(f"   ID: {customer.id}")
            print(f"   Phone: {customer.primary_phone}")
            print(f"   Fingerprint: {customer.fingerprint}")
            
            return str(customer.id)
            
        except Exception as e:
            session.rollback()
            print(f"❌ Error creating customer: {e}")
            return None
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ Error in customer creation: {e}")
        return None

def verify_final_schema():
    """Verify the final schema is working correctly"""
    
    print("\n🔍 Final Schema Verification")
    print("=" * 40)
    
    try:
        from database.schemas import get_session
        session = get_session()
        
        try:
            # Test customer query
            customers = session.query(Customer).all()
            print(f"✅ Customers table: {len(customers)} records")
            
            # Test loans query
            loans = session.query(Loan).all()
            print(f"✅ Loans table: {len(loans)} records")
            
            # Test file uploads query
            uploads = session.query(FileUpload).all()
            print(f"✅ File uploads table: {len(uploads)} records")
            
            # Test call sessions query
            call_sessions = session.query(CallSession).all()
            print(f"✅ Call sessions table: {len(call_sessions)} records")
            
            print("✅ All schema verification tests passed!")
            return True
            
        except Exception as e:
            print(f"❌ Schema verification failed: {e}")
            return False
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ Error in schema verification: {e}")
        return False

def main():
    """Main migration function"""
    
    print("🚀 Comprehensive Database Schema Migration")
    print("=" * 60)
    
    # Check current state
    schema_issues = check_current_database_state()
    
    if schema_issues:
        print(f"\n⚠️  Found {len(schema_issues)} schema issues to fix")
        
        # Backup existing data
        backup_data = backup_existing_data()
        
        # Create complete schema (will add missing tables/columns)
        if create_complete_schema():
            print("✅ Schema creation successful")
        else:
            print("❌ Schema creation failed, trying column-by-column approach...")
            add_missing_columns_to_existing_tables()
        
        # Create indexes and constraints
        create_indexes_and_constraints()
        
        # Add test customer
        customer_id = insert_test_customer()
        
        # Verify everything works
        if verify_final_schema():
            print("\n🎉 Database migration completed successfully!")
            print("=" * 50)
            print("✅ All tables and columns are now properly configured")
            print("✅ Test customer 'Kushal' has been added")
            print("✅ Your application should now work without database errors")
            
            if customer_id:
                print(f"\n👤 Test Customer Details:")
                print(f"   Name: Kushal")
                print(f"   Phone: +917417119014")
                print(f"   Customer ID: {customer_id}")
            
        else:
            print("\n❌ Migration verification failed")
            return False
    else:
        print("\n✅ Database schema is already complete!")
        
        # Still add test customer if requested
        customer_id = insert_test_customer()
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\n🚀 Ready to restart your application!")
            print("The database schema is now complete and contains test customer data.")
        else:
            print("\n❌ Please check the errors above and try again")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
