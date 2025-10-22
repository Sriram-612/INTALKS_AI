#!/usr/bin/env python3
"""
Database Schema Migration Verification Test
Tests that all existing functionality works with the new schema
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.schemas import (
    get_session, init_database, 
    Customer, CallSession, Loan, FileUpload,
    create_customer, create_call_session, update_call_status,
    get_customer_by_phone, get_call_session_by_sid,
    CallStatus, db_manager
)
from datetime import datetime

def test_backward_compatibility():
    """Test that all legacy property access works"""
    print("🧪 Testing backward compatibility...")
    
    session = get_session()
    try:
        # Test customer creation with old-style data
        customer_data = {
            'name': 'Test Customer',  # Old field name
            'phone_number': '+919876543210',  # Old field name
            'state': 'Karnataka',
            'loan_id': 'TEST001',  # Legacy field
            'amount': '50000',     # Legacy field
            'due_date': '2024-01-15'  # Legacy field
        }
        
        customer = create_customer(session, customer_data)
        if not customer:
            print("❌ Customer creation failed")
            return False
            
        print(f"✅ Customer created: {customer.id}")
        
        # Test legacy property access
        assert customer.name == 'Test Customer', "name property failed"
        assert customer.phone_number == '+919876543210', "phone_number property failed"
        assert customer.loan_id == 'TEST001', "loan_id legacy field failed"
        assert customer.amount == '50000', "amount legacy field failed"
        assert customer.due_date == '2024-01-15', "due_date legacy field failed"
        
        print("✅ All legacy property access working")
        
        # Test call session creation
        call_session = create_call_session(session, 'test_call_123', customer.id, 'ws_session_123')
        if not call_session:
            print("❌ Call session creation failed")
            return False
            
        print(f"✅ Call session created: {call_session.id}")
        
        # Test legacy call session properties
        assert call_session.start_time == call_session.initiated_at, "start_time property failed"
        assert call_session.duration == call_session.duration_seconds, "duration property failed"
        
        print("✅ Call session legacy properties working")
        
        # Test call status update
        updated_session = update_call_status(session, 'test_call_123', CallStatus.IN_PROGRESS, 'Test message')
        if not updated_session:
            print("❌ Call status update failed")
            return False
            
        print("✅ Call status update working")
        
        # Test customer lookup by phone
        found_customer = get_customer_by_phone(session, '+919876543210')
        if not found_customer or found_customer.id != customer.id:
            print("❌ Customer lookup by phone failed")
            return False
            
        print("✅ Customer lookup by phone working")
        
        # Test call session lookup by SID
        found_call = get_call_session_by_sid(session, 'test_call_123')
        if not found_call or found_call.id != call_session.id:
            print("❌ Call session lookup by SID failed")
            return False
            
        print("✅ Call session lookup by SID working")
        
        # Clean up
        session.delete(call_session)
        session.delete(customer)
        session.commit()
        
        print("✅ All backward compatibility tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Backward compatibility test failed: {e}")
        session.rollback()
        return False
    finally:
        session.close()

def test_new_features():
    """Test new schema features"""
    print("🧪 Testing new features...")
    
    session = get_session()
    try:
        # Test customer fingerprinting
        customer1 = Customer(
            fingerprint='test_fingerprint_1',
            full_name='New Feature Customer',
            primary_phone='+919876543211',
            first_uploaded_at=datetime.utcnow()
        )
        session.add(customer1)
        session.flush()
        
        print(f"✅ Customer with fingerprint created: {customer1.id}")
        
        # Test loan creation
        loan = Loan(
            customer_id=customer1.id,
            loan_id='NEWLOAN001',
            outstanding_amount=75000.00,
            branch='Test Branch',
            employee_name='Test Employee'
        )
        session.add(loan)
        session.flush()
        
        print(f"✅ Loan created: {loan.id}")
        
        # Test file upload tracking
        file_upload = FileUpload(
            filename='test_upload.csv',
            uploaded_by='test_user',
            total_records=100,
            status='processing'
        )
        session.add(file_upload)
        session.flush()
        
        print(f"✅ File upload created: {file_upload.id}")
        
        # Test call session with batch tracking
        call_session = CallSession(
            call_sid='new_call_123',
            customer_id=customer1.id,
            loan_id=loan.id,
            triggered_by_batch=file_upload.id,
            to_number='+919876543211'
        )
        session.add(call_session)
        session.flush()
        
        print(f"✅ Call session with batch tracking created: {call_session.id}")
        
        # Test relationships
        assert len(customer1.loans) == 1, "Customer-Loan relationship failed"
        assert len(customer1.call_sessions) == 1, "Customer-CallSession relationship failed"
        assert call_session.customer.id == customer1.id, "CallSession-Customer relationship failed"
        assert call_session.loan.id == loan.id, "CallSession-Loan relationship failed"
        
        print("✅ All relationships working correctly")
        
        # Clean up
        session.delete(call_session)
        session.delete(loan)
        session.delete(file_upload)
        session.delete(customer1)
        session.commit()
        
        print("✅ All new feature tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ New feature test failed: {e}")
        session.rollback()
        return False
    finally:
        session.close()

def main():
    """Run all tests"""
    print("🚀 Starting Database Schema Migration Verification Tests")
    print("=" * 60)
    
    # Test database connection
    if not db_manager.test_connection():
        print("❌ Database connection failed")
        return False
    
    # Test database initialization
    if not init_database():
        print("❌ Database initialization failed")
        return False
    
    print("✅ Database initialized successfully")
    print()
    
    # Run tests
    tests_passed = 0
    total_tests = 2
    
    if test_backward_compatibility():
        tests_passed += 1
    
    print()
    
    if test_new_features():
        tests_passed += 1
    
    print()
    print("=" * 60)
    print(f"📊 Test Results: {tests_passed}/{total_tests} passed")
    
    if tests_passed == total_tests:
        print("🎉 All tests passed! Database migration verification successful!")
        return True
    else:
        print("❌ Some tests failed. Please check the issues above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
