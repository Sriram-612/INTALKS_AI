#!/usr/bin/env python3
"""
Simple Test: Same Customer Multiple Uploads  
Shows database behavior when uploading the same customer multiple times
"""

import sys
import os
from datetime import datetime, timedelta

# Add project root to path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

from database.schemas import get_session, Customer, create_customer

def test_same_customer_multiple_times():
    """Test what happens when we try to create the same customer multiple times"""
    
    print("🧪 Testing Same Customer Multiple Upload Attempts")
    print("=" * 55)
    
    session = get_session()
    
    try:
        # Test customer data
        phone_number = "+919999888777"
        
        # Check if customer already exists
        existing = session.query(Customer).filter(Customer.primary_phone == phone_number).first()
        if existing:
            print(f"🧹 Cleaning up existing test customer: {existing.full_name}")
            session.delete(existing)
            session.commit()
        
        # Upload 1: Create customer for the first time
        print("\n📅 ATTEMPT 1: Creating customer for first time")
        print("-" * 45)
        
        customer_data_1 = {
            'full_name': 'Test Kumar',
            'primary_phone': phone_number,
            'state': 'Karnataka',
            'loan_id': 'TEST001',
            'amount': '25000',
            'due_date': '2025-11-15'
        }
        
        try:
            customer1 = create_customer(session, customer_data_1)
            session.commit()
            print(f"✅ SUCCESS: Customer created")
            print(f"   ID: {customer1.id}")
            print(f"   Name: {customer1.full_name}")
            print(f"   Amount: {customer1.amount}")
            print(f"   Created: {customer1.created_at}")
        except Exception as e:
            session.rollback()
            print(f"❌ FAILED: {e}")
            return
        
        # Upload 2: Try to create the same customer again (same phone)
        print("\n📅 ATTEMPT 2: Trying to create same customer again")
        print("-" * 50)
        
        customer_data_2 = {
            'full_name': 'Test Kumar Updated',  # Different name
            'primary_phone': phone_number,      # Same phone - should trigger constraint
            'state': 'Tamil Nadu',              # Different state
            'loan_id': 'TEST002',              # Different loan
            'amount': '35000',                 # Different amount
            'due_date': '2025-12-15'           # Different due date
        }
        
        try:
            customer2 = create_customer(session, customer_data_2)
            session.commit()
            print(f"✅ SUCCESS: Second customer created")
            print(f"   ID: {customer2.id}")
            print(f"   Name: {customer2.full_name}")
            print(f"   Amount: {customer2.amount}")
            print(f"   Created: {customer2.created_at}")
        except Exception as e:
            session.rollback()
            print(f"❌ FAILED: {e}")
            print("   This is expected due to unique constraint on phone number")
        
        # Check how many customers exist with this phone
        print(f"\n📊 DATABASE STATE CHECK:")
        print("-" * 25)
        
        all_customers = session.query(Customer).filter(Customer.primary_phone == phone_number).all()
        print(f"   Total customers with phone {phone_number}: {len(all_customers)}")
        
        for i, customer in enumerate(all_customers, 1):
            print(f"   {i}. ID: {customer.id}, Name: {customer.full_name}, Amount: {customer.amount}")
        
        # Upload 3: Manual update approach (what the system actually does)
        print(f"\n📅 ATTEMPT 3: Updating existing customer (system approach)")
        print("-" * 55)
        
        existing_customer = session.query(Customer).filter(Customer.primary_phone == phone_number).first()
        if existing_customer:
            # Update the existing customer with new data
            existing_customer.full_name = 'Test Kumar Final Update'
            existing_customer.state = 'Kerala'
            existing_customer.loan_id = 'TEST003'
            existing_customer.amount = '45000'
            existing_customer.due_date = '2026-01-15'
            existing_customer.updated_at = datetime.utcnow()
            
            session.commit()
            
            print(f"✅ SUCCESS: Customer updated")
            print(f"   ID: {existing_customer.id} (same as before)")
            print(f"   Name: {existing_customer.full_name} (updated)")
            print(f"   Amount: {existing_customer.amount} (updated)")
            print(f"   Updated: {existing_customer.updated_at}")
        
        # Final state
        print(f"\n🎯 FINAL RESULT:")
        print("-" * 15)
        final_customers = session.query(Customer).filter(Customer.primary_phone == phone_number).all()
        print(f"   Customers in database: {len(final_customers)}")
        print(f"   Behavior: {'UPDATE existing record' if len(final_customers) == 1 else 'CREATE new records'}")
        
        if final_customers:
            customer = final_customers[0]
            print(f"   Final data: {customer.full_name}, Amount: {customer.amount}")
        
    except Exception as e:
        print(f"❌ Test error: {e}")
        session.rollback()
        
    finally:
        # Cleanup
        try:
            test_customer = session.query(Customer).filter(Customer.primary_phone == phone_number).first()
            if test_customer:
                session.delete(test_customer)
                session.commit()
                print(f"\n🧹 Cleanup: Removed test customer")
        except:
            pass
        
        session.close()

if __name__ == "__main__":
    test_same_customer_multiple_times()
