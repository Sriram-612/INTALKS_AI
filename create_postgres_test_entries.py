#!/usr/bin/env python3
"""
Script to create test entries with yesterday and today's dates using PostgreSQL database
"""

import os
import json
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup IST timezone
ist = pytz.timezone('Asia/Kolkata')

def create_test_entries():
    # Import after loading env vars
    from database.schemas import get_session, Customer, Loan
    
    # Get today and yesterday dates in IST
    today = datetime.now(ist)
    yesterday = today - timedelta(days=1)
    
    # Format dates for database
    today_dt = today.replace(tzinfo=None)  # Remove timezone for database
    yesterday_dt = yesterday.replace(tzinfo=None)
    
    print(f"Creating test entries for:")
    print(f"Today: {today_dt}")
    print(f"Yesterday: {yesterday_dt}")
    
    # Get database session
    session = get_session()
    
    try:
        # Clear existing test data
        existing_customers = session.query(Customer).filter(
            Customer.full_name.in_(['Rajesh Kumar', 'Priya Singh'])
        ).all()
        
        for customer in existing_customers:
            # Delete associated loans first
            session.query(Loan).filter(Loan.customer_id == customer.id).delete()
            session.delete(customer)
        
        session.commit()
        print(f"🗑️ Cleared existing test data")
        
        # Test entries for today - Same customer details
        today_customers_data = [
            {
                'full_name': 'Rajesh Kumar',
                'primary_phone': '+91-9876543210',
                'state': 'Maharashtra',
                'email': 'rajesh.kumar@email.com',
                'national_id': 'AADHAAR123456789',
                'upload_date': today_dt,
                'loan_data': {
                    'loan_id': 'LN001',
                    'amount': 250000,
                    'outstanding_amount': 225000,
                    'due_amount': 225000,
                    'due_date': today + timedelta(days=2),
                    'cluster': 'Mumbai Central',
                    'branch': 'Mumbai Main',
                    'branch_contact': '+91-22-12345678',
                    'employee_name': 'Amit Sharma',
                    'employee_id': 'EMP001',
                    'employee_contact': '+91-9123456789',
                    'last_paid_date': today - timedelta(days=29),
                    'last_paid_amount': 25000
                }
            },
            {
                'full_name': 'Priya Singh',
                'primary_phone': '+91-9876543211',
                'state': 'Delhi',
                'email': 'priya.singh@email.com',
                'national_id': 'AADHAAR987654321',
                'upload_date': today_dt,
                'loan_data': {
                    'loan_id': 'LN002',
                    'amount': 150000,
                    'outstanding_amount': 135000,
                    'due_amount': 135000,
                    'due_date': today + timedelta(days=7),
                    'cluster': 'Delhi North',
                    'branch': 'Delhi Branch',
                    'branch_contact': '+91-11-12345678',
                    'employee_name': 'Sunita Verma',
                    'employee_id': 'EMP002',
                    'employee_contact': '+91-9123456790',
                    'last_paid_date': today - timedelta(days=34),
                    'last_paid_amount': 15000
                }
            }
        ]
        
        # Test entries for yesterday - SAME customer details but different upload date
        yesterday_customers_data = [
            {
                'full_name': 'Rajesh Kumar',  # Same name
                'primary_phone': '+91-9876543210',  # Same phone
                'state': 'Maharashtra',  # Same state
                'email': 'rajesh.kumar@email.com',  # Same email
                'national_id': 'AADHAAR123456789',  # Same national ID
                'upload_date': yesterday_dt,  # Different upload date
                'loan_data': {
                    'loan_id': 'LN001',  # Same loan ID
                    'amount': 250000,  # Same amount
                    'outstanding_amount': 225000,  # Same outstanding
                    'due_amount': 225000,  # Same due amount
                    'due_date': today + timedelta(days=2),  # Same due date
                    'cluster': 'Mumbai Central',  # Same cluster
                    'branch': 'Mumbai Main',  # Same branch
                    'branch_contact': '+91-22-12345678',  # Same branch contact
                    'employee_name': 'Amit Sharma',  # Same employee
                    'employee_id': 'EMP001',  # Same employee ID
                    'employee_contact': '+91-9123456789',  # Same employee contact
                    'last_paid_date': today - timedelta(days=29),  # Same last paid date
                    'last_paid_amount': 25000  # Same last paid amount
                }
            },
            {
                'full_name': 'Priya Singh',  # Same name
                'primary_phone': '+91-9876543211',  # Same phone
                'state': 'Delhi',  # Same state
                'email': 'priya.singh@email.com',  # Same email
                'national_id': 'AADHAAR987654321',  # Same national ID
                'upload_date': yesterday_dt,  # Different upload date
                'loan_data': {
                    'loan_id': 'LN002',  # Same loan ID
                    'amount': 150000,  # Same amount
                    'outstanding_amount': 135000,  # Same outstanding
                    'due_amount': 135000,  # Same due amount
                    'due_date': today + timedelta(days=7),  # Same due date
                    'cluster': 'Delhi North',  # Same cluster
                    'branch': 'Delhi Branch',  # Same branch
                    'branch_contact': '+91-11-12345678',  # Same branch contact
                    'employee_name': 'Sunita Verma',  # Same employee
                    'employee_id': 'EMP002',  # Same employee ID
                    'employee_contact': '+91-9123456790',  # Same employee contact
                    'last_paid_date': today - timedelta(days=34),  # Same last paid date
                    'last_paid_amount': 15000  # Same last paid amount
                }
            }
        ]
        
        # Insert today's entries
        for customer_data in today_customers_data:
            loan_data = customer_data.pop('loan_data')
            customer = Customer(**customer_data)
            session.add(customer)
            session.flush()  # Get the customer ID
            
            # Add loan
            loan = Loan(
                customer_id=customer.id,
                **loan_data
            )
            session.add(loan)
            print(f"✅ Added TODAY entry: {customer.full_name} (uploaded today)")
        
        # Insert yesterday's entries
        for customer_data in yesterday_customers_data:
            loan_data = customer_data.pop('loan_data')
            customer = Customer(**customer_data)
            session.add(customer)
            session.flush()  # Get the customer ID
            
            # Add loan
            loan = Loan(
                customer_id=customer.id,
                **loan_data
            )
            session.add(loan)
            print(f"✅ Added YESTERDAY entry: {customer.full_name} (uploaded yesterday)")
        
        # Commit all changes
        session.commit()
        
        # Verify entries
        test_customers = session.query(Customer).filter(
            Customer.full_name.in_(['Rajesh Kumar', 'Priya Singh'])
        ).order_by(Customer.full_name, Customer.upload_date).all()
        
        print(f"\n📊 Verification - Found {len(test_customers)} test entries in PostgreSQL:")
        for customer in test_customers:
            # Determine if today or yesterday
            if customer.upload_date.date() == today.date():
                date_label = "TODAY"
            elif customer.upload_date.date() == yesterday.date():
                date_label = "YESTERDAY"
            else:
                date_label = "OTHER"
                
            print(f"  - {customer.full_name}: {customer.upload_date} ({date_label})")
        
        print(f"\n🎉 Duplicate test data created successfully in PostgreSQL!")
        print(f"📝 You can now test the date filters and duplicate handling:")
        print(f"   - Filter by 'Today' should show: Rajesh Kumar, Priya Singh (today's uploads)")
        print(f"   - Filter by 'Yesterday' should show: Rajesh Kumar, Priya Singh (yesterday's uploads)")
        print(f"   - All customers filter should show: 4 entries total (2 duplicates each)")
        print(f"   - Test how the system handles duplicate customers with different upload dates")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    create_test_entries()
