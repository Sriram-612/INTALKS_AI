#!/usr/bin/env python3

"""Create test customer Kushal"""

from database.schemas import engine
from sqlalchemy import text

def create_test_customer():
    """Create test customer Kushal with phone +917417119014"""
    
    with engine.connect() as connection:
        trans = connection.begin()
        
        try:
            # Check if customer already exists
            result = connection.execute(text("""
                SELECT id, full_name FROM customers WHERE primary_phone = '+917417119014'
                LIMIT 1
            """))
            
            existing = result.fetchone()
            if existing:
                print(f"✅ Customer 'Kushal' already exists:")
                print(f"   ID: {existing[0]}")
                print(f"   Name: {existing[1]}")
                print(f"   Phone: +917417119014")
                return str(existing[0])
            
            # Create new customer
            print("📝 Creating test customer 'Kushal'...")
            result = connection.execute(text("""
                INSERT INTO customers (
                    full_name, 
                    primary_phone, 
                    fingerprint, 
                    state, 
                    loan_id, 
                    amount, 
                    due_date, 
                    language_code,
                    created_at,
                    updated_at
                )
                VALUES (
                    'Kushal', 
                    '+917417119014', 
                    '+917417119014', 
                    'active', 
                    gen_random_uuid(), 
                    50000.00, 
                    CURRENT_DATE + INTERVAL '30 days', 
                    'en',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                RETURNING id, full_name
            """))
            
            new_customer = result.fetchone()
            trans.commit()
            
            print(f"✅ Customer 'Kushal' created successfully!")
            print(f"   ID: {new_customer[0]}")
            print(f"   Name: {new_customer[1]}")
            print(f"   Phone: +917417119014")
            print(f"   State: active")
            print(f"   Amount: ₹50,000")
            
            return str(new_customer[0])
            
        except Exception as e:
            trans.rollback()
            print(f"❌ Error creating customer: {e}")
            return None

if __name__ == "__main__":
    print("🚀 Creating Test Customer")
    print("=" * 30)
    customer_id = create_test_customer()
    if customer_id:
        print("\n🎉 Test customer ready for use!")
    else:
        print("\n❌ Failed to create test customer")
