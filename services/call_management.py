"""
Call Management Service
Handles the complete call lifecycle with database and Redis integration
"""

import uuid
import json
import asyncio
import asyncpg
from datetime import datetime
from typing import Dict, Any, Optional, List
import httpx
import os
from urllib.parse import urlencode
from dotenv import load_dotenv

from database.schemas import (
    DatabaseManager, Customer, CallSession,
    CallStatus, get_customer_by_phone, create_customer, create_call_session,
    update_call_status, get_call_session_by_sid, db_manager,
    update_customer_call_status
)
from utils.redis_session import redis_manager
from utils.handler_asr import SarvamHandler

load_dotenv()

class CallManagementService:
    def __init__(self):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.sarvam_handler = SarvamHandler(os.getenv("SARVAM_API_KEY"))
        self.db_url = os.getenv("DATABASE_URL")
        self.pool: asyncpg.pool.Pool = None
        
        # Exotel configuration
        self.exotel_sid = os.getenv("EXOTEL_SID")
        self.exotel_token = os.getenv("EXOTEL_TOKEN")
        self.exotel_api_key = os.getenv("EXOTEL_API_KEY")
        self.exotel_virtual_number = os.getenv("EXOTEL_VIRTUAL_NUMBER")
        self.exotel_flow_app_id = os.getenv("EXOTEL_FLOW_APP_ID")
        self.agent_phone_number = os.getenv("AGENT_PHONE_NUMBER")
        
    async def upload_and_process_customers(
        self,
        file_data: bytes,
        filename: str,
        websocket_id: str = None,
        uploaded_by: Optional[str] = "dashboard"
    ) -> Dict[str, Any]:
        """
        Process uploaded customer file using the enhanced CSV pipeline.
        Falls back to a simple error structure if the enhanced pipeline fails.
        """
        from services.enhanced_csv_upload_service import enhanced_csv_service

        try:
            result = await enhanced_csv_service.upload_and_process_csv(
                file_data=file_data,
                filename=filename,
                uploaded_by=uploaded_by,
                websocket_id=websocket_id
            )
            return result
        except Exception as exc:
            print(f"❌ [CallService] Enhanced CSV processing failed: {exc}")
            return {
                "success": False,
                "error": str(exc),
                "message": str(exc),
            }
    
    async def trigger_single_call(self, customer_id: str, websocket_id: str = None) -> Dict[str, Any]:
        """Trigger a single outbound call"""
        session = self.db_manager.get_session()
        try:
            # Get customer data
            customer = session.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                return {'success': False, 'error': f"Customer with ID {customer_id} not found"}
            
            print(f"✅ [CHECKPOINT] Found customer: {customer.full_name} ({customer.primary_phone})")
            
            # Update customer call status to 'initiated'
            update_customer_call_status(session, customer_id, CallStatus.INITIATED)

            # Generate temporary call ID (before Exotel assigns SID)
            temp_call_id = f"temp_call_{uuid.uuid4().hex[:12]}"
            
            # Create Redis session with temp_call_id
            # Get the primary loan for this customer
            loan = customer.loans[0] if customer.loans else None
            
            customer_data = {
                'id': str(customer.id),
                'name': customer.full_name,
                'phone_number': customer.primary_phone,
                'state': customer.state,
                'loan_id': loan.loan_id if loan else 'N/A',
                'amount': float(loan.outstanding_amount) if loan and loan.outstanding_amount else 0,
                'due_date': loan.next_due_date.isoformat() if loan and loan.next_due_date else None,
                'language_code': 'en-IN',  # Default language
                'temp_call_id': temp_call_id
            }
            
            # Store by temp_call_id
            self.redis_manager.create_call_session(temp_call_id, customer_data, websocket_id)
            
            # Also store by phone number for easy lookup by WebSocket
            phone_key = f"customer_phone_{customer.primary_phone.replace('+', '').replace('-', '').replace(' ', '')}"
            self.redis_manager.store_temp_data(phone_key, customer_data, ttl=3600)
            print(f"[CallService] Stored customer data in Redis: temp_call_id={temp_call_id}, phone_key={phone_key}")
            
            # Store temp_call_id mapping by phone for reverse lookup
            temp_call_key = f"temp_call_phone_{customer.primary_phone.replace('+', '').replace('-', '').replace(' ', '')}"
            self.redis_manager.store_temp_data(temp_call_key, temp_call_id, ttl=3600)
            
            print(f"📞 [CHECKPOINT] About to trigger Exotel call for temp_call_id: {temp_call_id}")
            # Trigger Exotel call with customer data
            exotel_response = await self._trigger_exotel_call(customer.primary_phone, temp_call_id, customer_data)
            
            if exotel_response['success']:
                print(f"✅ [CHECKPOINT] Exotel call triggered successfully for temp_call_id: {temp_call_id}")
                call_sid = exotel_response.get('call_sid')
                
                # Handle case where call is successful but no call_sid is returned
                if call_sid:
                    print(f"✅ [CHECKPOINT] CallSid received: {call_sid}")
                else:
                    print(f"⚠️ [WARNING] Call triggered successfully but no CallSid returned")
                    call_sid = f"temp_{temp_call_id}"  # Use temp ID as fallback
                
                # Create call session in database
                try:
                    call_data = {
                        'call_sid': call_sid,
                        'customer_id': customer.id,
                        'to_number': customer.primary_phone,
                        'status': 'initiated',
                        'metadata': {'temp_call_id': temp_call_id}
                    }
                    call_session = create_call_session(session, call_data)
                    session.commit()
                    print(f"✅ [CHECKPOINT] Call session created in database")
                except Exception as db_error:
                    print(f"⚠️ [WARNING] Failed to create call session in DB: {db_error}")
                    # Continue anyway, don't fail the entire call
                
                return {
                    'success': True,
                    'message': f'Call triggered successfully for {customer.full_name}',
                    'call_sid': exotel_response.get('call_sid'),  # Return actual call_sid or None
                    'temp_call_id': temp_call_id,
                    'customer_name': customer.full_name,
                    'phone_number': customer.primary_phone,
                    'warning': exotel_response.get('warning')  # Include any warnings
                }
            else:
                print(f"❌ [CHECKPOINT] Failed to trigger Exotel call for temp_call_id: {temp_call_id}. Error: {exotel_response.get('error')}")
                return {
                    'success': False,
                    'error': f"Failed to trigger call: {exotel_response.get('error')}",
                    'temp_call_id': temp_call_id
                }
                
        except Exception as e:
            print(f"❌ [CHECKPOINT] Exception in trigger_single_call: {e}")
            import traceback
            print(f"🔍 [DEBUG] Full traceback: {traceback.format_exc()}")
            return {
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
        finally:
            self.db_manager.close_session(session)

    async def init_db_pool(self):
        """Initialize asyncpg connection pool"""
        if self.pool is None:
            self.pool = await asyncpg.create_pool(self.db_url, min_size=1, max_size=5)

    async def fetch_call_statuses(self, ids: List[str]) -> Dict[str, str]:
        """Fetch call_status for given customer ids from Postgres using pool"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, call_status FROM customers WHERE id = ANY($1)",
                ids
            )
            return {str(row["id"]): row["call_status"] for row in rows}

    
    async def trigger_bulk_calls(self, customer_ids: List[str], websocket_id: str = None) -> Dict[str, Any]:
        """Trigger calls in batches of 2 with DB status checks before next batch"""
        await self.init_db_pool()  # ✅ ensure pool is ready

        BATCH_SIZE = 2
        BATCH_DELAY = 40  # Wait 30 seconds after DB confirms statuses

        results = []
        successful_calls = 0
        failed_calls = 0

        print(f"🚀 Starting bulk calls for {len(customer_ids)} customers in batches of {BATCH_SIZE}")

        # Process customers in batches
        for i in range(0, len(customer_ids), BATCH_SIZE):
            batch_ids = customer_ids[i:i + BATCH_SIZE]
            batch_number = (i // BATCH_SIZE) + 1

            print(f"📦 Processing batch {batch_number}: {batch_ids}")

            # Start all calls in current batch simultaneously
            batch_tasks = [
                asyncio.create_task(self.trigger_single_call(customer_id, websocket_id))
                for customer_id in batch_ids
            ]

            # Wait for all calls in batch to complete
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            # Process results
            for j, result in enumerate(batch_results):
                customer_id = batch_ids[j]

                if isinstance(result, Exception):
                    results.append({
                        'id': customer_id,   # ✅ using "id" instead of customer_id
                        'success': False,
                        'error': str(result)
                    })
                    failed_calls += 1
                else:
                    results.append(result)
                    if result.get('success'):
                        successful_calls += 1
                    else:
                        failed_calls += 1

        # Before moving to next batch: check DB call_status for this batch
            if i + BATCH_SIZE < len(customer_ids):
                print(f"🔍 Waiting for DB statuses for batch {batch_number}...")

                while True:
                    statuses = await self.fetch_call_statuses(batch_ids)
                    print(f"📊 Current statuses for batch {batch_number}: {statuses}")

                    # Continue only if ALL calls in batch are call_failed or ringing
                    if all(status == "call_failed" for status in statuses.values()):
                        print(f"❌ All calls in batch {batch_number} failed. Moving immediately to next batch...")
                        break
                    elif any(status == "ringing" for status in statuses.values()):
                        print(f"⏳ Some calls in batch {batch_number} are still active/ringing. Waiting {BATCH_DELAY}s before next batch...")
                        await asyncio.sleep(BATCH_DELAY)
                        break
                    # Poll every 5 seconds
                    await asyncio.sleep(1)

        # Send final notification
        if websocket_id:
            self.redis_manager.notify_websocket(websocket_id, {
                'type': 'bulk_calls_completed',
                'total_calls': len(customer_ids),
                'successful_calls': successful_calls,
                'failed_calls': failed_calls,
                'results': results
            })

        print(f"🎉 Bulk calls completed: {successful_calls} successful, {failed_calls} failed")

        return {
            'success': True,
            'total_calls': len(customer_ids),
            'successful_calls': successful_calls,
            'failed_calls': failed_calls,
            'results': results
        }

    
    async def handle_exotel_webhook(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Exotel webhook updates"""
        call_sid = webhook_data.get('CallSid')
        call_status = webhook_data.get('CallStatus', '').lower()
        
        if not call_sid:
            return {'success': False, 'error': 'No CallSid in webhook data'}
        
        session = self.db_manager.get_session()
        try:
            # Map Exotel status to our status
            status_mapping = {
                'ringing': CallStatus.RINGING,
                'in-progress': CallStatus.IN_PROGRESS,
                'completed': CallStatus.COMPLETED,
                'failed': CallStatus.FAILED,
                'busy': CallStatus.BUSY,
                'no-answer': CallStatus.NO_ANSWER,
                'canceled': CallStatus.DISCONNECTED
            }
            
            mapped_status = status_mapping.get(call_status, call_status)
            
            # Update Redis
            self.redis_manager.update_call_status(call_sid, mapped_status, 
                                                f"Exotel webhook: {call_status}", webhook_data)
            
            # Update Database
            update_call_status(session, call_sid, mapped_status, 
                             f"Exotel webhook: {call_status}", webhook_data)
            
            # If call ended, update end time and duration
            if mapped_status in [CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.DISCONNECTED, CallStatus.NO_ANSWER]:
                call_session = get_call_session_by_sid(session, call_sid)
                if call_session:
                    call_session.end_time = datetime.utcnow()
                    if webhook_data.get('CallDuration'):
                        call_session.duration = int(webhook_data['CallDuration'])
                    session.commit()
            
            return {'success': True, 'status': mapped_status}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            self.db_manager.close_session(session)
    
    async def transfer_to_agent(self, call_sid: str) -> Dict[str, Any]:
        """Transfer call to human agent"""
        session = self.db_manager.get_session()
        try:
            # Update status
            self.redis_manager.update_call_status(call_sid, CallStatus.AGENT_TRANSFER, "Transferring to agent")
            update_call_status(session, call_sid, CallStatus.AGENT_TRANSFER, "Transferring to agent")
            
            # Get call session data
            redis_call_data = self.redis_manager.get_call_session(call_sid)
            if not redis_call_data:
                return {'success': False, 'error': 'Call session not found'}
            
            customer_data = redis_call_data['customer_data']
            
            # Trigger agent call using existing function
            agent_response = await self._trigger_agent_transfer(customer_data['phone_number'], self.agent_phone_number)
            
            if agent_response['success']:
                # Update database with agent transfer details
                db_call_session = get_call_session_by_sid(session, call_sid)
                if db_call_session:
                    db_call_session.agent_transfer_time = datetime.utcnow()
                    db_call_session.agent_number = self.agent_phone_number
                    session.commit()
                
                return {'success': True, 'message': 'Call transferred to agent successfully'}
            else:
                # Update status to failed transfer
                self.redis_manager.update_call_status(call_sid, CallStatus.FAILED, f"Agent transfer failed: {agent_response['error']}")
                update_call_status(session, call_sid, CallStatus.FAILED, f"Agent transfer failed: {agent_response['error']}")
                
                return {'success': False, 'error': agent_response['error']}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            self.db_manager.close_session(session)
    
    def get_call_status_dashboard(self, websocket_id: str = None) -> Dict[str, Any]:
        """Get dashboard data for call status monitoring"""
        session = self.db_manager.get_session()
        try:
            # Get active calls from Redis
            active_calls = []
            if websocket_id:
                active_calls = self.redis_manager.get_calls_for_websocket(websocket_id)
            
            # Get recent calls from database
            recent_calls = session.query(CallSession).order_by(CallSession.created_at.desc()).limit(20).all()
            
            # Get statistics
            total_calls = session.query(CallSession).count()
            completed_calls = session.query(CallSession).filter(CallStatus.COMPLETED).count()
            failed_calls = session.query(CallSession).filter(CallStatus.FAILED).count()
            in_progress_calls = session.query(CallSession).filter(CallSession.status.in_([CallStatus.IN_PROGRESS, CallStatus.RINGING])).count()
            
            return {
                'active_calls': active_calls,
                'recent_calls': [
                    {
                        'call_sid': call.call_sid,
                        'customer_name': call.customer.full_name if call.customer else 'Unknown',
                        'phone_number': call.customer.primary_phone if call.customer else 'Unknown',
                        'status': call.status,
                        'start_time': call.start_time.isoformat() if call.start_time else None,
                        'duration': call.duration
                    }
                    for call in recent_calls
                ],
                'statistics': {
                    'total_calls': total_calls,
                    'completed_calls': completed_calls,
                    'failed_calls': failed_calls,
                    'in_progress_calls': in_progress_calls
                }
            }
            
        except Exception as e:
            return {'error': str(e)}
        finally:
            self.db_manager.close_session(session)
    
    async def _trigger_call_from_data(self, customer_data: Dict[str, Any], websocket_id: str = None) -> Dict[str, Any]:
        """Trigger call from raw customer data and create database records"""
        session = self.db_manager.get_session()
        try:
            # Extract required fields
            phone_number = customer_data.get('phone', customer_data.get('phone_number', ''))
            name = customer_data.get('name', 'Unknown')
            
            if not phone_number:
                return {'success': False, 'error': 'Phone number is required', 'customer_data': customer_data}
            
            # Generate temporary call ID
            temp_call_id = f"temp_call_{uuid.uuid4().hex[:12]}"
            
            # First, check if customer exists in database, if not create one
            customer = get_customer_by_phone(session, phone_number)
            if not customer:
                # Create new customer record
                customer_dict = {
                    'name': name,
                    'phone_number': phone_number,
                    'loan_id': customer_data.get('loan_id', ''),
                    'amount': customer_data.get('amount', ''),
                    'due_date': customer_data.get('due_date', ''),
                    'state': customer_data.get('state', ''),
                    'language_code': customer_data.get('language_code', 'en-IN')
                }
                customer = create_customer(session, customer_dict)
            
            # Create Redis session for this call
            self.redis_manager.create_call_session(temp_call_id, customer_data, websocket_id)
            
            # Also store by phone number for easy lookup by WebSocket
            clean_phone = phone_number.replace('+', '').replace('-', '').replace(' ', '')
            phone_key = f"customer_phone_{clean_phone}"
            self.redis_manager.store_temp_data(phone_key, customer_data, ttl=3600)
            
            # Store temp_call_id mapping by phone for reverse lookup
            temp_call_key = f"temp_call_phone_{clean_phone}"
            self.redis_manager.store_temp_data(temp_call_key, temp_call_id, ttl=3600)
            
            print(f"[CallService] Stored customer data for call: temp_call_id={temp_call_id}, phone_key={phone_key}, name={name}")
            
            # Trigger Exotel call with customer data
            exotel_response = await self._trigger_exotel_call(phone_number, temp_call_id, customer_data)
            
            if exotel_response.get('success'):
                call_sid = exotel_response.get('call_sid')
                
                if call_sid:
                    print(f"✅ [CHECKPOINT] Exotel call triggered successfully. CallSid: {call_sid}")
                else:
                    print(f"⚠️ [WARNING] Call triggered successfully but no CallSid returned")
                    call_sid = f"temp_{temp_call_id}"  # Use temp ID as fallback
                
                # Create call session in database
                try:
                    call_data = {
                        'call_sid': call_sid,
                        'customer_id': customer.id,
                        'to_number': phone_number,
                        'status': 'initiated',
                        'metadata': {'temp_call_id': temp_call_id}
                    }
                    call_session = create_call_session(session, call_data)
                    session.commit()
                    print(f"✅ [CHECKPOINT] Call session created in database")
                except Exception as db_error:
                    print(f"⚠️ [WARNING] Failed to create call session in DB: {db_error}")
                    # Continue anyway, don't fail the entire call
                
                return {
                    'success': True,
                    'message': f'Call triggered successfully for {name}',
                    'call_sid': exotel_response.get('call_sid'),  # Return actual call_sid or None
                    'temp_call_id': temp_call_id,
                    'customer_name': name,
                    'phone_number': phone_number,
                    'warning': exotel_response.get('warning')  # Include any warnings
                }
            else:
                error_msg = exotel_response.get('error', 'Unknown error')
                print(f"❌ [CHECKPOINT] Failed to trigger Exotel call. Error: {error_msg}")
                return {
                    'success': False,
                    'error': f"Failed to trigger call: {error_msg}",
                    'temp_call_id': temp_call_id
                }
                
        except Exception as e:
            return {'success': False, 'error': str(e), 'customer_data': customer_data}
        finally:
            self.db_manager.close_session(session)
    
    
    async def _trigger_exotel_call(self, to_number: str, temp_call_id: str, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Internal method to trigger Exotel call and connect it to the ExoML flow."""
        print(f"🎯 [CHECKPOINT] Starting Exotel call trigger process")
        print(f"🎯 [CHECKPOINT] Target number: {to_number}")
        print(f"🎯 [CHECKPOINT] Temp call ID: {temp_call_id}")
        
        # The base URL for API calls
        url = f"https://api.exotel.com/v1/Accounts/{self.exotel_sid}/Calls/connect.json"
        
        # The URL for the ExoML flow that Exotel will execute when the call connects.
        # This is NOT our server's URL, but Exotel's URL for our specific application flow.
        flow_url = f"http://my.exotel.com/{self.exotel_sid}/exoml/start_voice/{self.exotel_flow_app_id}"

        print(f"🎯 [CHECKPOINT] API URL: {url}")
        print(f"🎯 [CHECKPOINT] Flow URL: {flow_url}")

        # Add temp_call_id to customer data for tracking
        customer_data['temp_call_id'] = temp_call_id

        # We pass all customer data in the 'CustomField'. 
        # The Passthru applet within the ExoML flow will send this data back to our /passthru-handler.
        custom_field_data = {k: str(v) for k, v in customer_data.items()}
        custom_field_str = "|".join([f"{key}={value}" for key, value in custom_field_data.items()])

        # CRITICAL FIX: According to Exotel API docs for flow calls:
        # - From: Customer number (who gets called first)
        # - CallerId: Your ExoPhone number  
        # - Url: Flow URL
        # The previous payload was wrong - it had From=ExoPhone and To=Customer
        payload = {
            'From': to_number,  # 🔥 FIXED: Customer number gets called first
            'CallerId': self.exotel_virtual_number,  # 🔥 FIXED: ExoPhone as caller ID
            'Url': flow_url,  # Flow URL remains the same
            'CallType': 'trans',
            'TimeLimit': '3600',
            'TimeOut': '30',
            'CustomField': custom_field_str,
           #'StatusCallback': f"{os.getenv('BASE_URL', 'https://3.108.35.213')}/exotel-webhook"
            'StatusCallback': f"{os.getenv('BASE_URL', 'https://9a81252242ca.ngrok-free.app')}/passthru-handler"#for Active Status from passthrough
        }
        
        print(f"🎯 [CHECKPOINT] Payload validation:")
        print(f"   • From (Customer): {payload['From']}")
        print(f"   • CallerId (ExoPhone): {payload['CallerId']}")
        print(f"   • Flow URL: {payload['Url']}")
        print(f"   • CustomField: {custom_field_str[:100]}...")
        
        print(f"📞 [CHECKPOINT] Triggering Exotel call to customer {to_number}")
        print(f"📦 [CHECKPOINT] CustomField Payload: {custom_field_str}")
        print(f"🔧 [CHECKPOINT] Debug - API URL: {url}")
        print(f"🔧 [CHECKPOINT] Debug - Auth: {self.exotel_api_key[:10]}...{self.exotel_api_key[-10:]} / {self.exotel_token[:10]}...{self.exotel_token[-10:]}")
        print(f"🔧 [CHECKPOINT] Debug - Full Payload: {json.dumps(payload, indent=2)}")

        # Add retry logic for better reliability
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                print(f"🎯 [CHECKPOINT] Making HTTP request to Exotel API (attempt {attempt + 1}/{max_retries})...")
                
                # Add proper timeout and retry logic
                timeout = httpx.Timeout(30.0, connect=10.0)
                async with httpx.AsyncClient(
                    auth=(self.exotel_api_key, self.exotel_token),
                    timeout=timeout
                ) as client:
                    response = await client.post(url, data=payload)
                
                print(f"🎯 [CHECKPOINT] Exotel API response received")
                print(f"🎯 [CHECKPOINT] Status Code: {response.status_code}")
                print(f"🎯 [CHECKPOINT] Response Text: {response.text[:500]}...")
                
                if response.status_code == 200:
                    try:
                        response_data = response.json()
                        print(f"🔍 [DEBUG] Full Exotel Response Structure: {json.dumps(response_data, indent=2)}")
                        
                        # Enhanced call_sid extraction with multiple fallbacks
                        call_sid = None
                        if 'Call' in response_data and response_data['Call']:
                            call_sid = response_data['Call'].get('Sid')
                        elif 'Sid' in response_data:
                            call_sid = response_data.get('Sid')
                        elif 'call_sid' in response_data:
                            call_sid = response_data.get('call_sid')
                        
                        if call_sid:
                            print(f"✅ [CHECKPOINT] Exotel call triggered successfully. CallSid: {call_sid}")
                            return {'success': True, 'call_sid': call_sid, 'response': response_data}
                        else:
                            print(f"⚠️ [WARNING] Call triggered but no CallSid found in response")
                            print(f"🔍 [DEBUG] Available keys in response: {list(response_data.keys())}")
                            # Still return success but without call_sid for polling
                            return {'success': True, 'call_sid': None, 'response': response_data, 'warning': 'No CallSid in response'}
                            
                    except json.JSONDecodeError as je:
                        print(f"❌ [ERROR] Failed to parse JSON response: {je}")
                        print(f"🔍 [DEBUG] Raw response: {response.text}")
                        return {'success': False, 'error': f'Invalid JSON response: {je}'}
                        
                elif response.status_code in [429, 500, 502, 503, 504]:  # Retryable errors
                    error_message = f"Exotel API Error (retryable): {response.status_code} - {response.text}"
                    print(f"⚠️ [WARNING] Retryable error on attempt {attempt + 1}: {error_message}")
                    if attempt < max_retries - 1:
                        print(f"🔄 [RETRY] Waiting {retry_delay} seconds before retry...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        return {'success': False, 'error': error_message}
                else:
                    error_message = f"Exotel API Error: {response.status_code} - {response.text}"
                    print(f"❌ [CHECKPOINT] Failed to trigger Exotel call. {error_message}")
                    return {'success': False, 'error': error_message}
                    
            except httpx.TimeoutException as te:
                error_message = f"Timeout error on attempt {attempt + 1}: {te}"
                print(f"⏰ [TIMEOUT] {error_message}")
                if attempt < max_retries - 1:
                    print(f"🔄 [RETRY] Waiting {retry_delay} seconds before retry...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    return {'success': False, 'error': f'Timeout after {max_retries} attempts'}
                    
            except Exception as e:
                error_message = f"Exception on attempt {attempt + 1}: {str(e)}"
                print(f"❌ [EXCEPTION] {error_message}")
                if attempt < max_retries - 1:
                    print(f"🔄 [RETRY] Waiting {retry_delay} seconds before retry...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    return {'success': False, 'error': f'Failed after {max_retries} attempts: {str(e)}'}
        
        # This should never be reached, but just in case
        return {'success': False, 'error': 'Unexpected error: max retries exceeded'}

    async def _trigger_agent_transfer(self, customer_number: str, agent_number: str) -> Dict[str, Any]:
        """Trigger agent transfer call with improved error handling"""
        url = f"https://api.exotel.com/v1/Accounts/{self.exotel_sid}/Calls/connect.json"
        
        payload = {
            "From": customer_number,
            "To": agent_number,
            "CallerId": self.exotel_virtual_number,
        }
        
        try:
            timeout = httpx.Timeout(30.0, connect=10.0)
            async with httpx.AsyncClient(
                auth=(self.exotel_api_key, self.exotel_token),
                timeout=timeout
            ) as client:
                response = await client.post(url, data=payload)
                
                if response.status_code == 200:
                    return {'success': True, 'response': response.json()}
                else:
                    return {'success': False, 'error': f'HTTP {response.status_code}: {response.text}'}
                    
        except httpx.TimeoutException as te:
            return {'success': False, 'error': f'Timeout during agent transfer: {te}'}
        except Exception as e:
            return {'success': False, 'error': f'Agent transfer failed: {str(e)}'}

# Global service instance
call_service = CallManagementService()
