#!/usr/bin/env python3
"""
Debug CSV Upload Processing
Test the CSV upload functionality with your data structure
"""

#!/usr/bin/env python3
"""
Debug CSV Upload Processing
Test the CSV upload functionality with your data structure
"""

import pandas as pd
import io
from services.call_management import call_service

# Create test CSV data based on your structure
csv_content = """Name,Phone,Loan ID,Amount,Due Date,State,Cluster,Branch,Branch Contact,Employee,Employee ID,Employee Contact,Last Paid Date,Last Paid Amount,Due Amount
Test Customer,9876543210,TEST001,50000,2025-10-15,Maharashtra,Cluster A,Mumbai Branch,+912233445566,John Doe,EMP001,+919876543211,2025-09-01,10000,40000
"""


async def test_csv_processing():
    """Test CSV processing with sample data"""
    print("🧪 Testing CSV Processing")
    print("=" * 50)
    
    try:
        # Convert to bytes like file upload
        file_data = csv_content.encode('utf-8')
        
        # Process the CSV
        result = await call_service.upload_and_process_customers(
            file_data=file_data,
            filename="test_upload.csv"
        )
        
        print("✅ CSV Processing Result:")
        print(f"   Success: {result.get('success', False)}")
        processing = result.get('processing_results', {})
        print(f"   Total: {processing.get('total_records', 0)}")
        print(f"   Processed: {processing.get('processed_records', 0)}")
        print(f"   Failed: {processing.get('failed_records', 0)}")
        
        if result.get('customers'):
            customer = result['customers'][0]
            print("\n📋 Sample Customer Data:")
            for key, value in customer.items():
                print(f"   {key}: {value}")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_csv_processing())
