#!/usr/bin/env python3
"""
Fixes the missing due_date for the demo user 'Kushal Sharma'.
"""
import os
import sys
from datetime import date
from sqlalchemy import select

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.schemas import db_manager, Customer, Loan

def fix_kushal_sharma_due_date():
    """
    Finds the user 'Kushal Sharma' and updates their loan's next_due_date.
    """
    session = db_manager.get_session()
    try:
        print("🔍 Searching for customer with phone number +917417119014...")
        
        # Find the customer
        stmt_customer = select(Customer).where(Customer.primary_phone == '+917417119014')
        customer = session.execute(stmt_customer).scalar_one_or_none()

        if not customer:
            print("❌ Customer with phone +917417119014 not found. Please ensure the demo user is in the database.")
            return

        print(f"✅ Found customer: {customer.full_name} (ID: {customer.id})")
        
        # Check if the customer has the legacy fields populated
        print(f"Current customer data:")
        print(f"  - loan_id: {customer.loan_id}")
        print(f"  - amount: {customer.amount}")
        print(f"  - due_date: {customer.due_date}")

        # Update the customer's legacy fields if they're missing
        needs_update = False
        
        if not customer.loan_id:
            customer.loan_id = 'LN747'
            needs_update = True
            print("✅ Updated customer loan_id to 'LN747'")
            
        if not customer.amount:
            customer.amount = '12000'
            needs_update = True
            print("✅ Updated customer amount to '12000'")
            
        if not customer.due_date:
            customer.due_date = '2025-10-25'
            needs_update = True
            print("✅ Updated customer due_date to '2025-10-25'")
            
        if needs_update:
            session.commit()
            print("💾 Customer data saved to database")
        else:
            print("✅ Customer already has all required fields")

        # Also ensure loan table has proper data
        stmt_loan = select(Loan).where(Loan.customer_id == customer.id)
        loan = session.execute(stmt_loan).scalar_one_or_none()

        if not loan:
            print("🔧 Creating a new loan record for consistency...")
            new_loan = Loan(
                customer_id=customer.id,
                loan_id='LN747',  # Matching the one from the logs
                principal_amount=12000.0,
                outstanding_amount=12000.0,
                due_amount=1500.0,
                next_due_date=date(2025, 10, 25),
                status='active'
            )
            session.add(new_loan)
            session.commit()
            print(f"✅ Created new loan {new_loan.loan_id} for customer {customer.full_name}.")
        else:
            print(f"✅ Loan {loan.loan_id} already exists for customer {customer.full_name}.")

        print("\n🎉 Due date fix complete!")

    except Exception as e:
        print(f"❌ An error occurred: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    fix_kushal_sharma_due_date()
