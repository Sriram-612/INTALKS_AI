#!/usr/bin/env python3
"""
Test script to upload duplicate customers with different upload dates:
- Today (27/09/2025)
- Yesterday (26/09/2025) 
- Day before yesterday (25/09/2025)
"""

import sys
import os
from datetime import datetime, timedelta

# Add the project root to Python path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

from database.schemas import get_session, Customer, compute_fingerprint
from sqlalchemy.exc import IntegrityError

def create_customer_with_date(session, customer_data, upload_date):
    """Create a customer entry with a specific upload date"""
    try:
        # Generate unique fingerprint with timestamp to ensure uniqueness
        unique_data = f"{customer_data['name']}_{customer_data['phone']}_{upload_date.isoformat()}"
        fingerprint = compute_fingerprint(unique_data)
        
        customer = Customer(
            full_name=customer_data['name'],
            primary_phone=customer_data['phone'],
            state=customer_data['state'],
            loan_id=customer_data['loan_id'],
            amount=customer_data['amount'],
            due_date=customer_data['due_date'],
            language_code=customer_data['language_code'],
            fingerprint=fingerprint,
            created_at=upload_date,  # Set specific upload date
            updated_at=upload_date
        )
        
        session.add(customer)
        session.commit()
        print(f"✅ Created: {customer.full_name} ({customer.primary_phone}) - Upload Date: {upload_date.strftime('%d/%m/%Y %H:%M:%S')}")
        return True
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error creating {customer_data['name']}: {e}")
        return False

def main():
    print("🚀 Creating multiple duplicate customers with different upload dates")
    print("=" * 70)
    
    # Calculate dates
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    day_before_yesterday = today - timedelta(days=2)
    
    print(f"📅 Today: {today.strftime('%d/%m/%Y')}")
    print(f"📅 Yesterday: {yesterday.strftime('%d/%m/%Y')}")
    print(f"📅 Day Before Yesterday: {day_before_yesterday.strftime('%d/%m/%Y')}")
    print()
    
    # Test customers with same phone numbers but different data
    test_customers = [
        # Same phone +919988776655 (John Doe variations)
        {
            'name': 'John Doe Mumbai',
            'phone': '+919988776655',
            'state': 'Maharashtra',
            'loan_id': 'LOAN004',
            'amount': '₹125,000',
            'due_date': '28/10/2025',
            'language_code': 'mr-IN'
        },
        {
            'name': 'John Doe Bangalore',
            'phone': '+919988776655',
            'state': 'Karnataka', 
            'loan_id': 'LOAN005',
            'amount': '₹150,000',
            'due_date': '29/10/2025',
            'language_code': 'kn-IN'
        },
        {
            'name': 'John Doe Chennai',
            'phone': '+919988776655',
            'state': 'Tamil Nadu',
            'loan_id': 'LOAN006', 
            'amount': '₹175,000',
            'due_date': '30/10/2025',
            'language_code': 'ta-IN'
        },
        
        # Same phone +918877665544 (Priya variations)
        {
            'name': 'Priya Sharma Delhi',
            'phone': '+918877665544',
            'state': 'Delhi',
            'loan_id': 'LOAN007',
            'amount': '₹80,000',
            'due_date': '31/10/2025',
            'language_code': 'hi-IN'
        },
        {
            'name': 'Priya Sharma Jaipur', 
            'phone': '+918877665544',
            'state': 'Rajasthan',
            'loan_id': 'LOAN008',
            'amount': '₹95,000',
            'due_date': '01/11/2025',
            'language_code': 'hi-IN'
        },
        {
            'name': 'Priya Sharma Ahmedabad',
            'phone': '+918877665544', 
            'state': 'Gujarat',
            'loan_id': 'LOAN009',
            'amount': '₹110,000',
            'due_date': '02/11/2025',
            'language_code': 'gu-IN'
        },
        
        # Same phone +917766554433 (Rajesh variations)
        {
            'name': 'Rajesh Kumar Hyderabad',
            'phone': '+917766554433',
            'state': 'Telangana', 
            'loan_id': 'LOAN010',
            'amount': '₹200,000',
            'due_date': '03/11/2025',
            'language_code': 'te-IN'
        },
        {
            'name': 'Rajesh Kumar Kolkata',
            'phone': '+917766554433',
            'state': 'West Bengal',
            'loan_id': 'LOAN011',
            'amount': '₹225,000', 
            'due_date': '04/11/2025',
            'language_code': 'bn-IN'
        },
        {
            'name': 'Rajesh Kumar Kochi',
            'phone': '+917766554433',
            'state': 'Kerala',
            'loan_id': 'LOAN012',
            'amount': '₹250,000',
            'due_date': '05/11/2025',
            'language_code': 'ml-IN'
        }
    ]
    
    session = get_session()
    
    try:
        total_created = 0
        
        # Create customers for each date
        for i, customer in enumerate(test_customers):
            print(f"\n📋 Processing Customer {i+1}: {customer['name']} ({customer['phone']})")
            
            # Create entry for today
            if create_customer_with_date(session, customer, today):
                total_created += 1
            
            # Create entry for yesterday  
            if create_customer_with_date(session, customer, yesterday):
                total_created += 1
                
            # Create entry for day before yesterday
            if create_customer_with_date(session, customer, day_before_yesterday):
                total_created += 1
        
        print(f"\n🎉 SUCCESS SUMMARY")
        print("=" * 50)
        print(f"📊 Total customers created: {total_created}")
        print(f"👥 Unique phone numbers: {len(set(c['phone'] for c in test_customers))}")
        print(f"📅 Date range: {day_before_yesterday.strftime('%d/%m/%Y')} to {today.strftime('%d/%m/%Y')}")
        print()
        
        # Verify the data
        print("🔍 VERIFICATION - Checking created entries:")
        print("-" * 50)
        
        for phone in ['+919988776655', '+918877665544', '+917766554433']:
            customers = session.query(Customer).filter(Customer.primary_phone == phone).all()
            print(f"\n📞 Phone: {phone} ({len(customers)} entries)")
            
            for customer in sorted(customers, key=lambda c: c.created_at):
                upload_date = customer.created_at.strftime('%d/%m/%Y')
                print(f"  • {customer.full_name} - {customer.state} - {customer.loan_id} - {upload_date}")
        
    except Exception as e:
        print(f"❌ Error in main process: {e}")
        session.rollback()
    finally:
        session.close()
        print(f"\n✅ Database session closed")

if __name__ == "__main__":
    main()
