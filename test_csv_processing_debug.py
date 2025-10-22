#!/usr/bin/env python3
"""
Debug CSV Processing with Real Data
Test the exact CSV content and see where the data gets lost
"""
import asyncio
import sys
import pandas as pd
import io

# Add project root to path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

# Test CSV content (same as uploaded)
csv_content = """Name,Phone,Loan ID,Amount,Due Date,State,Cluster,Branch,Branch Contact,Employee,Employee ID,Employee Contact,Last Paid Date,Last Paid Amount,Due Amount
Rahul Sharma,9876543210,LN1001,50000,2025-10-15,Maharashtra,Cluster A,Mumbai Branch,+912233445566,John Doe,EMP001,+919876543211,2025-09-01,10000,40000
Priya Nair,9123456780,LN1002,75000,2025-11-05,Kerala,Cluster B,Kerala Branch,+914433221100,Jane Smith,EMP002,+919876543212,2025-08-15,25000,50000
Amit Patel,9988776655,LN1003,30000,2025-10-20,Gujarat,Cluster A,Gujarat Branch,+917766554433,Bob Johnson,EMP003,+919876543213,2025-09-10,5000,25000
Sneha Gupta,9871234567,LN1004,90000,2025-12-01,Uttar Pradesh,Cluster C,UP Branch,+918899776655,Alice Wilson,EMP004,+919876543214,2025-08-30,20000,70000"""

def normalize_column_name(col_name):
    """Normalize column names by removing spaces and converting to lowercase"""
    return str(col_name).lower().replace(' ', '_').replace('-', '_')

async def test_csv_processing():
    """Test the CSV processing step by step"""
    print("🔍 Testing CSV Processing Step by Step")
    print("=" * 60)
    
    # Step 1: Parse CSV
    df = pd.read_csv(io.StringIO(csv_content))
    print(f"📊 Parsed {len(df)} rows")
    print(f"📋 Columns: {list(df.columns)}")
    
    # Step 2: Create column mapping
    actual_columns = {}
    for col in df.columns:
        normalized = normalize_column_name(col)
        actual_columns[normalized] = col
    
    print(f"\n🔄 Normalized columns: {actual_columns}")
    
    # Step 3: Column mapping
    column_mapping = {
        'name': 'name',
        'phone': 'phone_number', 
        'state': 'state',
        'loan_id': 'loan_id',
        'amount': 'amount',
        'due_amount': 'due_amount',
        'due_date': 'due_date',
        'cluster': 'cluster',
        'branch': 'branch',
        'branch_contact': 'branch_contact',
        'employee': 'employee_name',
        'employee_id': 'employee_id',
        'employee_contact': 'employee_contact',
        'last_paid_amount': 'last_paid_amount',
        'last_paid_date': 'last_paid_date'
    }
    
    # Step 4: Process each row
    customers = []
    for idx, row in df.iterrows():
        customer_data = {}
        
        # Map columns using normalized names
        for normalized_col, internal_field in column_mapping.items():
            if normalized_col in actual_columns:
                actual_col = actual_columns[normalized_col]
                value = row[actual_col]
                customer_data[internal_field] = str(value) if pd.notna(value) else ''
        
        print(f"\n👤 Customer {idx + 1}: {customer_data.get('name')}")
        print(f"   📞 Phone: {customer_data.get('phone_number')}")
        print(f"   🏢 Cluster: '{customer_data.get('cluster')}'")
        print(f"   🏦 Branch: '{customer_data.get('branch')}'")
        print(f"   📞 Branch Contact: '{customer_data.get('branch_contact')}'")
        print(f"   👨‍💼 Employee: '{customer_data.get('employee_name')}'")
        print(f"   🆔 Employee ID: '{customer_data.get('employee_id')}'")
        print(f"   📞 Employee Contact: '{customer_data.get('employee_contact')}'")
        print(f"   💰 Last Paid Amount: '{customer_data.get('last_paid_amount')}'")
        print(f"   📅 Last Paid Date: '{customer_data.get('last_paid_date')}'")
        print(f"   💵 Due Amount: '{customer_data.get('due_amount')}'")
        
        customers.append(customer_data)
    
    return customers

if __name__ == "__main__":
    asyncio.run(test_csv_processing())
