-- ============================================
-- OpenClaw Sandbox RPG - Database Initialization
-- ============================================
-- This script runs once on first PostgreSQL container startup
-- ============================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- ============================================
-- Schema will be managed by Alembic migrations
-- (see backend/models/ and backend/migrations/)
-- ============================================

-- This file is intentionally minimal
-- Tables will be created by the backend application
-- on first startup via SQLAlchemy/Alembic

SELECT 'Database initialized. Run backend to create tables.' AS status;
