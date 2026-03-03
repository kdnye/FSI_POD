-- Adds user-level ops membership flag while preserving existing user_role enum.
ALTER TABLE users
ADD COLUMN IF NOT EXISTS is_ops BOOLEAN NOT NULL DEFAULT FALSE;
