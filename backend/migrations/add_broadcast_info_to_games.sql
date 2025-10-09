-- Add broadcast_info and is_nationally_televised columns to games table
-- Migration created: 2025-10-09

ALTER TABLE games
ADD COLUMN IF NOT EXISTS broadcast_info JSONB,
ADD COLUMN IF NOT EXISTS is_nationally_televised BOOLEAN DEFAULT FALSE;

-- Create index on is_nationally_televised for faster queries
CREATE INDEX IF NOT EXISTS idx_games_nationally_televised
ON games(is_nationally_televised)
WHERE is_nationally_televised = TRUE;

-- Create index on commence_time for today's games queries
CREATE INDEX IF NOT EXISTS idx_games_commence_time
ON games(commence_time);
