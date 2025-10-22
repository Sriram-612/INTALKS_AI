#!/usr/bin/env python3
"""
Test Column Mapping Debug
Check how the CSV column names are being normalized and mapped
"""

# Your CSV columns
csv_columns = ['Name', 'Phone', 'Loan ID', 'Amount', 'Due Date', 'State', 'Cluster', 'Branch', 'Branch Contact', 'Employee', 'Employee ID', 'Employee Contact', 'Last Paid Date', 'Last Paid Amount', 'Due Amount']

def normalize_column_name(col_name):
    """Normalize column names by removing spaces and converting to lowercase"""
    return str(col_name).lower().replace(' ', '_').replace('-', '_')

# Create mapping from normalized names to actual column names
actual_columns = {}
for col in csv_columns:
    normalized = normalize_column_name(col)
    actual_columns[normalized] = col

print("CSV Columns:")
for col in csv_columns:
    print(f"  '{col}'")

print("\nNormalized mapping:")
for normalized, actual in actual_columns.items():
    print(f"  '{normalized}' → '{actual}'")

# Expected columns mapping (normalized -> internal field name)
column_mapping = {
    'name': 'name',
    'customer_name': 'name',
    'full_name': 'name',
    'phone': 'phone_number',
    'phone_number': 'phone_number',
    'mobile': 'phone_number',
    'contact': 'phone_number',
    'state': 'state',
    'loan_id': 'loan_id',
    'loan_ID': 'loan_id',
    'loanid': 'loan_id',
    'amount': 'amount',
    'loan_amount': 'amount',
    'outstanding_amount': 'amount',
    'due_amount': 'due_amount',
    'due_date': 'due_date',
    'due_DATE': 'due_date',
    'next_due_date': 'due_date',
    'cluster': 'cluster',
    'branch': 'branch',
    'branch_contact': 'branch_contact',
    'branch_contact_number': 'branch_contact',
    'employee_name': 'employee_name',
    'employee': 'employee_name',
    'emp_name': 'employee_name',
    'employee_id': 'employee_id',
    'emp_id': 'employee_id',
    'employee_contact': 'employee_contact',
    'employee_contact_number': 'employee_contact',
    'emp_contact': 'employee_contact',
    'last_paid_amount': 'last_paid_amount',
    'last_payment': 'last_paid_amount',
    'last_paid_date': 'last_paid_date',
    'last_payment_date': 'last_paid_date'
}

print("\nColumn mapping results:")
for normalized_col, internal_field in column_mapping.items():
    if normalized_col in actual_columns:
        actual_col = actual_columns[normalized_col]
        print(f"  ✅ '{normalized_col}' → '{actual_col}' → {internal_field}")
    else:
        print(f"  ❌ '{normalized_col}' → NOT FOUND → {internal_field}")

print("\nMissing mappings from your CSV:")
for normalized, actual in actual_columns.items():
    if normalized not in column_mapping:
        print(f"  ⚠️  '{normalized}' ('{actual}') → NO MAPPING")
