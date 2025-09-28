#!/usr/bin/env python3
"""
Simple Test: Create Multiple Customer Entries
Directly tests the database behavior with the new logic
"""
import sys
from datetime import datetime, timedelta
import io

# Add project root to path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

from services.call_management import CallManagementService
from database.schemas import get_session, Customer

async def test_multiple_customer_creation():
    """Test creating multiple customer entries directly"""
    
    print("🧪 TESTING MULTIPLE CUSTOMER CREATION")
    print("=" * 50)
    
    test_phone = "+919999888777"
    
    # Check initial count
    session = get_session()
    initial_count = session.query(Customer).filter(Customer.primary_phone == test_phone).count()
    print(f"📊 Initial entries for {test_phone}: {initial_count}")
    session.close()
    
    # Create CSV content
    csv_content = f'''Name,Phone,Loan ID,Amount,Due Date,State
Test Customer,{test_phone},LOAN001,50000,2025-12-31,Maharashtra'''
    
    try:
        # Convert CSV content to bytes
        csv_bytes = csv_content.encode('utf-8')
        
        # Create service instance
        call_service = CallManagementService()
        
        # Test Upload 1
        print(f"\n📤 Upload 1: Creating entry for {test_phone}...")
        result1 = await call_service.upload_and_process_customers(csv_bytes, "test_upload_1.csv")
        print(f"   Result: {result1.get('status', 'unknown')}")
        
        # Check count after upload 1
        session = get_session()
        count_after_1 = session.query(Customer).filter(Customer.primary_phone == test_phone).count()
        session.close()
        print(f"   📊 Entries after upload 1: {count_after_1}")
        
        # Test Upload 2 (same customer)
        print(f"\n📤 Upload 2: Creating another entry for SAME customer {test_phone}...")
        result2 = await call_service.upload_and_process_customers(csv_bytes, "test_upload_2.csv")
        print(f"   Result: {result2.get('status', 'unknown')}")
        
        # Check final count
        session = get_session()
        final_count = session.query(Customer).filter(Customer.primary_phone == test_phone).count()
        customers = session.query(Customer).filter(Customer.primary_phone == test_phone).all()
        session.close()
        
        print(f"   📊 Final entries: {final_count}")
        
        # Calculate new entries
        new_entries = final_count - initial_count
        
        print(f"\n📊 RESULTS:")
        print(f"   • Initial entries: {initial_count}")
        print(f"   • New entries created: {new_entries}")
        print(f"   • Final total: {final_count}")
        
        # Show customer details
        if customers:
            print(f"\n📝 Customer Entries for {test_phone}:")
            for i, customer in enumerate(customers[-new_entries:], 1):
                print(f"   • Entry {i}: {customer.full_name} (Created: {customer.created_at})")
        
        # Verify behavior
        if new_entries >= 2:
            print(f"\n✅ SUCCESS! Created {new_entries} separate entries for same customer")
            print("✅ Multiple customer entries behavior is working!")
            return True
        else:
            print(f"\n❌ FAILED: Only created {new_entries} entries (expected 2+)")
            return False
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Main async function"""
    success = await test_multiple_customer_creation()
    
    if success:
        print("\n🎉 NEW BEHAVIOR CONFIRMED!")
        print("   • Same customer + different upload dates = multiple entries ✅")
    else:
        print("\n❌ Test failed - behavior not working as expected")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
