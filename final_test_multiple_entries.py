#!/usr/bin/env python3
"""
Final Test: Multiple Customer Entries
Test that the complete fix works for creating multiple customer entries
"""
import sys
from datetime import datetime

# Add project root to path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

from database.schemas import get_session, create_customer, Customer

def test_multiple_customer_entries():
    """Test creating multiple entries for the same customer"""
    
    print("🧪 FINAL TEST: MULTIPLE CUSTOMER ENTRIES")
    print("=" * 50)
    
    test_phone = "+919988776655"
    
    try:
        session = get_session()
        
        # Clean up any existing test data
        existing_count = session.query(Customer).filter(Customer.primary_phone == test_phone).count()
        if existing_count > 0:
            session.query(Customer).filter(Customer.primary_phone == test_phone).delete()
            session.commit()
            print(f"🧹 Cleaned up {existing_count} existing test entries")
        
        print(f"\n📝 Creating multiple entries for {test_phone}...")
        
        # Entry 1 - Day 1 upload
        customer_data_1 = {
            'full_name': 'John Doe Day 1',
            'primary_phone': test_phone,
            'state': 'Maharashtra',
            'loan_id': 'LOAN001',
            'amount': '50000',
            'due_date': '2025-12-31'
        }
        
        customer1 = create_customer(session, customer_data_1)
        if customer1:
            print(f"   ✅ Day 1 Entry: {customer1.full_name} (ID: {customer1.id})")
        else:
            print("   ❌ Failed to create Day 1 entry")
            return False
        
        # Entry 2 - Day 2 upload (same phone, different data)
        customer_data_2 = {
            'full_name': 'John Doe Day 2',
            'primary_phone': test_phone,
            'state': 'Karnataka',
            'loan_id': 'LOAN002', 
            'amount': '75000',
            'due_date': '2025-11-30'
        }
        
        customer2 = create_customer(session, customer_data_2)
        if customer2:
            print(f"   ✅ Day 2 Entry: {customer2.full_name} (ID: {customer2.id})")
        else:
            print("   ❌ Failed to create Day 2 entry")
            return False
        
        # Entry 3 - Day 3 upload (same phone again)
        customer_data_3 = {
            'full_name': 'John Doe Day 3',
            'primary_phone': test_phone,
            'state': 'Tamil Nadu',
            'loan_id': 'LOAN003',
            'amount': '100000',
            'due_date': '2025-10-31'
        }
        
        customer3 = create_customer(session, customer_data_3)
        if customer3:
            print(f"   ✅ Day 3 Entry: {customer3.full_name} (ID: {customer3.id})")
        else:
            print("   ❌ Failed to create Day 3 entry")
            return False
        
        # Verify all entries exist
        final_count = session.query(Customer).filter(Customer.primary_phone == test_phone).count()
        customers = session.query(Customer).filter(Customer.primary_phone == test_phone).all()
        
        print(f"\n📊 RESULTS:")
        print(f"   • Phone Number: {test_phone}")
        print(f"   • Total Entries Created: {final_count}")
        print(f"   • Expected: 3")
        
        if final_count >= 3:
            print(f"\n🎉 SUCCESS! Created {final_count} separate entries for same customer!")
            print("\n📝 Customer Entry Details:")
            for i, customer in enumerate(customers, 1):
                print(f"   • Entry {i}: {customer.full_name}")
                print(f"     - ID: {customer.id}")
                print(f"     - State: {customer.state}")
                print(f"     - Loan: {customer.loan_id}")
                print(f"     - Created: {customer.created_at}")
            return True
        else:
            print(f"\n❌ FAILED! Only created {final_count} entries (expected 3)")
            return False
        
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        try:
            session.close()
        except:
            pass

def cleanup_test_data():
    """Clean up test data"""
    test_phone = "+919988776655"
    
    try:
        session = get_session()
        deleted = session.query(Customer).filter(Customer.primary_phone == test_phone).delete()
        session.commit()
        session.close()
        
        if deleted > 0:
            print(f"\n🧹 Cleaned up {deleted} test entries")
            
    except Exception as e:
        print(f"\n⚠️  Cleanup warning: {e}")

def main():
    success = test_multiple_customer_entries()
    
    if success:
        print("\n" + "=" * 50)
        print("🎉 MULTIPLE CUSTOMER ENTRIES - WORKING!")
        print()
        print("✅ Your system now behaves exactly as requested:")
        print("   • First Upload (Day 1):  Creates customer entry #1 ✅")
        print("   • Second Upload (Day 2): Creates customer entry #2 ✅") 
        print("   • Third Upload (Day 3):  Creates customer entry #3 ✅")
        print()
        print("🎯 Same customer + different upload dates = multiple database records")
        
        cleanup_choice = input("\nClean up test data? (y/n): ").lower().strip()
        if cleanup_choice == 'y':
            cleanup_test_data()
    else:
        print("\n❌ Test failed. The multiple entries feature is not working.")

if __name__ == "__main__":
    main()
