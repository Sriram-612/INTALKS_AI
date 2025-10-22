#!/usr/bin/env python3
"""
Simple test to verify date-based customer upload tracking feature
This test demonstrates the key functionality requested by the user
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.append(os.path.dirname(__file__))

from services.call_management import CallManagementService
from database.schemas import Customer, db_manager
from utils.logger import logger

async def test_date_based_upload():
    """Test that uploading same customer on different dates creates separate entries"""
    
    logger.info("🧪 Starting date-based customer upload test")
    
    # Initialize service
    call_service = CallManagementService()
    
    # Create test CSV data with same customer
    test_customer_csv = """name,phone_number,state,loan_id,amount,due_date
John Doe,+919876543210,Maharashtra,LOAN001,50000,2024-03-15"""
    
    logger.info("📋 Test CSV data created with customer: John Doe (+919876543210)")
    
    try:
        # First upload
        logger.info("🔄 Performing FIRST upload...")
        result1 = await call_service.upload_and_process_customers(
            file_data=test_customer_csv.encode('utf-8'),
            filename='test_customers_day1.csv'
        )
        
        logger.info(f"✅ First upload result: {result1['success']}")
        logger.info(f"   - Processed: {result1['processing_results']['processed_records']}")
        logger.info(f"   - Upload date: {result1['processing_results']['upload_date']}")
        
        # Simulate time passing (different date)
        logger.info("⏰ Simulating different upload date...")
        
        # Wait a moment to ensure different created_at timestamp
        await asyncio.sleep(2)
        
        # Second upload (same customer, different date simulation)
        logger.info("🔄 Performing SECOND upload (same customer)...")
        result2 = await call_service.upload_and_process_customers(
            file_data=test_customer_csv.encode('utf-8'),
            filename='test_customers_day2.csv'
        )
        
        logger.info(f"✅ Second upload result: {result2['success']}")
        logger.info(f"   - Processed: {result2['processing_results']['processed_records']}")
        logger.info(f"   - Upload date: {result2['processing_results']['upload_date']}")
        
        # Check database for multiple entries
        session = db_manager.get_session()
        try:
            customers = session.query(Customer).filter(
                Customer.phone_number == '+919876543210'
            ).all()
            
            logger.info(f"📊 Database check: Found {len(customers)} entries for phone +919876543210")
            
            for i, customer in enumerate(customers, 1):
                logger.info(f"   Entry {i}:")
                logger.info(f"     - ID: {customer.id}")
                logger.info(f"     - Name: {customer.name}")
                logger.info(f"     - Created: {customer.created_at}")
                logger.info(f"     - Updated: {customer.updated_at}")
                if hasattr(customer, 'first_uploaded_at') and customer.first_uploaded_at:
                    logger.info(f"     - First Upload: {customer.first_uploaded_at}")
            
            # Verify we have multiple entries (key requirement)
            if len(customers) >= 2:
                logger.info("🎉 SUCCESS: Multiple customer entries created for different upload dates!")
                logger.info("✅ Feature working correctly: Can filter by upload date for historical tracking")
                return True
            else:
                logger.error("❌ FAILURE: Expected multiple entries, but found only one")
                logger.error("   This means duplicate prevention is still active")
                return False
                
        finally:
            db_manager.close_session(session)
            
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}", exc_info=True)
        return False

async def cleanup_test_data():
    """Clean up test data"""
    logger.info("🧹 Cleaning up test data...")
    session = db_manager.get_session()
    try:
        # Delete test customers
        deleted = session.query(Customer).filter(
            Customer.phone_number == '+919876543210'
        ).delete()
        session.commit()
        logger.info(f"🗑️ Deleted {deleted} test customer records")
    finally:
        db_manager.close_session(session)

if __name__ == "__main__":
    async def main():
        success = await test_date_based_upload()
        await cleanup_test_data()
        
        if success:
            logger.info("🎉 TEST PASSED: Date-based customer upload tracking is working!")
        else:
            logger.error("❌ TEST FAILED: Date-based customer upload tracking needs fixing")
        
        return success
    
    # Run the test
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
