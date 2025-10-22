#!/usr/bin/env python3
"""
Debug Loan Creation Process
Check exactly what data is passed to loan creation
"""
import asyncio
import sys
import io

# Add project root to path
sys.path.append('/home/cyberdude/Documents/Projects/voice')

from services.call_management import CallManagementService

# Test CSV content
csv_content = """Name,Phone,Loan ID,Amount,Due Date,State,Cluster,Branch,Branch Contact,Employee,Employee ID,Employee Contact,Last Paid Date,Last Paid Amount,Due Amount
Test User,9999999999,TEST123,50000,2025-10-15,Maharashtra,Test Cluster,Test Branch,+912233445566,Test Employee,TEST001,+919876543211,2025-09-01,10000,40000"""

async def debug_loan_creation():
    """Debug the loan creation process"""
    print("🔍 Debugging Loan Creation Process")
    print("=" * 60)
    
    call_service = CallManagementService()
    
    # Parse the CSV
    customers_data = await call_service._parse_customer_file(csv_content.encode(), 'test.csv')
    
    print(f"📊 Parsed {len(customers_data)} customer(s)")
    
    for idx, customer_data in enumerate(customers_data):
        print(f"\n👤 Customer {idx + 1}: {customer_data.get('name')}")
        print("📋 Full customer_data content:")
        for key, value in customer_data.items():
            print(f"   {key}: '{value}'")
        
        print("\n🏦 Loan fields that would be used:")
        print(f"   cluster: '{customer_data.get('cluster')}'")
        print(f"   branch: '{customer_data.get('branch')}'")
        print(f"   branch_contact: '{customer_data.get('branch_contact')}'")
        print(f"   employee_name: '{customer_data.get('employee_name')}'")
        print(f"   employee_id: '{customer_data.get('employee_id')}'")
        print(f"   employee_contact: '{customer_data.get('employee_contact')}'")
        print(f"   last_paid_amount: '{customer_data.get('last_paid_amount')}'")
        print(f"   last_paid_date: '{customer_data.get('last_paid_date')}'")
        print(f"   due_amount: '{customer_data.get('due_amount')}'")

if __name__ == "__main__":
    asyncio.run(debug_loan_creation())
