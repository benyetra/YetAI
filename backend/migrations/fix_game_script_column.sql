-- Fix game_script column to be VARCHAR instead of double precision
-- This column should store game context like 'neutral', 'winning', 'losing'

ALTER TABLE player_analytics 
ALTER COLUMN game_script TYPE VARCHAR(20) 
USING CASE 
    WHEN game_script IS NULL THEN NULL
    WHEN game_script = 0 THEN 'neutral'
    WHEN game_script > 0 THEN 'winning'
    WHEN game_script < 0 THEN 'losing'
    ELSE 'neutral'
END;

-- Add comment for documentation
COMMENT ON COLUMN player_analytics.game_script IS 'Game script context: neutral, winning, losing, blowout_win, blowout_loss, comeback, etc.';