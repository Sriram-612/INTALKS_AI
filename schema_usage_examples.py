#!/usr/bin/env python3
"""
New Database Schema Usage Examples
==================================
This file demonstrates how to use the new enhanced database schema features.
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.schemas import (
    get_session, Customer, Loan, FileUpload, UploadRow, CallSession,
    create_customer, create_loan, create_call_session,
    compute_fingerprint, normalize_phone
)
from datetime import datetime, date

def example_customer_deduplication():
    """Example: Customer deduplication using fingerprinting"""
    print("🔍 Example: Customer Deduplication")
    print("-" * 40)
    
    session = get_session()
    try:
        # Example CSV data with potential duplicates
        csv_rows = [
            {"name": "John Doe", "phone": "+91-9876-543-210", "aadhar": "1234-5678-9012"},
            {"name": "John Doe", "phone": "9876543210", "aadhar": "123456789012"},  # Same person, different format
            {"name": "Jane Smith", "phone": "+919876543211", "aadhar": "2345678901"},
        ]
        
        for i, row in enumerate(csv_rows):
            # Normalize and create fingerprint
            normalized_phone = normalize_phone(row["phone"])
            fingerprint = compute_fingerprint(normalized_phone, row["aadhar"])
            
            # Check if customer already exists
            existing_customer = session.query(Customer).filter(Customer.fingerprint == fingerprint).first()
            
            if existing_customer:
                print(f"Row {i+1}: ✅ Duplicate detected - Customer already exists: {existing_customer.full_name}")
            else:
                # Create new customer
                customer = Customer(
                    fingerprint=fingerprint,
                    full_name=row["name"],
                    primary_phone=normalized_phone,
                    national_id=row["aadhar"],
                    first_uploaded_at=datetime.utcnow()
                )
                session.add(customer)
                session.flush()
                print(f"Row {i+1}: ✨ New customer created: {customer.full_name} (ID: {customer.id})")
        
        session.commit()
        print("✅ Deduplication complete")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        session.rollback()
    finally:
        session.close()

def example_loan_management():
    """Example: Managing customer loans with relationships"""
    print("\n💰 Example: Loan Management")
    print("-" * 40)
    
    session = get_session()
    try:
        # Create customer
        customer = Customer(
            fingerprint=compute_fingerprint("+919876543999", "9999888877"),
            full_name="Alice Johnson",
            primary_phone="+919876543999",
            national_id="9999888877",
            email="alice@example.com",
            state="Karnataka"
        )
        session.add(customer)
        session.flush()
        print(f"✨ Customer created: {customer.full_name}")
        
        # Create multiple loans for the customer
        loans = [
            {
                "loan_id": "HOME001",
                "outstanding_amount": 2500000.00,
                "next_due_date": date(2024, 1, 15),
                "branch": "Bangalore Main",
                "employee_name": "Rahul Kumar"
            },
            {
                "loan_id": "PERSONAL002", 
                "outstanding_amount": 150000.00,
                "next_due_date": date(2024, 1, 10),
                "branch": "Bangalore Main",
                "employee_name": "Priya Sharma"
            }
        ]
        
        for loan_data in loans:
            loan = Loan(
                customer_id=customer.id,
                **loan_data
            )
            session.add(loan)
            session.flush()
            print(f"💰 Loan created: {loan.loan_id} - ₹{loan.outstanding_amount}")
        
        session.commit()
        
        # Query customer with loans
        customer_with_loans = session.query(Customer).filter(Customer.id == customer.id).first()
        print(f"\n📊 Customer {customer_with_loans.full_name} has {len(customer_with_loans.loans)} loans:")
        for loan in customer_with_loans.loans:
            print(f"   • {loan.loan_id}: ₹{loan.outstanding_amount} (Due: {loan.next_due_date})")
        
        print("✅ Loan management complete")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        session.rollback()
    finally:
        session.close()

def example_batch_upload_tracking():
    """Example: Tracking batch uploads and CSV processing"""
    print("\n📁 Example: Batch Upload Tracking")
    print("-" * 40)
    
    session = get_session()
    try:
        # Create file upload record
        file_upload = FileUpload(
            filename="customers_batch_2024_01.csv",
            uploaded_by="admin@bank.com",
            total_records=1000,
            status="processing"
        )
        session.add(file_upload)
        session.flush()
        print(f"📄 File upload created: {file_upload.filename}")
        
        # Simulate processing individual rows
        sample_rows = [
            {"line": 1, "name": "Customer 1", "phone": "9876543001", "loan": "LOAN001"},
            {"line": 2, "name": "Customer 2", "phone": "9876543002", "loan": "LOAN002"},
            {"line": 3, "name": "Customer 3", "phone": "9876543003", "loan": "LOAN003"},
        ]
        
        for row_data in sample_rows:
            # Create upload row record
            upload_row = UploadRow(
                file_upload_id=file_upload.id,
                line_number=row_data["line"],
                raw_data=row_data,
                phone_normalized=normalize_phone(row_data["phone"]),
                loan_id_text=row_data["loan"],
                row_fingerprint=f"row_{row_data['line']}_{file_upload.id}",
                status="processed"
            )
            session.add(upload_row)
            
        # Update file upload status
        file_upload.processed_records = len(sample_rows)
        file_upload.success_records = len(sample_rows)
        file_upload.status = "completed"
        
        session.commit()
        print(f"✅ Processed {len(sample_rows)} rows successfully")
        
        # Query upload with rows
        upload_with_rows = session.query(FileUpload).filter(FileUpload.id == file_upload.id).first()
        print(f"📊 Upload {upload_with_rows.filename}:")
        print(f"   • Total: {upload_with_rows.total_records}")
        print(f"   • Processed: {upload_with_rows.processed_records}")
        print(f"   • Success: {upload_with_rows.success_records}")
        print(f"   • Status: {upload_with_rows.status}")
        
        print("✅ Batch upload tracking complete")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        session.rollback()
    finally:
        session.close()

def example_enhanced_call_tracking():
    """Example: Enhanced call tracking with batch and loan relationships"""
    print("\n📞 Example: Enhanced Call Tracking")
    print("-" * 40)
    
    session = get_session()
    try:
        # Get existing customer and loan (from previous examples)
        customer = session.query(Customer).filter(Customer.primary_phone.like("%9876543999")).first()
        if not customer:
            print("⚠️ No customer found from previous examples")
            return
            
        loan = customer.loans[0] if customer.loans else None
        
        # Create batch upload
        batch = FileUpload(
            filename="call_batch_2024_01_15.csv",
            uploaded_by="system",
            total_records=50,
            status="completed"
        )
        session.add(batch)
        session.flush()
        
        # Create enhanced call session
        call_session = CallSession(
            call_sid="exotel_sid_123456",
            customer_id=customer.id,
            loan_id=loan.id if loan else None,
            triggered_by_batch=batch.id,
            to_number=customer.primary_phone,
            status="initiated"
        )
        session.add(call_session)
        session.commit()
        
        print(f"📞 Call session created: {call_session.call_sid}")
        print(f"   • Customer: {customer.full_name}")
        print(f"   • Loan: {loan.loan_id if loan else 'None'}")
        print(f"   • Triggered by batch: {batch.filename}")
        print(f"   • Status: {call_session.status}")
        
        # Query call with relationships
        call_with_relations = session.query(CallSession).filter(CallSession.id == call_session.id).first()
        print(f"\n🔗 Call relationships:")
        print(f"   • Customer: {call_with_relations.customer.full_name}")
        if call_with_relations.loan:
            print(f"   • Loan: {call_with_relations.loan.loan_id} (₹{call_with_relations.loan.outstanding_amount})")
        print(f"   • Triggered by: {call_with_relations.triggering_batch.filename}")
        
        print("✅ Enhanced call tracking complete")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        session.rollback()
    finally:
        session.close()

def example_analytics_queries():
    """Example: Analytics queries using the new schema"""
    print("\n📊 Example: Analytics Queries")
    print("-" * 40)
    
    session = get_session()
    try:
        # Customer statistics
        total_customers = session.query(Customer).count()
        customers_with_loans = session.query(Customer).join(Loan).distinct().count()
        
        print(f"👥 Customer Statistics:")
        print(f"   • Total customers: {total_customers}")
        print(f"   • Customers with loans: {customers_with_loans}")
        
        # Loan statistics
        total_loans = session.query(Loan).count()
        total_outstanding = session.query(func.sum(Loan.outstanding_amount)).scalar() or 0
        
        print(f"\n💰 Loan Statistics:")
        print(f"   • Total loans: {total_loans}")
        print(f"   • Total outstanding: ₹{total_outstanding:,.2f}")
        
        # Call statistics
        total_calls = session.query(CallSession).count()
        calls_by_status = session.query(CallSession.status, func.count(CallSession.id)).group_by(CallSession.status).all()
        
        print(f"\n📞 Call Statistics:")
        print(f"   • Total calls: {total_calls}")
        for status, count in calls_by_status:
            print(f"   • {status}: {count}")
        
        # Upload statistics
        total_uploads = session.query(FileUpload).count()
        completed_uploads = session.query(FileUpload).filter(FileUpload.status == 'completed').count()
        
        print(f"\n📁 Upload Statistics:")
        print(f"   • Total uploads: {total_uploads}")
        print(f"   • Completed uploads: {completed_uploads}")
        
        print("✅ Analytics queries complete")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        session.close()

def main():
    """Run all examples"""
    print("🚀 New Database Schema Usage Examples")
    print("=" * 50)
    
    # Import required function for analytics
    from sqlalchemy import func
    globals()['func'] = func
    
    try:
        example_customer_deduplication()
        example_loan_management()
        example_batch_upload_tracking()
        example_enhanced_call_tracking()
        example_analytics_queries()
        
        print("\n" + "=" * 50)
        print("🎉 All examples completed successfully!")
        print("💡 Your voice assistant now has enhanced customer tracking,")
        print("   loan management, and analytics capabilities!")
        
    except Exception as e:
        print(f"❌ Example failed: {e}")

if __name__ == "__main__":
    main()
