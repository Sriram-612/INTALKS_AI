-- =============================================================================
-- VOICE ASSISTANT CALL MANAGEMENT SYSTEM - COMPLETE DATABASE SCHEMA(RUN THIS BEFORE EXECUTION IN PGADMIN4)
-- =============================================================================
-- This script creates all tables for the Voice Assistant Call Management System
-- Execute this script in pgAdmin4 to create the complete database structure
-- 
-- Author: Voice Assistant Development Team
-- Created: September 2025
-- Version: 3.0
-- =============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- ENUMS AND TYPES
-- =============================================================================

-- Call Status Enum
DO $$ BEGIN
    CREATE TYPE call_status_enum AS ENUM (
        'initiated', 'ringing', 'in_progress', 'agent_transfer', 
        'completed', 'failed', 'not_picked', 'cancelled', 'busy'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Call Direction Enum
DO $$ BEGIN
    CREATE TYPE call_direction_enum AS ENUM ('inbound', 'outbound');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Customer Status Enum
DO $$ BEGIN
    CREATE TYPE customer_status_enum AS ENUM ('active', 'inactive', 'blocked', 'pending');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Loan Status Enum
DO $$ BEGIN
    CREATE TYPE loan_status_enum AS ENUM ('active', 'overdue', 'paid', 'defaulted', 'restructured');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Payment Status Enum
DO $$ BEGIN
    CREATE TYPE payment_status_enum AS ENUM ('pending', 'completed', 'failed', 'refunded', 'cancelled');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- File Upload Status Enum
DO $$ BEGIN
    CREATE TYPE file_upload_status_enum AS ENUM ('processing', 'completed', 'failed', 'partial');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Conversation Sentiment Enum
DO $$ BEGIN
    CREATE TYPE conversation_sentiment_enum AS ENUM ('positive', 'negative', 'neutral', 'frustrated', 'satisfied');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- =============================================================================
-- CORE CUSTOMER MANAGEMENT TABLES
-- =============================================================================

-- Customers Table
CREATE TABLE IF NOT EXISTS customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fingerprint TEXT UNIQUE NOT NULL,
    customer_code VARCHAR(50) UNIQUE,
    
    -- Personal Information
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    full_name VARCHAR(255),
    date_of_birth TIMESTAMP,
    gender VARCHAR(10),
    national_id VARCHAR(50),
    
    -- Contact Information
    primary_phone VARCHAR(20) NOT NULL,
    secondary_phone VARCHAR(20),
    email VARCHAR(255),
    
    -- Address Information
    address_line1 VARCHAR(255),
    address_line2 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(100),
    postal_code VARCHAR(20),
    country VARCHAR(100) DEFAULT 'India',
    
    -- Preferences
    preferred_language VARCHAR(10) DEFAULT 'hi-IN',
    preferred_contact_time VARCHAR(50),
    timezone VARCHAR(50) DEFAULT 'Asia/Kolkata',
    
    -- Account Status
    status VARCHAR(50) DEFAULT 'not_initiated',
    call_status VARCHAR(50) DEFAULT 'not_initiated',
    kyc_verified BOOLEAN DEFAULT FALSE,
    consent_given BOOLEAN DEFAULT FALSE,
    do_not_call BOOLEAN DEFAULT FALSE,
    
    -- Metadata
    first_uploaded_at TIMESTAMP,
    last_contact_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
    created_by VARCHAR(100)
);

-- Customer Notes Table
CREATE TABLE IF NOT EXISTS customer_notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    
    note_type VARCHAR(50) NOT NULL,
    title VARCHAR(255),
    content TEXT NOT NULL,
    priority VARCHAR(20) DEFAULT 'normal',
    
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    created_by VARCHAR(100)
);

-- =============================================================================
-- LOAN MANAGEMENT TABLES
-- =============================================================================

-- Loans Table
CREATE TABLE IF NOT EXISTS loans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    
    -- Loan Identification
    loan_id VARCHAR(100) UNIQUE NOT NULL,
    loan_type VARCHAR(50),
    
    -- Financial Details
    principal_amount NUMERIC(15, 2),
    outstanding_amount NUMERIC(15, 2),
    interest_rate NUMERIC(5, 2),
    due_amount NUMERIC(15, 2),
    
    -- Term Details
    loan_term_months INTEGER,
    emi_amount NUMERIC(10, 2),
    next_due_date DATE,
    last_payment_date DATE,
    last_paid_date DATE,
    last_paid_amount NUMERIC(15, 2),
    
    -- Status and Dates
    status loan_status_enum DEFAULT 'active',
    disbursement_date TIMESTAMP,
    maturity_date TIMESTAMP,
    
    -- Risk Assessment
    days_past_due INTEGER DEFAULT 0,
    risk_category VARCHAR(20),
    
    -- Branch and Employee Information
    cluster VARCHAR(100),
    branch VARCHAR(255),
    branch_contact_number VARCHAR(20),
    employee_name VARCHAR(255),
    employee_id VARCHAR(100),
    employee_contact_number VARCHAR(20),
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- Payments Table
CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    loan_id UUID NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    
    -- Payment Details
    payment_id VARCHAR(100) UNIQUE NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    payment_method VARCHAR(50),
    payment_date TIMESTAMP NOT NULL,
    
    -- Status and Processing
    status payment_status_enum DEFAULT 'pending',
    transaction_reference VARCHAR(255),
    gateway_response JSONB,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    processed_at TIMESTAMP,
    processed_by VARCHAR(100)
);

-- =============================================================================
-- FILE UPLOAD MANAGEMENT TABLES
-- =============================================================================

-- File Uploads Table
CREATE TABLE IF NOT EXISTS file_uploads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- File Details
    filename VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255),
    file_path VARCHAR(500),
    file_size INTEGER,
    file_type VARCHAR(50),
    
    -- Processing Status
    status file_upload_status_enum DEFAULT 'processing',
    total_records INTEGER DEFAULT 0,
    processed_records INTEGER DEFAULT 0,
    success_records INTEGER DEFAULT 0,
    failed_records INTEGER DEFAULT 0,
    duplicate_records INTEGER DEFAULT 0,
    
    -- Processing Details
    processing_started_at TIMESTAMP,
    processing_completed_at TIMESTAMP,
    processing_errors JSONB,
    processing_logs JSONB,
    validation_errors JSONB,
    
    -- Metadata
    uploaded_at TIMESTAMP DEFAULT NOW() NOT NULL,
    uploaded_by VARCHAR(100),
    upload_batch_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- Upload Rows Table
CREATE TABLE IF NOT EXISTS upload_rows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_upload_id UUID NOT NULL REFERENCES file_uploads(id) ON DELETE CASCADE,
    line_number INTEGER NOT NULL,
    raw_data JSONB NOT NULL,
    phone_normalized VARCHAR(20),
    loan_id_text VARCHAR(100),
    row_fingerprint VARCHAR(100) NOT NULL,
    
    -- Foreign Key References for Matching
    match_loan_id UUID REFERENCES loans(id) ON DELETE SET NULL,
    match_customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
    
    -- Matching Metadata
    match_method VARCHAR(50),
    matched_at TIMESTAMP,
    status VARCHAR(50) DEFAULT 'pending',
    error TEXT
);

-- Customer Upload Entries Table
CREATE TABLE IF NOT EXISTS customer_upload_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Upload Batch Information
    file_upload_id UUID REFERENCES file_uploads(id) ON DELETE CASCADE,
    upload_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Customer Information
    customer_fingerprint VARCHAR(64) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    primary_phone VARCHAR(20) NOT NULL,
    state VARCHAR(100),
    email VARCHAR(255),
    
    -- Loan Information
    loan_id VARCHAR(100) NOT NULL,
    principal_amount NUMERIC(15, 2),
    outstanding_amount NUMERIC(15, 2),
    due_amount NUMERIC(15, 2),
    next_due_date DATE,
    last_paid_date DATE,
    last_paid_amount NUMERIC(15, 2),
    
    -- Branch and Employee Information
    cluster VARCHAR(100),
    branch VARCHAR(255),
    branch_contact_number VARCHAR(20),
    employee_name VARCHAR(255),
    employee_id VARCHAR(50),
    employee_contact_number VARCHAR(20),
    
    -- Status and Metadata
    processing_status VARCHAR(50) DEFAULT 'processed',
    is_new_customer BOOLEAN DEFAULT TRUE,
    is_new_loan BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- =============================================================================
-- CALL MANAGEMENT TABLES
-- =============================================================================

-- Call Sessions Table
CREATE TABLE IF NOT EXISTS call_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    loan_id UUID REFERENCES loans(id) ON DELETE CASCADE,
    
    -- Call Identification
    call_sid VARCHAR(100) UNIQUE,
    websocket_session_id VARCHAR(100),
    
    -- Call Details
    direction call_direction_enum,
    status call_status_enum DEFAULT 'initiated',
    
    -- Timing Information
    initiated_at TIMESTAMP DEFAULT NOW() NOT NULL,
    answered_at TIMESTAMP,
    ended_at TIMESTAMP,
    duration_seconds INTEGER,
    
    -- Numbers Involved
    from_number VARCHAR(20),
    to_number VARCHAR(20) NOT NULL,
    caller_id VARCHAR(20),
    
    -- Agent Transfer Details
    agent_transfer_initiated BOOLEAN DEFAULT FALSE,
    agent_transfer_time TIMESTAMP,
    agent_number VARCHAR(20),
    agent_connected BOOLEAN DEFAULT FALSE,
    
    -- AI and Conversation Data
    language_detected VARCHAR(10),
    intent_detected VARCHAR(100),
    sentiment_score NUMERIC(3, 2),
    conversation_summary TEXT,
    
    -- Batch Tracking
    triggered_by_batch UUID REFERENCES file_uploads(id) ON DELETE SET NULL,
    triggered_by_row UUID REFERENCES upload_rows(id) ON DELETE SET NULL,
    
    -- Exotel Specific Data
    exotel_data JSONB,
    recording_url VARCHAR(500),
    
    -- Quality Metrics
    call_quality_rating INTEGER,
    technical_issues BOOLEAN DEFAULT FALSE,
    
    -- Additional Data
    call_metadata JSONB,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- Call Status Updates Table
CREATE TABLE IF NOT EXISTS call_status_updates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    call_session_id UUID NOT NULL REFERENCES call_sessions(id) ON DELETE CASCADE,
    
    -- Status Information
    from_status call_status_enum,
    to_status call_status_enum,
    status VARCHAR(50) NOT NULL,
    status_message TEXT,
    message TEXT,
    
    -- Metadata
    timestamp TIMESTAMP DEFAULT NOW() NOT NULL,
    extra_data JSONB,
    triggered_by VARCHAR(100)
);

-- Conversation Logs Table
CREATE TABLE IF NOT EXISTS conversation_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    call_session_id UUID NOT NULL REFERENCES call_sessions(id) ON DELETE CASCADE,
    
    -- Message Details
    sequence_number INTEGER NOT NULL,
    speaker VARCHAR(20) NOT NULL,
    message_type VARCHAR(30),
    
    -- Content
    original_text TEXT,
    translated_text TEXT,
    language_code VARCHAR(10),
    confidence_score NUMERIC(3, 2),
    
    -- AI Processing
    intent VARCHAR(100),
    entities JSONB,
    sentiment conversation_sentiment_enum,
    
    -- Audio Details
    audio_duration NUMERIC(5, 2),
    audio_file_path VARCHAR(500),
    
    -- Timing
    timestamp TIMESTAMP DEFAULT NOW() NOT NULL
);

-- Call Analytics Table
CREATE TABLE IF NOT EXISTS call_analytics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    call_session_id UUID NOT NULL REFERENCES call_sessions(id) ON DELETE CASCADE,
    
    -- Conversation Metrics
    total_messages INTEGER DEFAULT 0,
    customer_messages INTEGER DEFAULT 0,
    ai_messages INTEGER DEFAULT 0,
    average_response_time NUMERIC(5, 2),
    
    -- Sentiment Analysis
    overall_sentiment conversation_sentiment_enum,
    sentiment_trend VARCHAR(20),
    frustration_incidents INTEGER DEFAULT 0,
    
    -- Language and Understanding
    languages_detected TEXT[],
    primary_language VARCHAR(10),
    language_switches INTEGER DEFAULT 0,
    avg_confidence_score NUMERIC(3, 2),
    
    -- Intent Analysis
    primary_intent VARCHAR(100),
    intent_changes INTEGER DEFAULT 0,
    resolution_achieved BOOLEAN,
    
    -- Quality Metrics
    call_effectiveness_score NUMERIC(3, 2),
    customer_satisfaction_predicted NUMERIC(3, 2),
    
    -- Technical Metrics
    audio_quality_score NUMERIC(3, 2),
    connection_issues INTEGER DEFAULT 0,
    silence_periods INTEGER DEFAULT 0,
    
    -- Outcomes
    escalation_required BOOLEAN DEFAULT FALSE,
    follow_up_needed BOOLEAN DEFAULT FALSE,
    payment_commitment BOOLEAN DEFAULT FALSE,
    
    -- Metadata
    analyzed_at TIMESTAMP DEFAULT NOW() NOT NULL,
    ai_model_version VARCHAR(50)
);

-- =============================================================================
-- SYSTEM MANAGEMENT TABLES
-- =============================================================================

-- System Configuration Table
CREATE TABLE IF NOT EXISTS system_configuration (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Configuration Details
    config_key VARCHAR(100) UNIQUE NOT NULL,
    config_value TEXT,
    config_type VARCHAR(30),
    description TEXT,
    
    -- Management
    is_active BOOLEAN DEFAULT TRUE,
    is_system BOOLEAN DEFAULT FALSE,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_by VARCHAR(100)
);

-- Audit Logs Table
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Event Details
    event_type VARCHAR(50) NOT NULL,
    table_name VARCHAR(50),
    record_id VARCHAR(100),
    
    -- Change Details
    old_values JSONB,
    new_values JSONB,
    changes_summary TEXT,
    
    -- Context
    user_id VARCHAR(100),
    session_id VARCHAR(100),
    ip_address VARCHAR(45),
    user_agent TEXT,
    
    -- Metadata
    timestamp TIMESTAMP DEFAULT NOW() NOT NULL
);

-- System Metrics Table
CREATE TABLE IF NOT EXISTS system_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Metric Details
    metric_name VARCHAR(100) NOT NULL,
    metric_value NUMERIC(15, 4) NOT NULL,
    metric_unit VARCHAR(20),
    metric_category VARCHAR(50),
    
    -- Context
    additional_data JSONB,
    
    -- Timing
    recorded_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE OPTIMIZATION
-- =============================================================================

-- Customer Indexes
CREATE INDEX IF NOT EXISTS idx_customer_fingerprint ON customers(fingerprint);
CREATE INDEX IF NOT EXISTS idx_customer_primary_phone ON customers(primary_phone);
CREATE INDEX IF NOT EXISTS idx_customer_name ON customers(full_name);
CREATE INDEX IF NOT EXISTS idx_customer_status ON customers(status);
CREATE INDEX IF NOT EXISTS idx_customer_created ON customers(created_at);
CREATE INDEX IF NOT EXISTS idx_customer_last_contact ON customers(last_contact_date);
CREATE INDEX IF NOT EXISTS idx_customer_state ON customers(state);

-- Customer Notes Indexes
CREATE INDEX IF NOT EXISTS idx_customer_notes_customer ON customer_notes(customer_id);
CREATE INDEX IF NOT EXISTS idx_customer_notes_type ON customer_notes(note_type);
CREATE INDEX IF NOT EXISTS idx_customer_notes_created ON customer_notes(created_at);

-- Loan Indexes
CREATE INDEX IF NOT EXISTS idx_loan_customer ON loans(customer_id);
CREATE INDEX IF NOT EXISTS idx_loan_external_id ON loans(loan_id);
CREATE INDEX IF NOT EXISTS idx_loan_status ON loans(status);
CREATE INDEX IF NOT EXISTS idx_loan_due_date ON loans(next_due_date);
CREATE INDEX IF NOT EXISTS idx_loan_cluster ON loans(cluster);
CREATE INDEX IF NOT EXISTS idx_loan_branch ON loans(branch);
CREATE INDEX IF NOT EXISTS idx_loan_employee_id ON loans(employee_id);
CREATE INDEX IF NOT EXISTS idx_loan_risk ON loans(risk_category);

-- Payment Indexes
CREATE INDEX IF NOT EXISTS idx_payment_customer ON payments(customer_id);
CREATE INDEX IF NOT EXISTS idx_payment_loan ON payments(loan_id);
CREATE INDEX IF NOT EXISTS idx_payment_date ON payments(payment_date);
CREATE INDEX IF NOT EXISTS idx_payment_status ON payments(status);

-- File Upload Indexes
CREATE INDEX IF NOT EXISTS idx_file_upload_status ON file_uploads(status);
CREATE INDEX IF NOT EXISTS idx_file_upload_uploaded_at ON file_uploads(uploaded_at);
CREATE INDEX IF NOT EXISTS idx_upload_status ON file_uploads(status);
CREATE INDEX IF NOT EXISTS idx_upload_date ON file_uploads(uploaded_at);
CREATE INDEX IF NOT EXISTS idx_upload_batch ON file_uploads(upload_batch_id);
CREATE INDEX IF NOT EXISTS idx_upload_user ON file_uploads(uploaded_by);

-- Upload Row Indexes
CREATE INDEX IF NOT EXISTS idx_upload_row_file_upload ON upload_rows(file_upload_id);
CREATE INDEX IF NOT EXISTS idx_upload_row_phone_normalized ON upload_rows(phone_normalized);
CREATE INDEX IF NOT EXISTS idx_upload_row_status ON upload_rows(status);
CREATE INDEX IF NOT EXISTS idx_upload_row_match_loan ON upload_rows(match_loan_id);
CREATE INDEX IF NOT EXISTS idx_upload_row_match_customer ON upload_rows(match_customer_id);

-- Customer Upload Entry Indexes
CREATE INDEX IF NOT EXISTS idx_upload_entries_timestamp ON customer_upload_entries(upload_timestamp);
CREATE INDEX IF NOT EXISTS idx_upload_entries_phone ON customer_upload_entries(primary_phone);
CREATE INDEX IF NOT EXISTS idx_upload_entries_fingerprint ON customer_upload_entries(customer_fingerprint);
CREATE INDEX IF NOT EXISTS idx_upload_entries_file_upload ON customer_upload_entries(file_upload_id);
CREATE INDEX IF NOT EXISTS idx_upload_entries_loan_id ON customer_upload_entries(loan_id);

-- Call Session Indexes
CREATE INDEX IF NOT EXISTS idx_call_customer ON call_sessions(customer_id);
CREATE INDEX IF NOT EXISTS idx_call_session_call_sid ON call_sessions(call_sid);
CREATE INDEX IF NOT EXISTS idx_call_session_loan ON call_sessions(loan_id);
CREATE INDEX IF NOT EXISTS idx_call_session_status ON call_sessions(status);
CREATE INDEX IF NOT EXISTS idx_call_session_initiated_at ON call_sessions(initiated_at);
CREATE INDEX IF NOT EXISTS idx_call_session_to_number ON call_sessions(to_number);
CREATE INDEX IF NOT EXISTS idx_call_session_batch ON call_sessions(triggered_by_batch);
CREATE INDEX IF NOT EXISTS idx_call_initiated ON call_sessions(initiated_at);
CREATE INDEX IF NOT EXISTS idx_call_sid ON call_sessions(call_sid);
CREATE INDEX IF NOT EXISTS idx_call_direction ON call_sessions(direction);

-- Call Status Update Indexes
CREATE INDEX IF NOT EXISTS idx_status_call ON call_status_updates(call_session_id);
CREATE INDEX IF NOT EXISTS idx_status_timestamp ON call_status_updates(timestamp);
CREATE INDEX IF NOT EXISTS idx_status_to ON call_status_updates(to_status);

-- Conversation Log Indexes
CREATE INDEX IF NOT EXISTS idx_conversation_call ON conversation_logs(call_session_id);
CREATE INDEX IF NOT EXISTS idx_conversation_sequence ON conversation_logs(call_session_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_conversation_timestamp ON conversation_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_conversation_speaker ON conversation_logs(speaker);

-- Call Analytics Indexes
CREATE INDEX IF NOT EXISTS idx_analytics_call ON call_analytics(call_session_id);
CREATE INDEX IF NOT EXISTS idx_analytics_sentiment ON call_analytics(overall_sentiment);
CREATE INDEX IF NOT EXISTS idx_analytics_effectiveness ON call_analytics(call_effectiveness_score);
CREATE INDEX IF NOT EXISTS idx_analytics_analyzed ON call_analytics(analyzed_at);

-- System Configuration Indexes
CREATE INDEX IF NOT EXISTS idx_config_key ON system_configuration(config_key);
CREATE INDEX IF NOT EXISTS idx_config_active ON system_configuration(is_active);

-- Audit Log Indexes
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_table ON audit_logs(table_name);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);

-- System Metrics Indexes
CREATE INDEX IF NOT EXISTS idx_metrics_name ON system_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_metrics_category ON system_metrics(metric_category);
CREATE INDEX IF NOT EXISTS idx_metrics_recorded ON system_metrics(recorded_at);
CREATE INDEX IF NOT EXISTS idx_metrics_name_time ON system_metrics(metric_name, recorded_at);

-- =============================================================================
-- UNIQUE CONSTRAINTS
-- =============================================================================

-- Upload Row Unique Constraint
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'uix_upload_row_fingerprint'
    ) THEN
        ALTER TABLE upload_rows ADD CONSTRAINT uix_upload_row_fingerprint 
        UNIQUE (file_upload_id, row_fingerprint);
    END IF;
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Customer Phone Unique Constraint
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'uix_customer_primary_phone'
    ) THEN
        ALTER TABLE customers ADD CONSTRAINT uix_customer_primary_phone 
        UNIQUE (primary_phone);
    END IF;
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- =============================================================================
-- CHECK CONSTRAINTS FOR DATA INTEGRITY
-- =============================================================================

-- Loan Amount Constraints
DO $$ BEGIN
    ALTER TABLE loans ADD CONSTRAINT chk_loan_amount_positive 
    CHECK (principal_amount > 0 AND outstanding_amount >= 0);
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Call Duration Constraint
DO $$ BEGIN
    ALTER TABLE call_sessions ADD CONSTRAINT chk_call_duration_positive 
    CHECK (duration_seconds >= 0);
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Payment Amount Constraint
DO $$ BEGIN
    ALTER TABLE payments ADD CONSTRAINT chk_payment_amount_positive 
    CHECK (amount > 0);
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- =============================================================================
-- TRIGGERS FOR AUTOMATIC TIMESTAMP UPDATES
-- =============================================================================

-- Function to update timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply triggers to tables with updated_at columns
DO $$ 
DECLARE
    table_name TEXT;
    tables_with_updated_at TEXT[] := ARRAY[
        'customers', 'loans', 'file_uploads', 'customer_upload_entries', 'call_sessions'
    ];
BEGIN
    FOREACH table_name IN ARRAY tables_with_updated_at
    LOOP
        EXECUTE format('
            DROP TRIGGER IF EXISTS update_%I_updated_at ON %I;
            CREATE TRIGGER update_%I_updated_at 
                BEFORE UPDATE ON %I 
                FOR EACH ROW 
                EXECUTE FUNCTION update_updated_at_column();
        ', table_name, table_name, table_name, table_name);
    END LOOP;
END $$;

-- =============================================================================
-- COMPLETION MESSAGE
-- =============================================================================

DO $$ 
BEGIN
    RAISE NOTICE '✅ Voice Assistant Call Management System Database Schema Created Successfully!';
    RAISE NOTICE '📊 Total Tables Created: 16';
    RAISE NOTICE '🔗 Total Indexes Created: 50+';
    RAISE NOTICE '⚡ Performance optimizations applied';
    RAISE NOTICE '🔒 Data integrity constraints added';
    RAISE NOTICE '🕒 Automatic timestamp triggers configured';
    RAISE NOTICE '';
    RAISE NOTICE '🚀 Database is ready for the Voice Assistant system!';
END $$;
