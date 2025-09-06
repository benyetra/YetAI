-- Create comprehensive player ID mapping table for multiple platforms
-- This table will be the central source of truth for player ID mappings across all data sources

CREATE TABLE IF NOT EXISTS player_id_mappings (
    id SERIAL PRIMARY KEY,
    
    -- Internal YetAI ID (our primary key reference)
    yetai_id INTEGER NOT NULL REFERENCES fantasy_players(id) ON DELETE CASCADE,
    
    -- External Platform IDs
    sleeper_id VARCHAR(50),           -- Sleeper Fantasy ID (e.g., '4866')
    espn_id VARCHAR(50),              -- ESPN Player ID
    yahoo_id VARCHAR(50),             -- Yahoo Fantasy ID
    draftkings_id VARCHAR(50),        -- DraftKings ID
    fanduel_id VARCHAR(50),           -- FanDuel ID
    nfl_id VARCHAR(50),               -- Official NFL ID
    pfr_id VARCHAR(50),               -- Pro Football Reference ID
    rotowire_id VARCHAR(50),          -- Rotowire ID
    numberfire_id VARCHAR(50),        -- NumberFire ID
    sportradar_id VARCHAR(50),        -- SportRadar ID
    
    -- Player identifiers for matching
    full_name VARCHAR(255) NOT NULL,   -- Player's full name for fuzzy matching
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    suffix VARCHAR(10),                -- Jr., Sr., III, etc.
    
    -- Additional matching fields
    birth_date DATE,                   -- For exact matching
    college VARCHAR(100),              -- College attended
    draft_year INTEGER,                -- NFL draft year
    draft_round INTEGER,               -- Draft round
    draft_pick INTEGER,                -- Draft pick number
    
    -- Position and team (current)
    position VARCHAR(10),              -- QB, RB, WR, TE, etc.
    team VARCHAR(10),                  -- Current team abbreviation
    jersey_number INTEGER,             -- Current jersey number
    
    -- Status flags
    is_active BOOLEAN DEFAULT true,    -- Currently active in NFL
    is_rookie BOOLEAN DEFAULT false,   -- First year player
    is_verified BOOLEAN DEFAULT false, -- Manually verified mapping
    confidence_score FLOAT DEFAULT 0.0,-- Confidence in the mapping (0-1)
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_sync_at TIMESTAMP,           -- Last time we synced data for this player
    notes TEXT                         -- Any manual notes about the mapping
);

-- Create indexes for fast lookups
CREATE INDEX idx_player_mapping_yetai ON player_id_mappings(yetai_id);
CREATE INDEX idx_player_mapping_sleeper ON player_id_mappings(sleeper_id);
CREATE INDEX idx_player_mapping_espn ON player_id_mappings(espn_id);
CREATE INDEX idx_player_mapping_yahoo ON player_id_mappings(yahoo_id);
CREATE INDEX idx_player_mapping_draftkings ON player_id_mappings(draftkings_id);
CREATE INDEX idx_player_mapping_fanduel ON player_id_mappings(fanduel_id);
CREATE INDEX idx_player_mapping_nfl ON player_id_mappings(nfl_id);
CREATE INDEX idx_player_mapping_name ON player_id_mappings(full_name);
CREATE INDEX idx_player_mapping_team_pos ON player_id_mappings(team, position);

-- Create unique constraint to prevent duplicate mappings
CREATE UNIQUE INDEX idx_unique_yetai_id ON player_id_mappings(yetai_id);

-- Add comments for documentation
COMMENT ON TABLE player_id_mappings IS 'Central mapping table for player IDs across all platforms';
COMMENT ON COLUMN player_id_mappings.yetai_id IS 'Internal YetAI player ID from fantasy_players table';
COMMENT ON COLUMN player_id_mappings.sleeper_id IS 'Sleeper Fantasy platform player ID';
COMMENT ON COLUMN player_id_mappings.espn_id IS 'ESPN Fantasy platform player ID';
COMMENT ON COLUMN player_id_mappings.confidence_score IS 'Confidence score for the mapping (0-1), 1 being manually verified';

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_player_mapping_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update timestamp
CREATE TRIGGER update_player_mapping_timestamp
BEFORE UPDATE ON player_id_mappings
FOR EACH ROW
EXECUTE FUNCTION update_player_mapping_timestamp();