#!/usr/bin/env python3

import requests
import json

def test_dashboard_display():
    """Test if enhanced fields are showing up on the dashboard"""
    
    url = 'http://localhost:8000/api/customers'
    
    try:
        response = requests.get(url)
        
        print(f"📡 Dashboard Response Status: {response.status_code}")
        
        if response.status_code == 200:
            customers = response.json()  # API returns customers directly as a list
            
            print(f"📊 Total customers: {len(customers)}")
            
            if customers:
                # Show the latest uploaded customer
                latest_customer = customers[-1]  # Assuming newest is last
                
                print(f"\n📝 Latest Customer Details:")
                print(f"  • Name: {latest_customer.get('name')}")
                print(f"  • Phone: {latest_customer.get('phone_number')}")
                print(f"  • State: {latest_customer.get('state')}")
                
                # Check if enhanced fields are present
                loans = latest_customer.get('loans', [])
                if loans:
                    loan = loans[0]
                    print(f"\n💰 Loan Information:")
                    print(f"  • Loan ID: {loan.get('loan_id')}")
                    print(f"  • Amount: {loan.get('outstanding_amount')}")
                    print(f"  • Due Date: {loan.get('next_due_date')}")
                    print(f"  • Cluster: {loan.get('cluster', 'N/A')}")
                    print(f"  • Branch: {loan.get('branch', 'N/A')}")
                    print(f"  • Employee Name: {loan.get('employee_name', 'N/A')}")
                    print(f"  • Employee ID: {loan.get('employee_id', 'N/A')}")
                    
                    # Check if enhanced fields are actually populated
                    enhanced_fields = ['cluster', 'branch', 'employee_name', 'employee_id']
                    populated_fields = [field for field in enhanced_fields if loan.get(field) and loan.get(field) != 'N/A']
                    
                    if populated_fields:
                        print(f"\n✅ Enhanced fields populated: {', '.join(populated_fields)}")
                    else:
                        print(f"\n⚠️ Enhanced fields are still empty/null")
                else:
                    print(f"\n⚠️ No loan information found for customer")
            else:
                print("📭 No customers found")
        else:
            print(f"❌ HTTP ERROR: {response.status_code}")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"❌ CONNECTION ERROR: {str(e)}")

if __name__ == '__main__':
    print("🔧 Testing dashboard display of enhanced fields...")
    test_dashboard_display()
