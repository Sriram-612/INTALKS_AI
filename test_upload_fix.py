#!/usr/bin/env python3

import requests
import json

# Test the CSV upload with existing customers
def test_csv_upload():
    """Test CSV upload with customers that already exist in database"""
    
    # Create test CSV with same phone numbers as before
    csv_content = """Name,Mobile Number,Loan ID,Outstanding Amount,State,Due Date,Cluster,Branch,Employee Name,Employee ID
John Doe,9876543210,LOAN001,15000,Karnataka,2024-02-15,South Zone,Bangalore Branch,Agent Smith,EMP001
Jane Smith,9876543211,LOAN002,25000,Maharashtra,2024-02-20,West Zone,Mumbai Branch,Agent Jones,EMP002
Bob Johnson,9876543212,LOAN003,18000,Tamil Nadu,2024-02-25,South Zone,Chennai Branch,Agent Brown,EMP003
Alice Wilson,9876543213,LOAN004,22000,Delhi,2024-03-01,North Zone,Delhi Branch,Agent Davis,EMP004"""
    
    # Save to file
    with open('test_update_customers.csv', 'w') as f:
        f.write(csv_content)
    
    # Test upload
    url = 'http://localhost:8000/api/upload-customers'
    
    try:
        with open('test_update_customers.csv', 'rb') as f:
            files = {'file': ('test_update_customers.csv', f, 'text/csv')}
            response = requests.post(url, files=files)
        
        print(f"📡 Upload Response Status: {response.status_code}")
        print(f"📋 Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print("✅ SUCCESS: CSV upload completed successfully!")
                print(f"📊 Processed: {result.get('processed_records', 0)} records")
                print(f"📊 Failed: {result.get('failed_records', 0)} records")
                
                # Check customer details
                if result.get('processed_customers'):
                    print("\n📝 Customer Details:")
                    for customer in result['processed_customers'][:2]:  # Show first 2
                        print(f"  • {customer.get('name')} ({customer.get('phone_number')})")
                        print(f"    State: {customer.get('state')}, Loan: {customer.get('loan_id')}")
            else:
                print(f"❌ UPLOAD FAILED: {result.get('error', 'Unknown error')}")
        else:
            print(f"❌ HTTP ERROR: {response.status_code}")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"❌ CONNECTION ERROR: {str(e)}")

if __name__ == '__main__':
    print("🔧 Testing CSV upload with existing customers...")
    test_csv_upload()
