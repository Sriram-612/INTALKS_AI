#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.schemas import get_session, create_customer, create_loan
from datetime import datetime, date
import uuid

def insert_demo_user():
    """Insert demo user Kushal with phone +917417119014 from Uttar Pradesh"""
    
    session = get_session()
    
    try:
        # Demo user data
        customer_data = {
            'name': 'Kushal',
            'phone_number': '+917417119014',
            'state': 'Uttar Pradesh',
            'language_code': 'hi-IN',  # Hindi for Uttar Pradesh
            'national_id': '',
            'address': 'Uttar Pradesh, India',
            'first_uploaded_at': datetime.utcnow()
        }
        
        print(f"🔧 Creating demo customer: {customer_data['name']} ({customer_data['phone_number']})")
        
        # Create customer
        customer = create_customer(session, customer_data)
        
        if customer:
            print(f"✅ Customer created successfully!")
            print(f"   • ID: {customer.id}")
            print(f"   • Name: {customer.name}")
            print(f"   • Phone: {customer.phone_number}")
            print(f"   • State: {customer.state}")
            print(f"   • Language: {customer.language_code}")
            
            # Create a demo loan for this customer
            loan_data = {
                'customer_id': customer.id,
                'loan_id': 'DEMO001',
                'principal_amount': 50000.0,
                'outstanding_amount': 45000.0,
                'due_amount': 5000.0,
                'next_due_date': date(2025, 10, 15),
                'cluster': 'North Zone',
                'branch': 'Lucknow Branch',
                'branch_contact_number': '+91-9876543000',
                'employee_name': 'Demo Agent',
                'employee_id': 'DEMO_AGT_001',
                'employee_contact_number': '+91-9876543001',
                'last_paid_date': date(2025, 9, 15),
                'last_paid_amount': 5000.0
            }
            
            print(f"\n💰 Creating demo loan for customer...")
            loan = create_loan(session, loan_data)
            
            if loan:
                print(f"✅ Loan created successfully!")
                print(f"   • Loan ID: {loan.loan_id}")
                print(f"   • Outstanding: ₹{loan.outstanding_amount}")
                print(f"   • Due Amount: ₹{loan.due_amount}")
                print(f"   • Next Due: {loan.next_due_date}")
                print(f"   • Branch: {loan.branch}")
                print(f"   • Employee: {loan.employee_name}")
            else:
                print(f"❌ Failed to create loan")
        else:
            print(f"❌ Failed to create customer")
            
        session.commit()
        print(f"\n🎉 Demo user insertion completed successfully!")
        
    except Exception as e:
        print(f"❌ Error inserting demo user: {str(e)}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == '__main__':
    print("🚀 Inserting demo user data...")
    insert_demo_user()
