#!/usr/bin/env python3
"""
Quick Fix: Enable Multiple Customer Entries Per Upload Date
This script makes the minimal changes needed to allow the same customer
to be uploaded multiple times and create separate database entries.
"""
import sys
from pathlib import Path
from sqlalchemy import text

# Add project root to path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

from database.schemas import db_manager

def apply_quick_fix():
    """Apply the quick fix to enable multiple customer entries"""
    
    print("🚀 APPLYING QUICK FIX FOR MULTIPLE CUSTOMER ENTRIES")
    print("=" * 60)
    
    # Step 1: Remove unique constraint from database
    print("🔧 Step 1: Removing unique phone constraint from database...")
    
    try:
        with db_manager.engine.connect() as conn:
            trans = conn.begin()
            
            try:
                # Drop the unique constraint
                conn.execute(text("""
                    ALTER TABLE customers 
                    DROP CONSTRAINT IF EXISTS uix_customer_primary_phone;
                """))
                
                trans.commit()
                print("   ✅ Successfully removed unique phone constraint")
                
            except Exception as e:
                trans.rollback()
                print(f"   ❌ Database error: {e}")
                return False
                
    except Exception as e:
        print(f"   ❌ Connection error: {e}")
        return False
    
    # Step 2: Update application logic
    print("\n🔧 Step 2: Updating application logic...")
    
    call_mgmt_file = Path('/home/cyberdude/Documents/Projects/voice/services/call_management.py')
    
    try:
        # Read current file
        with open(call_mgmt_file, 'r') as f:
            content = f.read()
        
        # Find and replace the customer checking logic
        old_check = '''                    # Get existing customer by phone
                    existing_customer = get_customer_by_phone(session, phone_number)
                    
                    if existing_customer:'''
        
        new_check = '''                    # Always create new entry for each upload (allows multiple entries per customer)
                    existing_customer = None  # Skip existing customer check to always create new entries
                    
                    if False:  # Disabled: existing_customer:'''
        
        if old_check in content:
            content = content.replace(old_check, new_check)
            
            # Write back to file
            with open(call_mgmt_file, 'w') as f:
                f.write(content)
            
            print("   ✅ Successfully updated application logic")
        else:
            print("   ⚠️  Could not find exact target code - manual update needed")
            return False
            
    except Exception as e:
        print(f"   ❌ File error: {e}")
        return False
    
    print("\n🎉 QUICK FIX APPLIED SUCCESSFULLY!")
    print()
    print("📊 NEW BEHAVIOR:")
    print("   • First Upload (Day 1):  Creates customer entry #1 ✅")
    print("   • Second Upload (Day 2): Creates customer entry #2 ✅") 
    print("   • Third Upload (Day 3):  Creates customer entry #3 ✅")
    print()
    print("🔄 Each upload will now create a separate customer entry,")
    print("   even for the same phone number on different dates.")
    
    return True

def test_the_fix():
    """Test that the fix works"""
    print("\n🧪 TESTING THE FIX")
    print("=" * 30)
    
    from services.call_management import CallManagementService
    from database.schemas import get_session, Customer
    
    # Test CSV content with same customer
    test_csv = '''Name,Phone,Loan ID,Amount,Due Date,State
John Doe,+919876543210,LOAN001,50000,2025-12-31,Maharashtra'''
    
    try:
        call_service = CallManagementService()
        
        # Get initial count
        session = get_session()
        initial_count = session.query(Customer).filter(Customer.primary_phone == '+919876543210').count()
        session.close()
        
        print(f"📊 Initial entries for +919876543210: {initial_count}")
        
        # Process upload 1
        print("\n📤 Upload 1: Processing...")
        result1 = call_service.process_csv_data(test_csv, "upload_1.csv")
        
        # Process upload 2 (same data)
        print("📤 Upload 2: Processing same customer...")
        result2 = call_service.process_csv_data(test_csv, "upload_2.csv")
        
        # Check final count
        session = get_session()
        final_count = session.query(Customer).filter(Customer.primary_phone == '+919876543210').count()
        session.close()
        
        print(f"📊 Final entries for +919876543210: {final_count}")
        print(f"📊 New entries created: {final_count - initial_count}")
        
        if (final_count - initial_count) >= 2:
            print("\n✅ SUCCESS! Multiple entries created for same customer")
            return True
        else:
            print("\n❌ FAILED! Still creating only one entry per customer")
            return False
            
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        return False

if __name__ == "__main__":
    # Apply the fix
    success = apply_quick_fix()
    
    if success:
        # Ask if user wants to test
        test_choice = input("\nWould you like to test the fix now? (y/n): ").lower().strip()
        if test_choice == 'y':
            test_the_fix()
    else:
        print("\n❌ Fix failed to apply. Please check the errors above.")
