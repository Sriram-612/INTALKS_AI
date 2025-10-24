"""
Call Management Service
Handles the complete call lifecycle with database and Redis integration
"""

import uuid
import json
import asyncio
import asyncpg
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List
import httpx
import io
import os
import pandas as pd
import re
from urllib.parse import urlencode
from dotenv import load_dotenv

from database.schemas import (
    DatabaseManager,
    Customer,
    CallSession,
    CallStatus,
    FileUpload,
    create_customer,
    create_call_session,
    create_loan,
    db_manager,
    get_call_session_by_sid,
    get_customer_by_phone,
    get_loan_by_external_id,
    update_call_status,
    update_customer_call_status,
    compute_fingerprint,
)
from utils.redis_session import redis_manager
from utils.handler_asr import SarvamHandler
from utils.logger import logger
from utils.json_encoder import convert_to_json_serializable

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
        """Process uploaded customer file and store in database with date-based tracking"""
        session = self.db_manager.get_session()
        try:
            logger.info(f"Starting customer file upload: {filename}")

            # Create file upload record using new schema structure
            try:
                file_upload = FileUpload(
                    filename=filename,
                    original_filename=filename,
                    uploaded_by=uploaded_by or 'system',
                    status='processing',
                    total_records=0
                )
                session.add(file_upload)
                session.commit()
                session.refresh(file_upload)
                logger.database.info(f"Created file upload record with ID: {file_upload.id}")
            except Exception as e:
                # If we fail to create a FileUpload record, abort early with clear error
                logger.error(f"Failed to create FileUpload record: {e}", exc_info=True)
                try:
                    session.rollback()
                except Exception:
                    pass
                return {'success': False, 'error': f'failed_to_create_file_upload: {str(e)}'}

            # Parse the file (assuming CSV/Excel)
            try:
                customers_data = await self._parse_customer_file(file_data, filename)
                file_upload.total_records = len(customers_data)
                session.commit()
            except Exception as e:
                logger.error(f"Failed to parse uploaded file {filename}: {e}", exc_info=True)
                # mark upload as failed and persist
                try:
                    file_upload.status = 'failed'
                    file_upload.processing_errors = [{'error': str(e)}]
                    session.commit()
                except Exception:
                    try:
                        session.rollback()
                    except Exception:
                        pass
                return {'success': False, 'error': f'failed_to_parse_file: {str(e)}'}

            logger.info(f"Parsed {len(customers_data)} customer records from {filename}")

            processed_customers = []
            failed_records = 0
            processing_errors = []
            # Store upload date in IST 
            current_upload_date = datetime.now().date()

            for idx, customer_data in enumerate(customers_data):
                try:
                    phone_number = customer_data.get('phone_number')
                    
                    if not phone_number:
                        raise ValueError("Phone number is required")
                    
                    # Always CREATE new customer entry for each upload (allows multiple entries per customer)
                    # This enables tracking the same customer across different upload dates
                    existing_any_date = get_customer_by_phone(session, phone_number)
                    
                    if existing_any_date:
                        logger.info(f"📝 Creating NEW entry for returning customer: {customer_data.get('full_name', 'Unknown')} (Phone: {phone_number})")
                    else:
                        logger.info(f"📝 Creating entry for first-time customer: {customer_data.get('full_name', 'Unknown')} (Phone: {phone_number})")
                    
                    # Always CREATE new record for each upload
                    
                    # Ensure fingerprint is generated properly
                    if not customer_data.get('fingerprint'):
                        customer_data['fingerprint'] = compute_fingerprint(
                            phone_number,
                            customer_data.get('national_id', '')
                        )
                    
                    # Set first upload date in IST
                    customer_data['first_uploaded_at'] = datetime.now()
                    
                    logger.info(f"Processing customer: {customer_data.get('name', 'Unknown')} (Phone: {phone_number})")
                    
                    customer = create_customer(session, customer_data)
                    if not customer:
                        raise Exception("Failed to create customer record")
                    
                    logger.info(f"✅ Customer entry created: {customer.full_name} (Upload Date: {current_upload_date})")
                    
                    loan_record = None
                    
                    # Create loan record if loan data exists
                    if customer_data.get('loan_id') and customer.id:
                        existing_loan = get_loan_by_external_id(session, customer_data['loan_id'])
                        
                        if existing_loan:
                            loan_record = existing_loan
                        else:
                            # Create new loan record
                            loan_data = {
                                'customer_id': customer.id,
                                'loan_id': customer_data['loan_id'],
                                'outstanding_amount': self._parse_amount(customer_data.get('amount', '0')),
                                'due_amount': self._parse_amount(customer_data.get('due_amount', customer_data.get('amount', '0'))),
                                'status': 'active',
                                'cluster': customer_data.get('cluster'),
                                'branch': customer_data.get('branch'),
                                'branch_contact_number': customer_data.get('branch_contact'),
                                'employee_name': customer_data.get('employee_name'),
                                'employee_id': customer_data.get('employee_id'),
                                'employee_contact_number': customer_data.get('employee_contact'),
                                'last_paid_amount': self._parse_amount(customer_data.get('last_paid_amount', '0')),
                            }
                            
                            # Parse due date
                            if customer_data.get('due_date'):
                                try:
                                    # Try multiple date formats
                                    due_date_str = str(customer_data['due_date']).strip()
                                    if due_date_str and due_date_str.lower() != 'nan':
                                        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y']:
                                            try:
                                                loan_data['next_due_date'] = datetime.strptime(due_date_str, fmt).date()
                                                break
                                            except ValueError:
                                                continue
                                except Exception as e:
                                    logger.warning(f"Invalid due date format for loan {customer_data['loan_id']}: {customer_data['due_date']} - {e}")
                            
                            # Parse last paid date
                            if customer_data.get('last_paid_date'):
                                try:
                                    last_paid_str = str(customer_data['last_paid_date']).strip()
                                    if last_paid_str and last_paid_str.lower() != 'nan':
                                        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y']:
                                            try:
                                                loan_data['last_paid_date'] = datetime.strptime(last_paid_str, fmt).date()
                                                break
                                            except ValueError:
                                                continue
                                except Exception as e:
                                    logger.warning(f"Invalid last paid date format for loan {customer_data['loan_id']}: {customer_data['last_paid_date']} - {e}")
                            
                            loan_record = create_loan(session, loan_data)
                            logger.info(f"Created loan: {loan_record.loan_id} for customer {customer.name}")
                    else:
                        # Attempt to reuse first associated loan if it exists
                        loan_record = customer.loans[0] if customer.loans else None
                    
                    # Add processed customer to results
                    primary_loan = loan_record or (customer.loans[0] if customer.loans else None)
                    outstanding_amount = None
                    due_amount = None
                    due_date_str = None
                    
                    if primary_loan:
                        if getattr(primary_loan, "outstanding_amount", None) is not None:
                            outstanding_amount = float(primary_loan.outstanding_amount)
                        if getattr(primary_loan, "due_amount", None) is not None:
                            due_amount = float(primary_loan.due_amount)
                        if getattr(primary_loan, "next_due_date", None):
                            due_date_str = primary_loan.next_due_date.isoformat()
                    
                    processed_customers.append({
                        'id': str(customer.id),
                        'name': customer.name,
                        'phone_number': customer.phone_number,
                        'state': customer.state,
                        'loan_id': primary_loan.loan_id if primary_loan else customer_data.get('loan_id'),
                        'amount': (
                            f"{outstanding_amount:.2f}" if outstanding_amount is not None
                            else customer_data.get('amount')
                        ),
                        'due_date': due_date_str or customer_data.get('due_date'),
                        'due_amount': due_amount if due_amount is not None else customer_data.get('due_amount'),
                        'upload_date': current_upload_date.isoformat(),
                        'language_code': getattr(customer, 'language_code', 'hi-IN')
                    })
                    
                except Exception as e:
                    failed_records += 1
                    processing_errors.append({
                        'row': idx + 1,
                        'customer_data': convert_to_json_serializable(customer_data),
                        'error': str(e)
                    })
                    logger.error(f"Failed to process customer at row {idx + 1}: {e}", exc_info=True)
            # Update file upload record
            try:
                file_upload.processed_records = len(processed_customers)
                file_upload.success_records = len(processed_customers)
                file_upload.failed_records = failed_records
                file_upload.processing_errors = processing_errors or None
                file_upload.status = 'completed' if failed_records == 0 else 'partial_failure'
                session.commit()
            except Exception as e:
                logger.error(f"Failed to update FileUpload record: {e}", exc_info=True)
                try:
                    session.rollback()
                except Exception:
                    pass

            logger.info(f"File processing completed: {len(processed_customers)} successful, {failed_records} failed")

            # Store in Redis for quick access
            try:
                temp_key = f"uploaded_customers_{file_upload.id}"
                self.redis_manager.store_temp_data(temp_key, processed_customers, ttl=3600)
            except Exception as e:
                logger.warning(f"Failed to store upload results in Redis: {e}")

            # Notify WebSocket if connected
            try:
                if websocket_id:
                    self.redis_manager.notify_websocket(websocket_id, {
                        'type': 'file_processed',
                        'upload_id': str(file_upload.id),
                        'total_records': file_upload.total_records,
                        'processed_records': file_upload.processed_records,
                        'failed_records': failed_records,
                        'customers': processed_customers
                    })
            except Exception as e:
                logger.warning(f"Failed to notify websocket about upload: {e}")

            return {
                'success': True,
                'upload_id': str(file_upload.id),
                'processing_results': {
                    'total_records': file_upload.total_records,
                    'processed_records': file_upload.processed_records,
                    'success_records': file_upload.success_records,
                    'failed_records': file_upload.failed_records,
                    'upload_date': current_upload_date.isoformat()
                },
                'customers': processed_customers,
                'temp_key': temp_key
            }
        except Exception as e:
            logger.error(f"Unexpected error processing customer file upload: {e}", exc_info=True)
            try:
                if 'file_upload' in locals():
                    file_upload.status = 'failed'
                    file_upload.processing_errors = [{'error': str(e)}]
                    session.commit()
            except Exception:
                try:
                    session.rollback()
                except Exception:
                    pass

            return {
                'success': False,
                'error': str(e)
            }
        finally:
            self.db_manager.close_session(session)
    
    async def trigger_single_call(self, customer_id: str, websocket_id: str = None) -> Dict[str, Any]:
        """Trigger a single outbound call"""
        session = self.db_manager.get_session()
        try:
            logger.info(f"Triggering single call for customer ID: {customer_id}")
            
            # Get customer data
            customer = session.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                logger.error(f"Customer with ID {customer_id} not found")
                return {'success': False, 'error': f"Customer with ID {customer_id} not found"}
            
            logger.info(f"✅ [CHECKPOINT] Found customer: {customer.full_name} ({customer.primary_phone})")
            
            # Update customer call status to 'initiated'
            update_customer_call_status(session, customer_id, CallStatus.INITIATED, call_attempt=True)

            # Generate temporary call ID (before Exotel assigns SID)
            temp_call_id = f"temp_call_{uuid.uuid4().hex[:12]}"
            
            # Get the primary loan for this customer
            loan = customer.loans[0] if customer.loans else None
            
            # Create Redis session with temp_call_id
            customer_name = (customer.full_name or customer.name or customer.primary_phone or "Customer")
            primary_phone = customer.primary_phone or getattr(customer, "phone_number", None) or ""
            state = customer.state or ""

            loan_id = 'N/A'
            amount_value = None
            due_date_value = None
            if loan:
                loan_id = loan.loan_id or loan_id
                if loan.outstanding_amount is not None:
                    amount_value = str(loan.outstanding_amount)
                if loan.due_amount is not None:
                    amount_value = str(loan.due_amount)
                if loan.next_due_date:
                    due_date_value = loan.next_due_date.isoformat()
            else:
                # Fallback to legacy fields if loan relationship missing
                loan_id = getattr(customer, "loan_id", None) or loan_id
                amount_value = getattr(customer, "amount", None) or amount_value
                due_date_value = getattr(customer, "due_date", None) or due_date_value

            customer_data = {
                'id': str(customer.id),
                'name': customer_name,
                'phone': primary_phone,
                'phone_number': primary_phone,
                'state': state,
                'loan_id': loan_id,
                'amount': amount_value if amount_value is not None else "0",
                'due_amount': amount_value if amount_value is not None else "0",
                'due_date': due_date_value,
                'language_code': getattr(customer, "language_code", None) or 'en-IN',
                'temp_call_id': temp_call_id
            }
            
            # Store by temp_call_id
            self.redis_manager.create_call_session(temp_call_id, customer_data, websocket_id)
            
            # Also store by phone number for easy lookup by WebSocket
            phone_key = f"customer_phone_{customer.primary_phone.replace('+', '').replace('-', '').replace(' ', '')}"
            self.redis_manager.store_temp_data(phone_key, customer_data, ttl=3600)
            logger.info(f"[CallService] Stored customer data in Redis: temp_call_id={temp_call_id}, phone_key={phone_key}")
            
            # Store temp_call_id mapping by phone for reverse lookup
            temp_call_key = f"temp_call_phone_{customer.primary_phone.replace('+', '').replace('-', '').replace(' ', '')}"
            self.redis_manager.store_temp_data(temp_call_key, temp_call_id, ttl=3600)
            
            logger.info(f"📞 [CHECKPOINT] About to trigger Exotel call for temp_call_id: {temp_call_id}")
            # Trigger Exotel call with customer data
            exotel_response = await self._trigger_exotel_call(customer.primary_phone, temp_call_id, customer_data)
            
            if exotel_response['success']:
                logger.info(f"✅ [CHECKPOINT] Exotel call triggered successfully for temp_call_id: {temp_call_id}")
                call_sid = exotel_response.get('call_sid')
                
                # Handle case where call is successful but no call_sid is returned
                if call_sid:
                    logger.info(f"✅ [CHECKPOINT] CallSid received: {call_sid}")
                else:
                    logger.warning("⚠️ [WARNING] Call triggered successfully but no CallSid returned")
                    call_sid = f"temp_{temp_call_id}"  # Use temp ID as fallback
                
                # Create call session in database
                try:
                    call_data = {
                        'call_sid': call_sid,
                        'customer_id': customer.id,
                        'to_number': customer.primary_phone,
                        'status': CallStatus.CALLING,
                        'metadata': {'temp_call_id': temp_call_id}
                    }
                    call_session = create_call_session(session, call_data)
                    session.commit()
                    logger.info(f"✅ [CHECKPOINT] Call session created in database")
                except Exception as db_error:
                    logger.warning(f"⚠️ [WARNING] Failed to create call session in DB: {db_error}")
                    # Continue anyway, don't fail the entire call
                
                result = {
                    'success': True,
                    'message': f'Call triggered successfully for {customer.full_name}',
                    'call_sid': call_sid,
                    'temp_call_id': temp_call_id,
                    'customer_name': customer.full_name,
                    'phone_number': customer.primary_phone,
                    'warning': exotel_response.get('warning')  # Include any warnings
                }

                self.redis_manager.update_call_status(
                    call_sid,
                    CallStatus.INITIATED,
                    "Call ringing customer"
                )
                
                return result
            else:
                error_msg = f"❌ [CHECKPOINT] Failed to trigger Exotel call for temp_call_id: {temp_call_id}. Error: {exotel_response.get('error')}"
                logger.error(error_msg)
                update_customer_call_status(session, customer_id, CallStatus.FAILED, call_attempt=True)
                self.redis_manager.update_call_status(temp_call_id, CallStatus.FAILED, "Call failed to start")
                
                return {
                    'success': False,
                    'error': f"Failed to trigger call: {exotel_response.get('error')}",
                    'temp_call_id': temp_call_id
                }
                
        except Exception as e:
            error_msg = f"❌ [CHECKPOINT] Exception in trigger_single_call: {e}"
            logger.error(error_msg, exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
        finally:
            self.db_manager.close_session(session)
    
    async def trigger_bulk_calls(self, customer_ids: List[str], websocket_id: str = None) -> Dict[str, Any]:
        """Trigger multiple calls in parallel"""
        results = []
        
        # Create tasks for parallel execution
        tasks = []
        for customer_id in customer_ids:
            task = asyncio.create_task(self.trigger_single_call(customer_id, websocket_id))
            tasks.append(task)
        
        # Execute all calls in parallel
        call_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful_calls = 0
        failed_calls = 0
        
        for i, result in enumerate(call_results):
            if isinstance(result, Exception):
                results.append({
                    'customer_id': customer_ids[i],
                    'success': False,
                    'error': str(result)
                })
                failed_calls += 1
            else:
                results.append(result)
                if result['success']:
                    successful_calls += 1
                else:
                    failed_calls += 1
        
        # Notify WebSocket
        if websocket_id:
            self.redis_manager.notify_websocket(websocket_id, {
                'type': 'bulk_calls_completed',
                'total_calls': len(customer_ids),
                'successful_calls': successful_calls,
                'failed_calls': failed_calls,
                'results': results
            })
        
        return {
            'success': True,
            'total_calls': len(customer_ids),
            'successful_calls': successful_calls,
            'failed_calls': failed_calls,
            'results': results
        }
    
    async def trigger_bulk_calls_from_data(self, customer_data_list: List[Dict[str, Any]], websocket_id: str = None) -> Dict[str, Any]:
        """Trigger calls from raw customer data (without storing in database first)"""
        results = []
        tasks = []
        
        # Create tasks for parallel execution
        for customer_data in customer_data_list:
            task = asyncio.create_task(self._trigger_call_from_data(customer_data, websocket_id))
            tasks.append(task)
        
        # Execute all calls in parallel
        call_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful_calls = 0
        failed_calls = 0
        
        for i, result in enumerate(call_results):
            if isinstance(result, Exception):
                results.append({
                    'customer_data': customer_data_list[i],
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
        
        # Notify WebSocket
        if websocket_id:
            self.redis_manager.notify_websocket(websocket_id, {
                'type': 'bulk_calls_completed',
                'total_calls': len(customer_data_list),
                'successful_calls': successful_calls,
                'failed_calls': failed_calls,
                'results': results
            })
        
        return {
            'success': True,
            'total_calls': len(customer_data_list),
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
            completed_calls = session.query(CallSession).filter(CallSession.status == CallStatus.COMPLETED).count()
            failed_calls = session.query(CallSession).filter(CallStatus.FAILED).count()
            in_progress_calls = session.query(CallSession).filter(CallSession.status.in_([CallStatus.IN_PROGRESS, CallStatus.RINGING])).count()
            
            return {
                'active_calls': active_calls,
                'recent_calls': [
                    {
                        'call_sid': call.call_sid,
                        'customer_name': call.customer.name if call.customer else 'Unknown',
                        'phone_number': call.customer.phone_number if call.customer else 'Unknown',
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
                    'language_code': customer_data.get('language_code', 'hi-IN')
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
            
            logger.info(f"Stored customer data for call: temp_call_id={temp_call_id}, phone_key={phone_key}, name={name}")
            
            # Trigger Exotel call with customer data
            exotel_response = await self._trigger_exotel_call(phone_number, temp_call_id, customer_data)
            
            if exotel_response.get('success'):
                call_sid = exotel_response['call_sid']
                
                # Create database call session record
                call_session = create_call_session(
                    session=session,
                    call_sid=call_sid,
                    customer_id=str(customer.id),
                    websocket_session_id=websocket_id
                )
                
                # Update Redis session with actual call SID and database ID
                self.redis_manager.update_call_session(temp_call_id, {
                    'call_sid': call_sid,
                    'customer_id': str(customer.id),
                    'call_session_id': str(call_session.id)
                })
                
                # Update status in both Redis and Database
                self.redis_manager.update_call_status(call_sid, CallStatus.RINGING, "Call initiated successfully")
                update_call_status(session, call_sid, CallStatus.RINGING, "Call initiated successfully")
                
                return {
                    'success': True,
                    'call_sid': call_sid,
                    'customer_data': customer_data,
                    'status': CallStatus.RINGING
                }
            else:
                # Update Redis session with failure
                self.redis_manager.update_call_status(temp_call_id, CallStatus.FAILED, f"Failed to initiate call: {exotel_response['error']}")
                
                return {
                    'success': False,
                    'error': exotel_response['error'],
                    'temp_call_id': temp_call_id,
                    'customer_data': customer_data
                }
                
        except Exception as e:
            return {'success': False, 'error': str(e), 'customer_data': customer_data}
        finally:
            self.db_manager.close_session(session)
    
    # Helper methods
    def _parse_amount(self, amount_str: str) -> float:
        """Parse amount string to float, handling various formats"""
        if not amount_str or amount_str in ['', 'nan', 'null', 'None']:
            return 0.0
        
        # Convert to string and clean
        amount_str = str(amount_str).strip()
        
        # Remove currency symbols and commas
        amount_str = amount_str.replace('₹', '').replace(',', '').replace(' ', '')
        
        # Handle date-like formats or other non-numeric strings
        if '/' in amount_str or ':' in amount_str:
            return 0.0
        
        try:
            return float(amount_str)
        except (ValueError, TypeError):
            return 0.0
    
    async def _parse_customer_file(self, file_data: bytes, filename: str) -> List[Dict[str, Any]]:
        """Parse uploaded customer file"""
        # File parsing logic using pandas
        
        try:
            if filename.endswith('.csv'):
                df = pd.read_csv(io.BytesIO(file_data))
            elif filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(io.BytesIO(file_data))
            else:
                raise ValueError("Unsupported file format")
            
            # Print column names for debugging
            logger.info(f"CSV Columns found: {list(df.columns)}")
            
            # Create a case-insensitive column mapping
            def normalize_column_name(col_name):
                """Normalize column names by removing spaces and converting to lowercase"""
                return str(col_name).lower().replace(' ', '_').replace('-', '_')
            
            # Create mapping from normalized names to actual column names
            actual_columns = {}
            for col in df.columns:
                normalized = normalize_column_name(col)
                actual_columns[normalized] = col
            
            logger.info(f"Normalized columns: {actual_columns}")
            
            # Expected columns mapping (normalized -> internal field name)
            column_mapping = {
                'name': 'name',
                'customer_name': 'name',
                'full_name': 'name',
                'phone': 'phone_number',
                'phone_number': 'phone_number',
                'mobile': 'phone_number',
                'mobile_number': 'phone_number',
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
            
            customers = []
            for _, row in df.iterrows():
                customer_data = {}
                
                # Map columns using normalized names
                for normalized_col, internal_field in column_mapping.items():
                    if normalized_col in actual_columns:
                        actual_col = actual_columns[normalized_col]
                        value = row[actual_col]
                        customer_data[internal_field] = str(value) if pd.notna(value) else ''
                
                # Ensure we have required fields
                if not customer_data.get('name'):
                    customer_data['name'] = 'Unknown'
                if not customer_data.get('phone_number'):
                    logger.warning(f"Skipping row with missing phone number: {customer_data}")
                    continue
                
                # Clean phone number (remove spaces, hyphens, parentheses but keep + and digits)
                phone = customer_data['phone_number']
                if phone:
                    # Keep only digits and + sign
                    phone = re.sub(r'[^\d+]', '', phone)
                    if not phone.startswith('+'):
                        # Keep the number as-is from CSV, just add +91 prefix (no leading zero removal)
                        phone = '+91' + phone
                    customer_data['phone_number'] = phone
                
                # Determine language code from state
                state = customer_data.get('state', '').lower()
                if state:
                    # Import state mapping
                    STATE_TO_LANGUAGE = {
                        'andhra pradesh': 'te-IN', 'arunachal pradesh': 'hi-IN', 'assam': 'hi-IN',
                        'bihar': 'hi-IN', 'chhattisgarh': 'hi-IN', 'goa': 'hi-IN', 'gujarat': 'gu-IN',
                        'haryana': 'hi-IN', 'himachal pradesh': 'hi-IN', 'jharkhand': 'hi-IN',
                        'karnataka': 'kn-IN', 'kerala': 'ml-IN', 'madhya pradesh': 'hi-IN',
                        'maharashtra': 'mr-IN', 'manipur': 'hi-IN', 'meghalaya': 'hi-IN',
                        'mizoram': 'hi-IN', 'nagaland': 'hi-IN', 'odisha': 'or-IN', 'punjab': 'pa-IN',
                        'rajasthan': 'hi-IN', 'sikkim': 'hi-IN', 'tamil nadu': 'ta-IN',
                        'telangana': 'te-IN', 'tripura': 'hi-IN', 'uttar pradesh': 'hi-IN',
                        'uttarakhand': 'hi-IN', 'west bengal': 'bn-IN', 'delhi': 'hi-IN',
                        'puducherry': 'ta-IN', 'chandigarh': 'hi-IN'
                    }
                    customer_data['language_code'] = STATE_TO_LANGUAGE.get(state, 'hi-IN')
                else:
                    customer_data['language_code'] = 'hi-IN'
                
                logger.info(f"Parsed customer: {customer_data['name']} - {customer_data['phone_number']}")
                customers.append(customer_data)
            
            return customers
            
        except Exception as e:
            raise Exception(f"Failed to parse file: {str(e)}")
    
    async def _trigger_exotel_call(self, to_number: str, temp_call_id: str, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Internal method to trigger Exotel call and connect it to the ExoML flow."""
        logger.info(f"Starting Exotel call trigger process")
        logger.info(f"Target number: {to_number}")
        logger.info(f"Temp call ID: {temp_call_id}")
        
        # The base URL for API calls
        url = f"https://api.exotel.com/v1/Accounts/{self.exotel_sid}/Calls/connect.json"
        
        # The URL for the ExoML flow that Exotel will execute when the call connects.
        # This is NOT our server's URL, but Exotel's URL for our specific application flow.
        flow_url = f"http://my.exotel.com/{self.exotel_sid}/exoml/start_voice/{self.exotel_flow_app_id}"

        logger.info(f"API URL: {url}")
        logger.info(f"Flow URL: {flow_url}")

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
            'StatusCallback': f"{os.getenv('BASE_URL', 'https://3.108.35.213')}/exotel-webhook"
        }
        
        logger.info("Payload validation:")
        logger.info(f"  • From (Customer): {payload['From']}")
        logger.info(f"  • CallerId (ExoPhone): {payload['CallerId']}")
        logger.info(f"  • Flow URL: {payload['Url']}")
        logger.info(f"  • CustomField: {custom_field_str[:100]}...")
        
        logger.info(f"Triggering Exotel call to customer {to_number}")
        logger.call.info(f"CustomField Payload: {custom_field_str}")
        logger.info(f"Debug - API URL: {url}")
        logger.info(f"Debug - Auth: {self.exotel_api_key[:10]}...{self.exotel_api_key[-10:]} / {self.exotel_token[:10]}...{self.exotel_token[-10:]}")
        print(f"🔧 [CHECKPOINT] Debug - Full Payload: {json.dumps(payload, indent=2)}")

        try:
            print(f"🎯 [CHECKPOINT] Making HTTP request to Exotel API...")
            async with httpx.AsyncClient(auth=(self.exotel_api_key, self.exotel_token)) as client:
                response = await client.post(url, data=payload)
            
            print(f"🎯 [CHECKPOINT] Exotel API response received")
            print(f"🎯 [CHECKPOINT] Status Code: {response.status_code}")
            print(f"🎯 [CHECKPOINT] Response Text: {response.text[:500]}...")
            
            if response.status_code == 200:
                response_data = response.json()
                call_sid = response_data.get('Call', {}).get('Sid')
                print(f"✅ [CHECKPOINT] Exotel call triggered successfully. CallSid: {call_sid}")
                print(f"✅ [CHECKPOINT] Full response: {json.dumps(response_data, indent=2)}")
                return {'success': True, 'call_sid': call_sid, 'response': response_data}
            else:
                error_message = f"Exotel API Error: {response.status_code} - {response.text}"
                print(f"❌ [CHECKPOINT] Failed to trigger Exotel call. {error_message}")
                return {'success': False, 'error': error_message}
        except Exception as e:
            error_message = str(e)
            print(f"❌ [CHECKPOINT] Exception during Exotel call trigger: {error_message}")
            return {'success': False, 'error': error_message}

    async def _trigger_agent_transfer(self, customer_number: str, agent_number: str) -> Dict[str, Any]:
        """Trigger agent transfer call"""
        url = f"https://api.exotel.com/v1/Accounts/{self.exotel_sid}/Calls/connect.json"
        
        payload = {
            "From": customer_number,
            "To": agent_number,
            "CallerId": self.exotel_virtual_number,
        }
        
        try:
            async with httpx.AsyncClient(auth=(self.exotel_api_key, self.exotel_token)) as client:
                response = await client.post(url, data=payload, timeout=30.0)
                
                if response.status_code == 200:
                    return {'success': True, 'response': response.json()}
                else:
                    return {'success': False, 'error': f'HTTP {response.status_code}: {response.text}'}
                    
        except Exception as e:
            return {'success': False, 'error': str(e)}

# Global service instance
call_service = CallManagementService()
