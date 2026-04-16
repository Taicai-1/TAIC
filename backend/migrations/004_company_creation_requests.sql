-- ============================================================================
-- Migration 004 - Add company_creation_requests table
-- ============================================================================
--
-- Stores user requests to create a new organization, pending manual approval
-- by an administrator (default: jeremy@taic.co). Linked to companies when
-- approved via company_id (nullable until decision).
--
-- This migration is idempotent: safe to re-run.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS company_creation_requests (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    requested_name   VARCHAR(200) NOT NULL,
    status           VARCHAR(20) NOT NULL DEFAULT 'pending',
    token            VARCHAR(128) NOT NULL UNIQUE,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    decided_at       TIMESTAMP,
    decided_reason   TEXT,
    company_id       INTEGER REFERENCES companies(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_ccr_user_id ON company_creation_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_ccr_token ON company_creation_requests(token);
CREATE INDEX IF NOT EXISTS idx_ccr_status ON company_creation_requests(status);

COMMIT;

-- ============================================================================
-- VERIFICATION:
--   SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--   WHERE table_name = 'company_creation_requests';
-- ============================================================================
