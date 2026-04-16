-- ============================================================
-- Migration: Remove client_type from api_key_entries
--
-- Goal: API Keys no longer have a client_type attribute.
--       Service type is determined by which Pool the Key belongs to.
--       Association is managed through pool_members table.
--
-- Before:  api_key_entries.client_type = "ethereum-rpc" (confusing)
-- After:   api_key_entries has NO client_type column
--          key_pools.client_type = "ethereum-rpc" (pool-level metadata)
--          pool_members links keys ↔ pools (existing, unchanged)
-- ============================================================

BEGIN TRANSACTION;

-- 1. Backup current data for safety
CREATE TABLE IF NOT EXISTS _bak_api_key_entries AS SELECT * FROM api_key_entries;
-- 2. Remove client_type column from api_key_entries
ALTER TABLE api_key_entries DROP COLUMN IF EXISTS client_type;

COMMIT;

-- Verification queries:
-- SELECT name FROM sqlite_master WHERE type='table' AND name='api_key_entries';
-- PRAGMA table_info(api_key_entries);
