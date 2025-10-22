#!/usr/bin/env python3
"""
Script to create test entries with yesterday and today's dates for testing date filters
"""

import sqlite3
import json
from datetime import datetime, timedelta
import pytz

# Setup IST timezone
ist = pytz.timezone('Asia/Kolkata')

def create_test_entries():
    # Get today and yesterday dates in IST
    today = datetime.now(ist)
    yesterday = today - timedelta(days=1)
    
    # Format dates for database
    today_str = today.strftime('%Y-%m-%d %H:%M:%S')
    yesterday_str = yesterday.strftime('%Y-%m-%d %H:%M:%S')
    
    print(f"Creating test entries for:")
    print(f"Today: {today_str}")
    print(f"Yesterday: {yesterday_str}")
    
    # Connect to database
    conn = sqlite3.connect('database/customers.db')
    cursor = conn.cursor()
    
    # Create customers table if it doesn't exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            primary_phone TEXT,
            loans TEXT,
            upload_date TEXT,
            call_status TEXT DEFAULT 'ready'
        )
    ''')
    
    # Test entries for today - Same customer details
    today_customers = [
        {
            'full_name': 'Rajesh Kumar',
            'primary_phone': '+91-9876543210',
            'loans': json.dumps([{
                'loan_id': 'LN001',
                'amount': 250000,
                'due_date': '2025-09-15',
                'state': 'Maharashtra',
                'cluster': 'Mumbai Central',
                'branch': 'Mumbai Main',
                'branch_contact': '+91-22-12345678',
                'employee_name': 'Amit Sharma',
                'employee_id': 'EMP001',
                'employee_contact': '+91-9123456789',
                'last_paid_date': '2025-08-15',
                'last_paid_amount': 25000,
                'due_amount': 225000
            }]),
            'upload_date': today_str,
            'call_status': 'ready'
        },
        {
            'full_name': 'Priya Singh',
            'primary_phone': '+91-9876543211',
            'loans': json.dumps([{
                'loan_id': 'LN002',
                'amount': 150000,
                'due_date': '2025-09-20',
                'state': 'Delhi',
                'cluster': 'Delhi North',
                'branch': 'Delhi Branch',
                'branch_contact': '+91-11-12345678',
                'employee_name': 'Sunita Verma',
                'employee_id': 'EMP002',
                'employee_contact': '+91-9123456790',
                'last_paid_date': '2025-08-10',
                'last_paid_amount': 15000,
                'due_amount': 135000
            }]),
            'upload_date': today_str,
            'call_status': 'ready'
        }
    ]
    
    # Test entries for yesterday - SAME customer details but different upload date
    yesterday_customers = [
        {
            'full_name': 'Rajesh Kumar',  # Same name as today's entry
            'primary_phone': '+91-9876543210',  # Same phone as today's entry
            'loans': json.dumps([{
                'loan_id': 'LN001',  # Same loan ID
                'amount': 250000,  # Same amount
                'due_date': '2025-09-15',  # Same due date
                'state': 'Maharashtra',  # Same state
                'cluster': 'Mumbai Central',  # Same cluster
                'branch': 'Mumbai Main',  # Same branch
                'branch_contact': '+91-22-12345678',  # Same branch contact
                'employee_name': 'Amit Sharma',  # Same employee
                'employee_id': 'EMP001',  # Same employee ID
                'employee_contact': '+91-9123456789',  # Same employee contact
                'last_paid_date': '2025-08-15',  # Same last paid date
                'last_paid_amount': 25000,  # Same last paid amount
                'due_amount': 225000  # Same due amount
            }]),
            'upload_date': yesterday_str,  # Only difference is upload date
            'call_status': 'ready'
        },
        {
            'full_name': 'Priya Singh',  # Same name as today's entry
            'primary_phone': '+91-9876543211',  # Same phone as today's entry
            'loans': json.dumps([{
                'loan_id': 'LN002',  # Same loan ID
                'amount': 150000,  # Same amount
                'due_date': '2025-09-20',  # Same due date
                'state': 'Delhi',  # Same state
                'cluster': 'Delhi North',  # Same cluster
                'branch': 'Delhi Branch',  # Same branch
                'branch_contact': '+91-11-12345678',  # Same branch contact
                'employee_name': 'Sunita Verma',  # Same employee
                'employee_id': 'EMP002',  # Same employee ID
                'employee_contact': '+91-9123456790',  # Same employee contact
                'last_paid_date': '2025-08-10',  # Same last paid date
                'last_paid_amount': 15000,  # Same last paid amount
                'due_amount': 135000  # Same due amount
            }]),
            'upload_date': yesterday_str,  # Only difference is upload date
            'call_status': 'ready'
        }
    ]
    
    # Clear existing test data (remove all entries for these test customers)
    cursor.execute("DELETE FROM customers WHERE full_name IN (?, ?)", 
                   ('Rajesh Kumar', 'Priya Singh'))
    
    print(f"🗑️ Cleared existing test data")
    
    # Insert today's entries
    for customer in today_customers:
        cursor.execute('''
            INSERT INTO customers (full_name, primary_phone, loans, upload_date, call_status)
            VALUES (?, ?, ?, ?, ?)
        ''', (customer['full_name'], customer['primary_phone'], customer['loans'], 
              customer['upload_date'], customer['call_status']))
        print(f"✅ Added TODAY entry: {customer['full_name']} (uploaded today)")
    
    # Insert yesterday's entries (same customers, same details, different upload date)
    for customer in yesterday_customers:
        cursor.execute('''
            INSERT INTO customers (full_name, primary_phone, loans, upload_date, call_status)
            VALUES (?, ?, ?, ?, ?)
        ''', (customer['full_name'], customer['primary_phone'], customer['loans'], 
              customer['upload_date'], customer['call_status']))
        print(f"✅ Added YESTERDAY entry: {customer['full_name']} (uploaded yesterday)")
    
    # Commit changes
    conn.commit()
    
    # Verify entries
    cursor.execute("SELECT full_name, upload_date FROM customers WHERE full_name IN (?, ?) ORDER BY full_name, upload_date", 
                   ('Rajesh Kumar', 'Priya Singh'))
    results = cursor.fetchall()
    
    print(f"\n📊 Verification - Found {len(results)} test entries (duplicates with different upload dates):")
    for name, upload_date in results:
        # Parse date and determine if today or yesterday
        upload_dt = datetime.strptime(upload_date, '%Y-%m-%d %H:%M:%S')
        upload_dt_ist = ist.localize(upload_dt) if upload_dt.tzinfo is None else upload_dt
        
        if upload_dt_ist.date() == today.date():
            date_label = "TODAY"
        elif upload_dt_ist.date() == yesterday.date():
            date_label = "YESTERDAY"
        else:
            date_label = "OTHER"
            
        print(f"  - {name}: {upload_date} ({date_label})")
    
    conn.close()
    print(f"\n🎉 Duplicate test data created successfully!")
    print(f"📝 You can now test the date filters and duplicate handling:")
    print(f"   - Filter by 'Today' should show: Rajesh Kumar, Priya Singh (today's uploads)")
    print(f"   - Filter by 'Yesterday' should show: Rajesh Kumar, Priya Singh (yesterday's uploads)")
    print(f"   - All customers filter should show: 4 entries total (2 duplicates each)")
    print(f"   - Test how the system handles duplicate customers with different upload dates")

if __name__ == "__main__":
    create_test_entries()
