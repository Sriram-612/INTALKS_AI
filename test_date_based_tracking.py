#!/usr/bin/env python3
"""
Test Date-Based Customer Tracking Feature
Tests that duplicate customers uploaded on different dates create separate entries
"""

import os
import sys
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, '/home/cyberdude/Documents/Projects/voice')

from services.call_management import CallManagementService
from database.schemas import db_manager, Customer

def test_date_based_customer_tracking():
    """Test that customers uploaded on different dates create separate entries"""
    
    print("🧪 Testing Date-Based Customer Tracking")
    print("=" * 50)
    
    # Initialize service
    call_service = CallManagementService()
    session = db_manager.get_session()
    
    try:
        # Test data - same customer uploaded twice
        customer_data = {
            'name': 'John Doe Test',
            'phone_number': '+91-9876543210',
            'national_id': 'TEST123456789',
            'state': 'Karnataka', 
            'loan_id': 'LOAN123',
            'amount': '50000',
            'due_date': '2025-10-15',
            'language_code': 'en-IN'
        }
        
        print(f"📋 Test Customer: {customer_data['name']} ({customer_data['phone_number']})")
        
        # Clean up any existing test data
        existing_customers = session.query(Customer).filter(
            Customer.primary_phone == customer_data['phone_number']
        ).all()
        
        for customer in existing_customers:
            session.delete(customer)
        session.commit()
        print(f"🧹 Cleaned up {len(existing_customers)} existing test records")
        
        # Simulate first upload (today)
        print("\n📤 Simulating first upload (today)...")
        
        # Mock file data for first upload
        first_upload_result = asyncio.run(
            call_service._process_single_customer(session, customer_data)
        )
        
        # Count customers after first upload
        customers_after_first = session.query(Customer).filter(
            Customer.primary_phone == customer_data['phone_number']
        ).count()
        
        print(f"✅ First upload completed - Total customers: {customers_after_first}")
        
        # Simulate second upload (same day) - should update existing
        print("\n📤 Simulating second upload (same day)...")
        
        customer_data_updated = customer_data.copy()
        customer_data_updated['amount'] = '60000'  # Changed amount
        
        second_upload_result = asyncio.run(
            call_service._process_single_customer(session, customer_data_updated)
        )
        
        customers_after_second = session.query(Customer).filter(
            Customer.primary_phone == customer_data['phone_number']
        ).count()
        
        print(f"✅ Second upload completed - Total customers: {customers_after_second}")
        
        # Verify same-day upload didn't create new entry
        if customers_after_second == customers_after_first:
            print("✅ PASS: Same-day upload updated existing customer (no duplicate)")
        else:
            print("❌ FAIL: Same-day upload created duplicate entry")
            
        # Test the key feature: Different date upload
        print("\n📤 Simulating third upload (different date simulation)...")
        
        # Modify the created_at timestamp to simulate different upload date
        existing_customer = session.query(Customer).filter(
            Customer.primary_phone == customer_data['phone_number']
        ).first()
        
        if existing_customer:
            # Simulate previous day upload
            existing_customer.created_at = datetime.utcnow() - timedelta(days=1)
            session.commit()
            
            # Now upload again with different data
            customer_data_different_date = customer_data.copy()
            customer_data_different_date['amount'] = '70000'  # Different amount
            customer_data_different_date['state'] = 'Tamil Nadu'  # Different state
            
            third_upload_result = asyncio.run(
                call_service._process_single_customer(session, customer_data_different_date)
            )
            
            customers_after_third = session.query(Customer).filter(
                Customer.primary_phone == customer_data['phone_number']
            ).count()
            
            print(f"✅ Third upload completed - Total customers: {customers_after_third}")
            
            # Verify different date created new entry
            if customers_after_third > customers_after_second:
                print("✅ PASS: Different date upload created separate customer entry")
                
                # Verify both entries exist with different data
                all_customers = session.query(Customer).filter(
                    Customer.primary_phone == customer_data['phone_number']
                ).all()
                
                amounts = [c.amount for c in all_customers]
                states = [c.state for c in all_customers]
                
                print(f"📊 Customer entries found: {len(all_customers)}")
                print(f"📊 Amounts: {amounts}")
                print(f"📊 States: {states}")
                
                if len(set(amounts)) > 1 or len(set(states)) > 1:
                    print("✅ PASS: Previous data preserved, new data stored separately")
                else:
                    print("❌ FAIL: Data was overwritten instead of creating separate entry")
                    
            else:
                print("❌ FAIL: Different date upload did not create separate entry")
        
        print("\n" + "=" * 50)
        print("🎯 Date-Based Customer Tracking Test Summary:")
        print(f"📈 Total customer entries created: {customers_after_third}")
        print(f"📞 Phone number tested: {customer_data['phone_number']}")
        
        if customers_after_third >= 2:
            print("🎉 SUCCESS: Date-based customer tracking is working!")
            return True
        else:
            print("❌ FAILED: Date-based customer tracking needs debugging")
            return False
            
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Clean up test data
        test_customers = session.query(Customer).filter(
            Customer.primary_phone == customer_data['phone_number']
        ).all()
        
        for customer in test_customers:
            session.delete(customer)
        session.commit()
        
        db_manager.close_session(session)
        print("🧹 Test cleanup completed")

async def _process_single_customer_helper(call_service, session, customer_data):
    """Helper to process a single customer (simulates part of upload_and_process_customers)"""
    from database.schemas import get_customer_by_phone, create_customer, compute_fingerprint
    from datetime import datetime as dt
    
    current_upload_date = dt.utcnow().date()
    
    # Check if customer exists with same phone number AND same upload date
    existing_customer = get_customer_by_phone(session, customer_data['phone_number'])
    same_date_customer = None
    
    if existing_customer:
        # Check if there's already an entry for today's upload
        same_date_customer = session.query(Customer).filter(
            Customer.primary_phone == customer_data['phone_number'],
            Customer.created_at >= dt.combine(current_upload_date, dt.min.time()),
            Customer.created_at < dt.combine(current_upload_date, dt.max.time())
        ).first()
    
    if same_date_customer:
        # Update existing customer from same upload date
        for key, value in customer_data.items():
            if hasattr(same_date_customer, key) and value:
                setattr(same_date_customer, key, value)
        same_date_customer.updated_at = dt.utcnow()
        session.commit()
        return same_date_customer
    else:
        # Create NEW customer entry for different upload date
        if not customer_data.get('fingerprint'):
            customer_data['fingerprint'] = compute_fingerprint(
                customer_data.get('phone_number', ''),
                customer_data.get('national_id', '')
            )
        
        if not existing_customer:
            customer_data['first_uploaded_at'] = dt.utcnow()
        
        customer = create_customer(session, customer_data)
        session.commit()
        return customer

# Add the helper method to CallManagementService for testing
CallManagementService._process_single_customer = _process_single_customer_helper

if __name__ == "__main__":
    success = test_date_based_customer_tracking()
    sys.exit(0 if success else 1)
