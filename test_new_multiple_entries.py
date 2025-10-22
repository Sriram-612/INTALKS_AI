#!/usr/bin/env python3
"""
Test New Multiple Customer Entry Behavior
Tests that the same customer can now be uploaded multiple times 
and creates separate database entries for each upload.
"""
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

from services.call_management import CallManagementService
from database.schemas import get_session, Customer

def test_multiple_customer_entries():
    """Test that same customer creates multiple entries on different uploads"""
    
    print("🧪 TESTING MULTIPLE CUSTOMER ENTRIES")
    print("=" * 50)
    print("Testing that the same customer creates separate entries for each upload")
    print()
    
    # Test phone number
    test_phone = "+919999888777"
    
    # Get initial count
    session = get_session()
    initial_count = session.query(Customer).filter(Customer.primary_phone == test_phone).count()
    print(f"📊 Initial customer entries for {test_phone}: {initial_count}")
    session.close()
    
    # Test CSV content - same customer data
    test_csv = f'''Name,Phone,Loan ID,Amount,Due Date,State,Branch,Employee
Test Customer,{test_phone},LOAN001,50000,2025-12-31,Maharashtra,Test Branch,Test Employee'''
    
    try:
        call_service = CallManagementService()
        
        # Upload 1 - Day 1
        print(f"\n📤 Upload 1 (Day 1): Processing customer {test_phone}...")
        result1 = call_service.process_csv_data(test_csv, "day1_upload.csv")
        
        # Check count after first upload
        session = get_session()
        count_after_1 = session.query(Customer).filter(Customer.primary_phone == test_phone).count()
        session.close()
        print(f"   📊 Entries after upload 1: {count_after_1}")
        
        # Upload 2 - Day 2 (same customer data)
        print(f"\n📤 Upload 2 (Day 2): Processing SAME customer {test_phone}...")
        result2 = call_service.process_csv_data(test_csv, "day2_upload.csv")
        
        # Check count after second upload  
        session = get_session()
        count_after_2 = session.query(Customer).filter(Customer.primary_phone == test_phone).count()
        session.close()
        print(f"   📊 Entries after upload 2: {count_after_2}")
        
        # Upload 3 - Day 3 (same customer data again)
        print(f"\n📤 Upload 3 (Day 3): Processing SAME customer {test_phone} again...")
        result3 = call_service.process_csv_data(test_csv, "day3_upload.csv")
        
        # Final count
        session = get_session()
        final_count = session.query(Customer).filter(Customer.primary_phone == test_phone).count()
        customers = session.query(Customer).filter(Customer.primary_phone == test_phone).all()
        session.close()
        
        print(f"   📊 Final entries: {final_count}")
        
        # Calculate new entries created
        new_entries = final_count - initial_count
        
        print(f"\n📊 RESULTS:")
        print(f"   • Initial entries: {initial_count}")
        print(f"   • New entries created: {new_entries}")
        print(f"   • Final total entries: {final_count}")
        print()
        
        # Show details of each entry
        if customers:
            print("📝 Customer Entry Details:")
            for i, customer in enumerate(customers[-new_entries:], 1):  # Show only new entries
                print(f"   • Entry {i}: {customer.full_name} (Created: {customer.created_at})")
        
        # Verify the behavior
        if new_entries >= 3:
            print("\n✅ SUCCESS! Multiple entries created for same customer!")
            print("✅ The system now creates NEW customer entries for each upload")
            print("✅ Same customer on different dates = separate database records")
            return True
        elif new_entries >= 1:
            print("\n⚠️  PARTIAL SUCCESS: Some new entries created")
            print(f"   Expected 3 new entries, got {new_entries}")
            return False
        else:
            print("\n❌ FAILED: No new entries created")
            print("❌ The system is still updating existing records")
            return False
            
    except Exception as e:
        print(f"\n❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

def cleanup_test_data():
    """Clean up test data"""
    test_phone = "+919999888777"
    
    try:
        session = get_session()
        # Delete test entries
        deleted = session.query(Customer).filter(Customer.primary_phone == test_phone).delete()
        session.commit()
        session.close()
        
        if deleted > 0:
            print(f"\n🧹 Cleaned up {deleted} test entries")
        
    except Exception as e:
        print(f"\n⚠️  Cleanup warning: {e}")

if __name__ == "__main__":
    # Run the test
    success = test_multiple_customer_entries()
    
    # Ask if user wants to clean up test data
    if success:
        print("\n" + "=" * 50)
        print("🎉 TEST COMPLETED SUCCESSFULLY!")
        print()
        print("📊 NEW BEHAVIOR CONFIRMED:")
        print("   • Day 1 Upload: Creates customer entry #1 ✅")
        print("   • Day 2 Upload: Creates customer entry #2 ✅") 
        print("   • Day 3 Upload: Creates customer entry #3 ✅")
        print()
        print("🎯 Your system now works exactly as requested!")
        
        cleanup_choice = input("Clean up test data? (y/n): ").lower().strip()
        if cleanup_choice == 'y':
            cleanup_test_data()
    else:
        print("\n❌ Test failed. Please check the implementation.")
