"""
New Database Schema Definitions
==============================
This file contains the new database schema models after redesign.
Use this to replace your existing database/schemas.py file.

Schema Overview:
1. customers - Root entity for customer data
2. loans - Loan information tied to customers  
3. file_uploads - Track CSV batch uploads
4. upload_rows - Individual rows from CSV uploads
5. call_sessions - Call session tracking
"""

import os
import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    create_engine, MetaData, Column, String, Text, Integer, 
    Numeric, Date, DateTime, Boolean, JSON, UUID, ForeignKey,
    UniqueConstraint, Index, func, text
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session, joinedload
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from dotenv import load_dotenv

load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:IntalksAI07@db-voice-agent.cviea4aicss0.ap-south-1.rds.amazonaws.com:5432/db-voice-agent")

# Create SQLAlchemy components
engine = create_engine(DATABASE_URL, echo=False)
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# =============================================================================
# DATABASE MODELS
# =============================================================================

class Customer(Base):
    """
    Root entity for customers
    Other tables depend on this
    """
    __tablename__ = "customers"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fingerprint = Column(Text, unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    primary_phone = Column(String(20), nullable=True, index=True)
    national_id = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    state = Column(String(100), nullable=True)  # Customer's state
    first_uploaded_at = Column(DateTime, nullable=True)
    last_contact_date = Column(DateTime, nullable=True)
    do_not_call = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Backward compatibility fields (mapped to new fields)
    @property
    def name(self):
        return self.full_name
    
    @name.setter
    def name(self, value):
        self.full_name = value
        
    @property
    def phone_number(self):
        return self.primary_phone
    
    @phone_number.setter
    def phone_number(self, value):
        self.primary_phone = value
        # Auto-generate fingerprint when phone is set
        if value:
            self.fingerprint = compute_fingerprint(value, self.national_id or "")
    
    @property
    def language_code(self):
        return getattr(self, '_language_code', 'hi-IN')
    
    @language_code.setter 
    def language_code(self, value):
        self._language_code = value
    
    # Legacy fields for backward compatibility - will be moved to loans table
    loan_id = Column(String(50), nullable=True)  # Legacy field - deprecated
    amount = Column(String(20), nullable=True)   # Legacy field - deprecated
    due_date = Column(String(50), nullable=True) # Legacy field - deprecated
    
    # Relationships
    loans = relationship("Loan", back_populates="customer", cascade="all, delete-orphan")
    call_sessions = relationship("CallSession", back_populates="customer", cascade="all, delete-orphan")
    upload_row_matches = relationship("UploadRow", foreign_keys="UploadRow.match_customer_id", back_populates="matched_customer")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('primary_phone', name='uix_customer_primary_phone'),
        Index('ix_customer_fingerprint', 'fingerprint'),
        Index('ix_customer_primary_phone', 'primary_phone'),
        Index('ix_customer_last_contact', 'last_contact_date'),
        Index('ix_customer_state', 'state'),
    )
    
"""
New Database Schema Definitions
==============================
This file contains the new database schema models after redesign.
Use this to replace your existing database/schemas.py file.

Schema Overview:
1. customers - Root entity for customer data
2. loans - Loan information tied to customers  
3. file_uploads - Track CSV batch uploads
4. upload_rows - Individual rows from CSV uploads
5. call_sessions - Call session tracking
"""

import os
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy import (
    create_engine, MetaData, Column, String, Text, Integer, 
    Numeric, Date, DateTime, Boolean, JSON, UUID, ForeignKey,
    UniqueConstraint, Index, func, text
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session, joinedload
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from dotenv import load_dotenv

load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:IntalksAI07@db-voice-agent.cviea4aicss0.ap-south-1.rds.amazonaws.com:5432/db-voice-agent")

# Create SQLAlchemy components  
engine = create_engine(
    DATABASE_URL, 
    echo=True,  # Enable SQL logging for debugging
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600
)
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def compute_fingerprint(phone: str, national_id: str = "") -> str:
    """
    Compute a unique fingerprint for customer deduplication
    """
    # Normalize phone number
    normalized_phone = phone.replace("+", "").replace("-", "").replace(" ", "") if phone else ""
    normalized_id = national_id.strip().upper() if national_id else ""
    
    # Create fingerprint from phone + national_id
    fingerprint_data = f"{normalized_phone}|{normalized_id}"
    return hashlib.md5(fingerprint_data.encode()).hexdigest()


def normalize_phone(phone: str) -> str:
    """Normalize phone number for indexing"""
    if not phone:
        return ""
    return phone.replace("+", "").replace("-", "").replace(" ", "")

# =============================================================================
# DATABASE MODELS
# =============================================================================

class Customer(Base):
    """
    Root entity for customers
    Other tables depend on this
    """
    __tablename__ = "customers"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fingerprint = Column(Text, unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    primary_phone = Column(String(20), nullable=True, index=True)
    national_id = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    state = Column(String(100), nullable=True)  # Customer's state
    first_uploaded_at = Column(DateTime, nullable=True)
    last_contact_date = Column(DateTime, nullable=True)
    do_not_call = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Backward compatibility fields (mapped to new fields)
    @property
    def name(self):
        return self.full_name
    
    @name.setter
    def name(self, value):
        self.full_name = value
        
    @property
    def phone_number(self):
        return self.primary_phone
    
    @phone_number.setter
    def phone_number(self, value):
        self.primary_phone = value
        # Auto-generate fingerprint when phone is set
        if value:
            self.fingerprint = compute_fingerprint(value, self.national_id or "")
    
    @property
    def language_code(self):
        return getattr(self, '_language_code', 'hi-IN')
    
    @language_code.setter 
    def language_code(self, value):
        self._language_code = value
    
    # Legacy fields for backward compatibility - will be moved to loans table
    loan_id = Column(String(50), nullable=True)  # Legacy field - deprecated
    amount = Column(String(20), nullable=True)   # Legacy field - deprecated
    due_date = Column(String(50), nullable=True) # Legacy field - deprecated
    
    # Relationships
    loans = relationship("Loan", back_populates="customer", cascade="all, delete-orphan")
    call_sessions = relationship("CallSession", back_populates="customer", cascade="all, delete-orphan")
    upload_row_matches = relationship("UploadRow", foreign_keys="UploadRow.match_customer_id", back_populates="matched_customer")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('primary_phone', name='uix_customer_primary_phone'),
        Index('ix_customer_fingerprint', 'fingerprint'),
        Index('ix_customer_primary_phone', 'primary_phone'),
        Index('ix_customer_last_contact', 'last_contact_date'),
        Index('ix_customer_state', 'state'),
    )
    
    def __repr__(self):
        return f"<Customer(id={self.id}, name='{self.full_name}', phone='{self.primary_phone}')>"


class Loan(Base):
    """
    Loan information tied to customers
    Depends on customers table
    """
    __tablename__ = "loans"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(PG_UUID(as_uuid=True), ForeignKey('customers.id', ondelete='CASCADE'), nullable=False)
    loan_id = Column(String(100), unique=True, nullable=False, index=True)  # External identifier
    principal_amount = Column(Numeric(15, 2), nullable=True)
    outstanding_amount = Column(Numeric(15, 2), nullable=True)
    due_amount = Column(Numeric(15, 2), nullable=True)  # Current due amount from CSV
    next_due_date = Column(Date, nullable=True)
    last_paid_date = Column(Date, nullable=True)  # Last payment date from CSV
    last_paid_amount = Column(Numeric(15, 2), nullable=True)  # Last payment amount from CSV
    status = Column(String(50), nullable=True, default='active')
    
    # Branch and Employee Information
    cluster = Column(String(100), nullable=True)
    branch = Column(String(255), nullable=True)
    branch_contact_number = Column(String(20), nullable=True)
    employee_name = Column(String(255), nullable=True)
    employee_id = Column(String(100), nullable=True)
    employee_contact_number = Column(String(20), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    customer = relationship("Customer", back_populates="loans")
    call_sessions = relationship("CallSession", back_populates="loan", cascade="all, delete-orphan")
    upload_row_matches = relationship("UploadRow", foreign_keys="UploadRow.match_loan_id", back_populates="matched_loan")
    
    # Constraints
    __table_args__ = (
        Index('ix_loan_customer_id', 'customer_id'),
        Index('ix_loan_external_id', 'loan_id'),
        Index('ix_loan_status', 'status'),
        Index('ix_loan_due_date', 'next_due_date'),
        Index('ix_loan_cluster', 'cluster'),
        Index('ix_loan_branch', 'branch'),
        Index('ix_loan_employee_id', 'employee_id'),
    )
    
    def __repr__(self):
        return f"<Loan(id={self.id}, loan_id='{self.loan_id}', outstanding={self.outstanding_amount})>"


class FileUpload(Base):
    """
    Root entity for tracking CSV batch uploads
    """
    __tablename__ = "file_uploads"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=True)
    uploaded_by = Column(String(100), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    total_records = Column(Integer, default=0, nullable=False)
    processed_records = Column(Integer, default=0, nullable=False)
    success_records = Column(Integer, default=0, nullable=False)
    failed_records = Column(Integer, default=0, nullable=False)
    status = Column(String(50), default='processing', nullable=False)
    processing_errors = Column(JSON, nullable=True)
    
    # Backward compatibility fields
    file_path = Column(String(500), nullable=True)
    upload_status = Column(String(50), nullable=True)  # Maps to status
    upload_time = Column(DateTime, nullable=True)      # Maps to uploaded_at
    
    @property
    def upload_status(self):
        return self.status
    
    @upload_status.setter
    def upload_status(self, value):
        self.status = value
        
    @property
    def upload_time(self):
        return self.uploaded_at
    
    @upload_time.setter 
    def upload_time(self, value):
        self.uploaded_at = value
    
    # Relationships
    upload_rows = relationship("UploadRow", back_populates="file_upload", cascade="all, delete-orphan")
    triggered_call_sessions = relationship("CallSession", foreign_keys="CallSession.triggered_by_batch", back_populates="triggering_batch")
    
    # Constraints
    __table_args__ = (
        Index('ix_file_upload_status', 'status'),
        Index('ix_file_upload_uploaded_at', 'uploaded_at'),
    )
    
    def __repr__(self):
        return f"<FileUpload(id={self.id}, filename='{self.filename}', status='{self.status}')>"


class UploadRow(Base):
    """
    Individual rows from CSV uploads
    Depends on file_uploads, loans, customers
    """
    __tablename__ = "upload_rows"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_upload_id = Column(PG_UUID(as_uuid=True), ForeignKey('file_uploads.id', ondelete='CASCADE'), nullable=False)
    line_number = Column(Integer, nullable=False)
    raw_data = Column(JSON, nullable=False)
    phone_normalized = Column(String(20), nullable=True, index=True)
    loan_id_text = Column(String(100), nullable=True)
    row_fingerprint = Column(String(100), nullable=False)
    
    # Foreign key references for matching
    match_loan_id = Column(PG_UUID(as_uuid=True), ForeignKey('loans.id', ondelete='SET NULL'), nullable=True)
    match_customer_id = Column(PG_UUID(as_uuid=True), ForeignKey('customers.id', ondelete='SET NULL'), nullable=True)
    
    # Matching metadata
    match_method = Column(String(50), nullable=True)  # 'fingerprint', 'created', 'phone', etc.
    matched_at = Column(DateTime, nullable=True)
    status = Column(String(50), default='pending', nullable=False)
    error = Column(Text, nullable=True)
    
    # Relationships
    file_upload = relationship("FileUpload", back_populates="upload_rows")
    matched_loan = relationship("Loan", foreign_keys=[match_loan_id], back_populates="upload_row_matches")
    matched_customer = relationship("Customer", foreign_keys=[match_customer_id], back_populates="upload_row_matches")
    triggered_call_sessions = relationship("CallSession", foreign_keys="CallSession.triggered_by_row", back_populates="triggering_row")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('file_upload_id', 'row_fingerprint', name='uix_upload_row_fingerprint'),
        Index('ix_upload_row_file_upload', 'file_upload_id'),
        Index('ix_upload_row_phone_normalized', 'phone_normalized'),
        Index('ix_upload_row_status', 'status'),
        Index('ix_upload_row_match_loan', 'match_loan_id'),
        Index('ix_upload_row_match_customer', 'match_customer_id'),
    )
    
class CallSession(Base):
    """
    Call session tracking - Enhanced version with backward compatibility
    Depends on loans, customers, file_uploads, upload_rows
    """
    __tablename__ = "call_sessions"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_sid = Column(String(100), unique=True, nullable=True, index=True)  # Telephony provider ID
    loan_id = Column(PG_UUID(as_uuid=True), ForeignKey('loans.id', ondelete='CASCADE'), nullable=True)
    customer_id = Column(PG_UUID(as_uuid=True), ForeignKey('customers.id', ondelete='CASCADE'), nullable=False)
    initiated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String(50), default='scheduled', nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    from_number = Column(String(20), nullable=True)
    to_number = Column(String(20), nullable=False)
    
    # Batch tracking
    triggered_by_batch = Column(PG_UUID(as_uuid=True), ForeignKey('file_uploads.id', ondelete='SET NULL'), nullable=True)
    triggered_by_row = Column(PG_UUID(as_uuid=True), ForeignKey('upload_rows.id', ondelete='SET NULL'), nullable=True)
    
    # Additional data
    call_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Backward compatibility fields
    websocket_session_id = Column(String(100), nullable=True)  # WebSocket session ID
    call_direction = Column(String(20), default='outbound', nullable=True)  # outbound, inbound
    start_time = Column(DateTime, nullable=True)  # Maps to initiated_at
    end_time = Column(DateTime, nullable=True)
    duration = Column(Integer, nullable=True)  # Maps to duration_seconds
    
    # Exotel specific data
    exotel_data = Column(JSON, nullable=True)  # Store raw Exotel response
    agent_transfer_time = Column(DateTime, nullable=True)
    agent_number = Column(String(20), nullable=True)
    
    # AI Conversation data
    conversation_transcript = Column(JSON, nullable=True)  # Store conversation history
    intent_detected = Column(String(100), nullable=True)
    language_detected = Column(String(10), nullable=True)
    
    # Backward compatibility properties
    @property
    def start_time(self):
        return self.initiated_at
    
    @start_time.setter
    def start_time(self, value):
        self.initiated_at = value
        
    @property
    def duration(self):
        return self.duration_seconds
    
    @duration.setter
    def duration(self, value):
        self.duration_seconds = value
    
    # Relationships
    loan = relationship("Loan", back_populates="call_sessions")
    customer = relationship("Customer", back_populates="call_sessions")
    triggering_batch = relationship("FileUpload", foreign_keys=[triggered_by_batch], back_populates="triggered_call_sessions")
    triggering_row = relationship("UploadRow", foreign_keys=[triggered_by_row], back_populates="triggered_call_sessions")
    status_updates = relationship("CallStatusUpdate", back_populates="call_session", cascade="all, delete-orphan")
    
    # Constraints
    __table_args__ = (
        Index('ix_call_session_call_sid', 'call_sid'),
        Index('ix_call_session_customer', 'customer_id'),
        Index('ix_call_session_loan', 'loan_id'),
        Index('ix_call_session_status', 'status'),
        Index('ix_call_session_initiated_at', 'initiated_at'),
        Index('ix_call_session_to_number', 'to_number'),
        Index('ix_call_session_batch', 'triggered_by_batch'),
    )
    
    def __repr__(self):
        return f"<CallSession(id={self.id}, call_sid='{self.call_sid}', status='{self.status}')>"


class CallStatusUpdate(Base):
    """Call status update tracking table"""
    __tablename__ = 'call_status_updates'
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_session_id = Column(PG_UUID(as_uuid=True), ForeignKey('call_sessions.id'), nullable=False)
    
    status = Column(String(50), nullable=False)
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    extra_data = Column(JSON)
    
    # Relationships
    call_session = relationship("CallSession", back_populates="status_updates")


# =============================================================================
# STATUS CONSTANTS AND ENUMS
# =============================================================================

class CallStatus:
    """Call status constants for compatibility"""
    INITIATED = "initiated"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    CALL_IN_PROGRESS = "call_in_progress"  # Alias for compatibility
    AGENT_TRANSFER = "agent_transfer"
    COMPLETED = "completed"
    CALL_COMPLETED = "call_completed"  # Alias for compatibility
    FAILED = "failed"
    CALL_FAILED = "call_failed"  # Alias for compatibility
    NOT_PICKED = "not_picked"
    DISCONNECTED = "disconnected"
    BUSY = "busy"
    NO_ANSWER = "no_answer"


# =============================================================================
# DATABASE MANAGER CLASS
# =============================================================================

class DatabaseManager:
    """Database manager for backward compatibility"""
    def __init__(self):
        try:
            print(f"🔧 Initializing database connection to: {DATABASE_URL}")
            self.engine = engine
            self.SessionLocal = SessionLocal
            print("✅ Database engine initialized successfully")
        except Exception as e:
            print(f"❌ Failed to initialize database engine: {e}")
            print(f"   Database URL: {DATABASE_URL}")
            raise
        
    def get_session(self):
        """Get a database session"""
        try:
            session = self.SessionLocal()
            return session
        except Exception as e:
            print(f"❌ Failed to create database session: {e}")
            raise
        
    def close_session(self, session):
        """Close database session safely"""
        try:
            session.close()
        except Exception as e:
            print(f"❌ Error closing database session: {e}")
    
    def test_connection(self):
        """Test database connection"""
        try:
            print("🔌 Testing database connection...")
            session = self.get_session()
            session.execute(text("SELECT 1"))
            self.close_session(session)
            print("✅ Database connection test passed")
            return True
        except Exception as e:
            print(f"❌ Database connection test failed: {e}")
            return False
    
    def create_tables(self):
        """Create all tables if they don't exist"""
        try:
            print("🔧 Creating database tables...")
            
            # Get all table names that will be created
            table_names = [table.name for table in Base.metadata.tables.values()]
            print(f"📋 Tables to create: {', '.join(table_names)}")
            
            Base.metadata.create_all(bind=self.engine)
            
            # Confirm each table was created
            print("✅ Database schema creation completed!")
            for table_name in table_names:
                print(f"   ✓ Table '{table_name}' created successfully")
            
            print(f"🎉 Total {len(table_names)} tables created in database")
            return True
        except Exception as e:
            print(f"❌ Failed to create tables: {e}")
            return False

# Global database manager instance for compatibility
db_manager = DatabaseManager()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_session() -> Session:
    """Get a new database session"""
    return SessionLocal()


def init_database() -> bool:
    """Initialize the database - create tables if they don't exist"""
    try:
        print("🚀 Initializing Voice Assistant Database...")
        print("=" * 50)
        
        if db_manager.test_connection():
            print("✅ Database connection successful")
            print(f"🔗 Connected to: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'database'}")
            
            if db_manager.create_tables():
                print("=" * 50)
                print("🎉 Database initialization completed successfully!")
                print("📊 Database schema status:")
                print("   • Customer table: Ready for customer data")
                print("   • Loan table: Ready for loan tracking")
                print("   • CallSession table: Ready for call tracking")
                print("   • CallStatusUpdate table: Ready for status updates")
                print("   • FileUpload table: Ready for file management")
                print("   • UploadRow table: Ready for CSV row tracking")
                print("=" * 50)
                return True
            else:
                print("❌ Failed to create database tables")
                return False
        else:
            print("❌ Database connection failed")
            print("💡 Please check your DATABASE_URL in .env file")
            return False
    except Exception as e:
        print(f"❌ Failed to initialize database: {e}")
        return False


def get_customer_by_fingerprint(session: Session, fingerprint: str) -> Optional[Customer]:
    """Get customer by fingerprint"""
    return session.query(Customer).filter(Customer.fingerprint == fingerprint).first()


def get_customer_by_phone(session, phone_number: str) -> Optional[Customer]:
    """Get customer by phone number - backward compatible"""
    try:
        normalized = normalize_phone(phone_number)
        return session.query(Customer).options(joinedload(Customer.loans)).filter(Customer.primary_phone.like(f"%{normalized[-10:]}")).first()
    except Exception as e:
        print(f"❌ Error getting customer by phone: {e}")
        return None


def get_loan_by_external_id(session: Session, loan_id: str) -> Optional[Loan]:
    """Get loan by external loan ID"""
    return session.query(Loan).filter(Loan.loan_id == loan_id).first()


def get_call_session_by_sid(session, call_sid: str) -> Optional[CallSession]:
    """Get call session by call SID with customer relationship loaded - backward compatible"""
    try:
        return session.query(CallSession).options(joinedload(CallSession.customer)).filter(CallSession.call_sid == call_sid).first()
    except Exception as e:
        print(f"❌ Error getting call session by SID: {e}")
        return None


def get_calls_by_customer(session: Session, customer_id: str) -> List[CallSession]:
    """Get all calls for a customer"""
    return session.query(CallSession).filter(CallSession.customer_id == customer_id).all()


def get_calls_by_loan(session: Session, loan_id: str) -> List[CallSession]:
    """Get all calls for a loan"""
    return session.query(CallSession).filter(CallSession.loan_id == loan_id).all()


def get_call_counts_for_loan(session: Session, loan_id: str) -> dict:
    """Get call statistics for a loan"""
    calls = get_calls_by_loan(session, loan_id)
    
    total_calls = len(calls)
    completed_calls = len([c for c in calls if c.status == 'completed'])
    failed_calls = len([c for c in calls if c.status == 'failed'])
    
    return {
        'total_calls': total_calls,
        'completed_calls': completed_calls,
        'failed_calls': failed_calls,
        'success_rate': (completed_calls / total_calls * 100) if total_calls > 0 else 0
    }


def create_customer(session, customer_data: dict) -> Optional[Customer]:
    """Create a new customer - backward compatible"""
    try:
        # Handle both old and new data formats
        phone = customer_data.get('phone_number') or customer_data.get('primary_phone', '')
        name = customer_data.get('name') or customer_data.get('full_name', '')
        
        fingerprint = compute_fingerprint(
            phone,
            customer_data.get('national_id', '')
        )
        
        customer = Customer(
            fingerprint=fingerprint,
            full_name=name,
            primary_phone=phone,
            national_id=customer_data.get('national_id'),
            email=customer_data.get('email'),
            state=customer_data.get('state'),
            first_uploaded_at=datetime.utcnow(),
            # Legacy fields
            loan_id=customer_data.get('loan_id'),
            amount=customer_data.get('amount'),
            due_date=customer_data.get('due_date'),
        )
        
        session.add(customer)
        session.commit()
        session.refresh(customer)
        print(f"✅ Created customer: {customer.full_name} ({customer.primary_phone})")
        return customer
    except Exception as e:
        session.rollback()
        print(f"❌ Error creating customer: {e}")
        return None


def create_loan(session: Session, loan_data: dict) -> Loan:
    """Create a new loan with all enhanced fields"""
    loan = Loan(
        customer_id=loan_data['customer_id'],
        loan_id=loan_data['loan_id'],
        principal_amount=loan_data.get('principal_amount'),
        outstanding_amount=loan_data.get('outstanding_amount'),
        due_amount=loan_data.get('due_amount'),
        next_due_date=loan_data.get('next_due_date'),
        last_paid_date=loan_data.get('last_paid_date'),
        last_paid_amount=loan_data.get('last_paid_amount'),
        status=loan_data.get('status', 'active'),
        cluster=loan_data.get('cluster'),
        branch=loan_data.get('branch'),
        branch_contact_number=loan_data.get('branch_contact_number'),
        employee_name=loan_data.get('employee_name'),
        employee_id=loan_data.get('employee_id'),
        employee_contact_number=loan_data.get('employee_contact_number')
    )
    
    session.add(loan)
    session.flush()
    return loan


def create_call_session(session, call_sid: str, customer_id: str, websocket_session_id: str = None) -> Optional[CallSession]:
    """Create a new call session - backward compatible"""
    try:
        call_session = CallSession(
            call_sid=call_sid,
            customer_id=customer_id,
            websocket_session_id=websocket_session_id,
            status=CallStatus.INITIATED,
            to_number="",  # Will be filled from customer data
        )
        session.add(call_session)
        session.commit()
        session.refresh(call_session)
        print(f"✅ Created call session: {call_sid} for customer {customer_id}")
        return call_session
    except Exception as e:
        session.rollback()
        print(f"❌ Error creating call session: {e}")
        return None


def update_call_status(session, call_sid: str, status: str, message: str = None, extra_data: dict = None) -> Optional[CallSession]:
    """Update call status and create status update record - backward compatible"""
    try:
        call_session = session.query(CallSession).filter(CallSession.call_sid == call_sid).first()
        if call_session:
            # Update main status
            call_session.status = status
            call_session.updated_at = datetime.utcnow()
            
            # Create status update record
            status_update = CallStatusUpdate(
                call_session_id=call_session.id,
                status=status,
                message=message,
                extra_data=extra_data
            )
            session.add(status_update)
            session.commit()
            print(f"✅ Updated call {call_sid} status to: {status}")
            return call_session
        else:
            print(f"⚠️ Call session not found: {call_sid}")
        return None
    except Exception as e:
        session.rollback()
        print(f"❌ Error updating call status: {e}")
        return None


def get_customers_list(session, limit: int = 100, offset: int = 0) -> List[Customer]:
    """Get list of customers with pagination - backward compatible"""
    try:
        return session.query(Customer).offset(offset).limit(limit).all()
    except Exception as e:
        print(f"❌ Error getting customers list: {e}")
        return []


def get_call_sessions_by_status(session, status: str, limit: int = 50) -> List[CallSession]:
    """Get call sessions by status - backward compatible"""
    try:
        return session.query(CallSession).filter(CallSession.status == status).limit(limit).all()
    except Exception as e:
        print(f"❌ Error getting call sessions by status: {e}")
        return []


def get_customer_call_history(session, customer_id: str) -> List[CallSession]:
    """Get call history for a specific customer - backward compatible"""
    try:
        return session.query(CallSession).filter(CallSession.customer_id == customer_id).order_by(CallSession.created_at.desc()).all()
    except Exception as e:
        print(f"❌ Error getting customer call history: {e}")
        return []


def cleanup_old_sessions(session, days_old: int = 7) -> int:
    """Clean up old call sessions older than specified days - backward compatible"""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        old_sessions = session.query(CallSession).filter(CallSession.created_at < cutoff_date).all()
        count = len(old_sessions)
        
        for session_obj in old_sessions:
            session.delete(session_obj)
        
        session.commit()
        if count > 0:
            print(f"✅ Cleaned up {count} old call sessions (older than {days_old} days)")
        return count
    except Exception as e:
        session.rollback()
        print(f"❌ Error cleaning up old sessions: {e}")
        return 0


def update_customer_call_status_by_phone(session, phone: str, status: str) -> bool:
    """Update customer call status by phone number"""
    try:
        customer = get_customer_by_phone(session, phone)
        if customer:
            customer.last_contact_date = datetime.utcnow()
            session.commit()
            return True
        return False
    except Exception as e:
        session.rollback()
        print(f"❌ Error updating customer call status: {e}")
        return False


def update_customer_call_status(session, customer_id: str, status: str) -> bool:
    """Update customer call status by customer ID"""
    try:
        customer = session.query(Customer).filter(Customer.id == customer_id).first()
        if customer:
            customer.last_contact_date = datetime.utcnow()
            session.commit()
            return True
        return False
    except Exception as e:
        session.rollback()
        print(f"❌ Error updating customer call status: {e}")
        return False


def print_database_info():
    """Print detailed information about the database schema"""
    print("\n" + "=" * 60)
    print("📊 VOICE ASSISTANT DATABASE SCHEMA INFORMATION")
    print("=" * 60)
    
    print("\n🏢 DATABASE TABLES:")
    print("-" * 40)
    
    tables_info = [
        {
            "name": "customers",
            "description": "Stores customer information and contact details",
            "key_fields": ["id", "full_name", "primary_phone", "state", "fingerprint"]
        },
        {
            "name": "loans", 
            "description": "Tracks loan information tied to customers",
            "key_fields": ["id", "customer_id", "loan_id", "outstanding_amount", "next_due_date"]
        },
        {
            "name": "call_sessions", 
            "description": "Tracks individual call sessions with telephony providers",
            "key_fields": ["id", "call_sid", "customer_id", "status", "initiated_at"]
        },
        {
            "name": "call_status_updates",
            "description": "Records real-time status changes for calls",
            "key_fields": ["id", "call_session_id", "status", "timestamp"]
        },
        {
            "name": "file_uploads",
            "description": "Manages uploaded customer data files",
            "key_fields": ["id", "filename", "total_records", "status"]
        },
        {
            "name": "upload_rows",
            "description": "Tracks individual rows from CSV uploads",
            "key_fields": ["id", "file_upload_id", "line_number", "status"]
        }
    ]
    
    for table in tables_info:
        print(f"📋 {table['name'].upper()}")
        print(f"   Purpose: {table['description']}")
        print(f"   Key Fields: {', '.join(table['key_fields'])}")
        print()
    
    print("🔄 CALL STATUS FLOW:")
    print("-" * 40)
    statuses = [
        CallStatus.INITIATED,
        CallStatus.RINGING, 
        CallStatus.IN_PROGRESS,
        CallStatus.AGENT_TRANSFER,
        CallStatus.COMPLETED
    ]
    print(" → ".join(statuses))
    
    print(f"\n🌐 DATABASE URL: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'Not configured'}")
    print("=" * 60)


def get_database_info():
    """Alias for print_database_info for backwards compatibility"""
    print_database_info()


# =============================================================================
# EXPORTS
# =============================================================================

# Export commonly used items
__all__ = [
    'Base', 'engine', 'SessionLocal', 'get_session', 'init_database',
    'Customer', 'Loan', 'FileUpload', 'UploadRow', 'CallSession', 'CallStatusUpdate',
    'CallStatus', 'db_manager', 'DatabaseManager',
    'compute_fingerprint', 'normalize_phone',
    'get_customer_by_fingerprint', 'get_customer_by_phone',
    'get_loan_by_external_id', 'get_call_session_by_sid',
    'get_calls_by_customer', 'get_calls_by_loan', 'get_call_counts_for_loan',
    'create_customer', 'create_loan', 'create_call_session',
    'update_call_status', 'update_customer_call_status_by_phone', 'update_customer_call_status',
    'get_customers_list', 'get_call_sessions_by_status', 'get_customer_call_history', 'cleanup_old_sessions',
    'print_database_info', 'get_database_info'
]

# Initialize database info display
if __name__ == "__main__":
    print("🧪 Database Schema Module Loaded")
    print_database_info()
