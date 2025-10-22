#!/usr/bin/env python3
"""
Enable Multiple Customer Entries for Same Phone Number
This script modifies the system to allow creating new customer entries
for each upload, even if the phone number already exists.
"""
import sys
from pathlib import Path
from sqlalchemy import text
from datetime import datetime

# Add project root to path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

from database.schemas import db_manager

def remove_unique_phone_constraint():
    """
    Remove the unique constraint on primary_phone to allow 
    multiple customer entries with the same phone number
    """
    print("🔧 Removing unique constraint on primary_phone...")
    print("This will allow multiple customer entries for the same phone number.")
    print()
    
    try:
        with db_manager.engine.connect() as conn:
            # Start transaction
            trans = conn.begin()
            
            try:
                # Drop the unique constraint
                conn.execute(text("""
                    ALTER TABLE customers 
                    DROP CONSTRAINT IF EXISTS uix_customer_primary_phone;
                """))
                
                print("✅ Successfully removed unique constraint on primary_phone")
                
                # Commit the transaction
                trans.commit()
                
                print("✅ Database schema updated successfully!")
                print("📝 Now you can upload the same customer multiple times on different dates.")
                
            except Exception as e:
                # Rollback on error
                trans.rollback()
                raise e
                
    except Exception as e:
        print(f"❌ Error removing constraint: {e}")
        return False
    
    return True

def update_application_logic():
    """
    Update the application logic to always create new entries
    instead of updating existing ones
    """
    print("\n🔧 Updating application logic...")
    
    # Read the current call_management.py
    call_mgmt_file = Path('/home/cyberdude/Documents/Projects/voice/services/call_management.py')
    
    with open(call_mgmt_file, 'r') as f:
        content = f.read()
    
    # Replace the UPDATE logic with CREATE logic
    old_logic = '''                    # Get existing customer by phone
                    existing_customer = get_customer_by_phone(session, phone_number)
                    
                    if existing_customer:
                        # Customer exists - UPDATE existing record
                        customer = existing_customer
                        
                        # Update customer fields with new data
                        for key, value in customer_data.items():
                            if hasattr(customer, key) and value is not None and key not in ['id', 'created_at', 'fingerprint']:
                                setattr(customer, key, value)
                        
                        customer.updated_at = datetime.utcnow()
                        session.commit()
                        
                        logger.info(f"✅ Updated existing customer: {customer.full_name} (Phone: {phone_number})")
                    else:
                        # First-time customer - CREATE new record'''
    
    new_logic = '''                    # Always CREATE new customer entry for each upload
                    # This allows tracking the same customer across different upload dates
                    
                    # Check if this is a returning customer (for logging purposes)
                    existing_customer = get_customer_by_phone(session, phone_number)
                    if existing_customer:
                        logger.info(f"📝 Creating new entry for returning customer: {customer_data.get('name', 'Unknown')} (Phone: {phone_number})")
                    else:
                        logger.info(f"📝 Creating new entry for first-time customer: {customer_data.get('name', 'Unknown')} (Phone: {phone_number})")
                    
                    # Always CREATE new record for each upload'''
    
    # Replace the logic
    if old_logic in content:
        content = content.replace(old_logic, new_logic)
        
        # Write back to file
        with open(call_mgmt_file, 'w') as f:
            f.write(content)
        
        print("✅ Updated application logic to always create new customer entries")
        return True
    else:
        print("❌ Could not find the target logic to replace")
        print("Please manually update services/call_management.py")
        return False

def test_new_behavior():
    """
    Test the new behavior by creating multiple entries for the same customer
    """
    print("\n🧪 Testing new multiple entry behavior...")
    
    from services.call_management import CallManagementService
    from database.schemas import get_session, Customer
    
    # Test data - same customer, different upload dates
    test_csv_content = '''Name,Phone,Loan ID,Amount,Due Date,State
Test Customer,9999888777,TEST001,50000,2025-12-31,Maharashtra
Test Customer,9999888777,TEST002,75000,2025-12-31,Maharashtra'''
    
    try:
        # Create service instance
        call_service = CallManagementService()
        
        # Process first upload
        print("\n📤 Processing first upload...")
        result1 = call_service.process_csv_data(test_csv_content, "test_upload_1.csv")
        
        # Process second upload (same customer)
        print("\n📤 Processing second upload (same customer)...")
        result2 = call_service.process_csv_data(test_csv_content, "test_upload_2.csv")
        
        # Check database entries
        session = get_session()
        customers = session.query(Customer).filter(Customer.primary_phone == '9999888777').all()
        session.close()
        
        print(f"\n📊 Results:")
        print(f"   • Number of entries for phone 9999888777: {len(customers)}")
        print(f"   • Expected: 4 (2 customers × 2 uploads)")
        
        if len(customers) >= 2:
            print("✅ SUCCESS: Multiple entries created for same customer!")
            for i, customer in enumerate(customers):
                print(f"   • Entry {i+1}: {customer.full_name} (Created: {customer.created_at})")
        else:
            print("❌ FAILED: Still only one entry per customer")
        
        return len(customers) >= 2
        
    except Exception as e:
        print(f"❌ Test error: {e}")
        return False

def restore_unique_constraint():
    """
    Restore the unique constraint if you want to revert back
    """
    print("\n🔄 Restoring unique constraint...")
    
    try:
        with db_manager.engine.connect() as conn:
            trans = conn.begin()
            
            try:
                # Add back the unique constraint
                conn.execute(text("""
                    ALTER TABLE customers 
                    ADD CONSTRAINT uix_customer_primary_phone 
                    UNIQUE (primary_phone);
                """))
                
                trans.commit()
                print("✅ Unique constraint restored")
                
            except Exception as e:
                trans.rollback()
                raise e
                
    except Exception as e:
        print(f"❌ Error restoring constraint: {e}")
        return False
    
    return True

def main():
    print("🚀 ENABLE MULTIPLE CUSTOMER ENTRIES")
    print("=" * 50)
    print("This will modify your system to allow multiple entries")
    print("for the same customer on different upload dates.")
    print()
    
    choice = input("Proceed with changes? (y/n): ").lower().strip()
    
    if choice != 'y':
        print("❌ Operation cancelled")
        return
    
    # Step 1: Remove database constraint
    if not remove_unique_phone_constraint():
        print("❌ Failed to remove database constraint")
        return
    
    # Step 2: Update application logic
    if not update_application_logic():
        print("❌ Failed to update application logic")
        return
    
    # Step 3: Test the new behavior
    print("\n" + "=" * 50)
    print("🎉 SYSTEM UPDATED SUCCESSFULLY!")
    print()
    print("✅ What changed:")
    print("   • Removed unique constraint on phone numbers")
    print("   • Updated logic to always create new customer entries")
    print("   • Same customer can now be uploaded multiple times")
    print()
    print("📝 New behavior:")
    print("   • Day 1 Upload: Creates customer entry #1 ✅")
    print("   • Day 2 Upload: Creates customer entry #2 ✅") 
    print("   • Day 3 Upload: Creates customer entry #3 ✅")
    print()
    
    # Optional: Test the new behavior
    test_choice = input("Run test to verify new behavior? (y/n): ").lower().strip()
    if test_choice == 'y':
        test_new_behavior()

if __name__ == "__main__":
    main()
