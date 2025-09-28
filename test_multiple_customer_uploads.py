#!/usr/bin/env python3
"""
Test Multiple Customer Uploads with Different Dates
Shows what happens when the same customer is uploaded multiple times
"""

import sys
import os
from datetime import datetime, timedelta

# Add project root to path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

from database.schemas import get_session, Customer, FileUpload, UploadRow
from services.call_management import CallManagementService

def test_multiple_customer_uploads():
    """Test uploading the same customer on different dates"""
    
    print("🧪 Testing Multiple Customer Uploads with Different Dates")
    print("=" * 60)
    
    # Create test CSV content for same customer on different dates
    test_customer_data = {
        'Name': 'Raj Kumar',
        'Phone': '+919999888777',
        'Loan ID': 'TEST123',
        'Amount': '25000',
        'Due Date': '2025-11-15',
        'State': 'Karnataka',
        'Cluster': 'South Zone',
        'Branch': 'Bangalore Main',
        'Branch Contact': '+918012345678',
        'Employee': 'Arjun Shah', 
        'Employee ID': 'EMP789',
        'Employee Contact': '+919876543210',
        'Last Paid Date': '2025-09-01',
        'Last Paid Amount': '5000',
        'Due Amount': '20000'
    }
    
    call_service = CallManagementService()
    session = get_session()
    
    try:
        # Upload 1: First time (Day 1)
        print("\n📅 UPLOAD 1: First time upload (Day 1)")
        print("-" * 40)
        
        result1 = call_service.process_csv_content(
            content=create_csv_content(test_customer_data),
            filename=f"test_upload_day1_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            uploaded_by="test-user"
        )
        
        # Check customer count
        customer_count = session.query(Customer).filter(Customer.primary_phone == '+919999888777').count()
        customer = session.query(Customer).filter(Customer.primary_phone == '+919999888777').first()
        
        print(f"✅ Upload 1 Result: {result1['summary']}")
        print(f"📊 Total customers with this phone: {customer_count}")
        if customer:
            print(f"📋 Customer ID: {customer.id}")
            print(f"📅 First uploaded: {customer.first_uploaded_at}")
            print(f"🔄 Last updated: {customer.updated_at}")
        
        # Wait a moment to ensure different timestamps
        import time
        time.sleep(2)
        
        # Upload 2: Same customer, different date (Day 2) 
        print("\n📅 UPLOAD 2: Same customer, different date (Day 2)")
        print("-" * 40)
        
        # Modify some data to see if it updates
        test_customer_data['Amount'] = '30000'  # Changed amount
        test_customer_data['Employee'] = 'Priya Nair'  # Changed employee
        
        result2 = call_service.process_csv_content(
            content=create_csv_content(test_customer_data),
            filename=f"test_upload_day2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            uploaded_by="test-user"
        )
        
        # Check customer count again
        customer_count_after = session.query(Customer).filter(Customer.primary_phone == '+919999888777').count()
        customer_after = session.query(Customer).filter(Customer.primary_phone == '+919999888777').first()
        
        print(f"✅ Upload 2 Result: {result2['summary']}")
        print(f"📊 Total customers with this phone: {customer_count_after}")
        if customer_after:
            print(f"📋 Customer ID: {customer_after.id} (Same as before: {customer_after.id == customer.id})")
            print(f"📅 First uploaded: {customer_after.first_uploaded_at}")
            print(f"🔄 Last updated: {customer_after.updated_at}")
            print(f"💰 Amount updated: {customer.amount} → {customer_after.amount}")
            
        # Check upload history
        uploads = session.query(FileUpload).order_by(FileUpload.uploaded_at.desc()).limit(2).all()
        print(f"\n📁 Upload History:")
        for i, upload in enumerate(uploads, 1):
            print(f"   {i}. {upload.filename} - {upload.uploaded_at}")
            print(f"      Records: {upload.success_records} success, {upload.failed_records} failed")
        
        # Upload 3: Same customer, different date (Day 3)
        print("\n📅 UPLOAD 3: Same customer, different date (Day 3)")
        print("-" * 40)
        
        time.sleep(2)
        
        # Modify data again
        test_customer_data['Amount'] = '35000'  # Changed amount again
        test_customer_data['Due Date'] = '2025-12-15'  # Changed due date
        
        result3 = call_service.process_csv_content(
            content=create_csv_content(test_customer_data),
            filename=f"test_upload_day3_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            uploaded_by="test-user"
        )
        
        # Final check
        customer_count_final = session.query(Customer).filter(Customer.primary_phone == '+919999888777').count()
        customer_final = session.query(Customer).filter(Customer.primary_phone == '+919999888777').first()
        
        print(f"✅ Upload 3 Result: {result3['summary']}")
        print(f"📊 Total customers with this phone: {customer_count_final}")
        if customer_final:
            print(f"📋 Customer ID: {customer_final.id} (Same as original: {customer_final.id == customer.id})")
            print(f"📅 First uploaded: {customer_final.first_uploaded_at}")
            print(f"🔄 Last updated: {customer_final.updated_at}")
            print(f"💰 Final amount: {customer_final.amount}")
            print(f"📅 Final due date: {customer_final.due_date}")
        
        print("\n" + "=" * 60)
        print("🎯 CONCLUSION:")
        print(f"   • Same customer uploaded 3 times")
        print(f"   • Database contains {customer_count_final} record(s) for this phone")
        print(f"   • System behavior: {'UPDATE existing' if customer_count_final == 1 else 'CREATE new each time'}")
        print(f"   • Upload history tracked: {len(uploads)} separate file uploads")
        
    except Exception as e:
        print(f"❌ Error during test: {e}")
        
    finally:
        # Cleanup - remove test customer
        try:
            test_customer = session.query(Customer).filter(Customer.primary_phone == '+919999888777').first()
            if test_customer:
                session.delete(test_customer)
                session.commit()
                print(f"\n🧹 Cleanup: Removed test customer")
        except Exception as cleanup_error:
            print(f"⚠️ Cleanup warning: {cleanup_error}")
        
        session.close()

def create_csv_content(data):
    """Create CSV content from dictionary data"""
    headers = list(data.keys())
    values = list(data.values())
    
    csv_content = ','.join(headers) + '\n'
    csv_content += ','.join(str(v) for v in values) + '\n'
    
    return csv_content

if __name__ == "__main__":
    test_multiple_customer_uploads()
