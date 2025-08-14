-- Basic schema for MVP testing
-- Run this after creating the database

-- Create user and database
-- Run these commands as postgres superuser:
-- CREATE USER sports_user WITH PASSWORD 'sports_pass';
-- CREATE DATABASE sports_betting_ai OWNER sports_user;
-- GRANT ALL PRIVILEGES ON DATABASE sports_betting_ai TO sports_user;

-- Connect to sports_betting_ai database and run the rest:

CREATE TABLE IF NOT EXISTS sports (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    season_type VARCHAR(20) NOT NULL DEFAULT 'regular',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS teams (
    id SERIAL PRIMARY KEY,
    sport_id INTEGER REFERENCES sports(id),
    external_id VARCHAR(50) UNIQUE,
    name VARCHAR(100) NOT NULL,
    abbreviation VARCHAR(10),
    city VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS games (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(50) UNIQUE,
    sport_id INTEGER REFERENCES sports(id),
    home_team_id INTEGER REFERENCES teams(id),
    away_team_id INTEGER REFERENCES teams(id),
    game_date TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'scheduled',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insert test data
INSERT INTO sports (name, season_type) VALUES 
('NFL', 'regular'),
('MLB', 'regular'),
('NBA', 'regular')
ON CONFLICT DO NOTHING;

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date);
CREATE INDEX IF NOT EXISTS idx_teams_sport ON teams(sport_id);