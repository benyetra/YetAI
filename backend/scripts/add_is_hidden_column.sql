-- Manual SQL script to add is_hidden column to users table
-- Run this if automatic migration fails
-- Usage: Connect to your Railway PostgreSQL database and run this script

-- Add is_hidden column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'users'
        AND column_name = 'is_hidden'
    ) THEN
        ALTER TABLE users ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT false;
        RAISE NOTICE 'Column is_hidden added to users table';
    ELSE
        RAISE NOTICE 'Column is_hidden already exists in users table';
    END IF;
END $$;

-- Verify the column was added
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'users' AND column_name = 'is_hidden';
