-- Create player_analytics table manually
CREATE TABLE IF NOT EXISTS player_analytics (
    id SERIAL PRIMARY KEY,
    player_id INTEGER NOT NULL,
    week INTEGER NOT NULL,
    season INTEGER NOT NULL,
    game_date TIMESTAMP,
    opponent VARCHAR(10),

    -- Snap Count Analytics
    total_snaps INTEGER,
    offensive_snaps INTEGER,
    special_teams_snaps INTEGER,
    snap_percentage FLOAT,
    snap_share_rank INTEGER,

    -- Target Share Analytics
    targets INTEGER DEFAULT 0,
    team_total_targets INTEGER,
    target_share FLOAT,
    air_yards INTEGER,
    air_yards_share FLOAT,
    average_depth_of_target FLOAT,
    target_separation FLOAT,

    -- Red Zone Usage
    red_zone_snaps INTEGER DEFAULT 0,
    red_zone_targets INTEGER DEFAULT 0,
    red_zone_carries INTEGER DEFAULT 0,
    red_zone_touches INTEGER DEFAULT 0,
    red_zone_share FLOAT,
    red_zone_efficiency FLOAT,

    -- Route Running
    routes_run INTEGER DEFAULT 0,
    route_participation FLOAT,
    slot_rate FLOAT,
    deep_target_rate FLOAT,

    -- Rushing Usage
    carries INTEGER DEFAULT 0,
    rushing_yards INTEGER DEFAULT 0,
    goal_line_carries INTEGER DEFAULT 0,
    carry_share FLOAT,
    yards_before_contact FLOAT,
    yards_after_contact FLOAT,
    broken_tackles INTEGER DEFAULT 0,

    -- Receiving Production
    receptions INTEGER DEFAULT 0,
    receiving_yards INTEGER DEFAULT 0,
    yards_after_catch INTEGER,
    yards_after_catch_per_reception FLOAT,
    contested_catch_rate FLOAT,
    drop_rate FLOAT,

    -- Game Context
    team_pass_attempts INTEGER,
    team_rush_attempts INTEGER,
    team_red_zone_attempts INTEGER,
    game_script FLOAT,
    time_of_possession FLOAT,

    -- Advanced Efficiency Metrics
    ppr_points FLOAT,
    half_ppr_points FLOAT,
    standard_points FLOAT,
    points_per_snap FLOAT,
    points_per_target FLOAT,
    points_per_touch FLOAT,

    -- Consistency Metrics
    boom_rate FLOAT,
    bust_rate FLOAT,
    weekly_variance FLOAT,
    floor_score FLOAT,
    ceiling_score FLOAT,

    -- Injury/Availability
    injury_designation VARCHAR(20),
    snaps_missed_injury INTEGER DEFAULT 0,
    games_missed_season INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT fk_player_analytics_player_id FOREIGN KEY (player_id) REFERENCES fantasy_players(id)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_player_analytics_player_week ON player_analytics(player_id, week, season);
CREATE INDEX IF NOT EXISTS idx_player_analytics_snap_share ON player_analytics(player_id, snap_percentage);
CREATE INDEX IF NOT EXISTS idx_player_analytics_target_share ON player_analytics(player_id, target_share);

-- Create player_trends table
CREATE TABLE IF NOT EXISTS player_trends (
    id SERIAL PRIMARY KEY,
    player_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    trend_type VARCHAR(50) NOT NULL,
    period_start INTEGER,
    period_end INTEGER,

    -- Usage Trends
    snap_share_trend FLOAT,
    target_share_trend FLOAT,
    red_zone_usage_trend FLOAT,
    carry_share_trend FLOAT,

    -- Performance Trends
    fantasy_points_trend FLOAT,
    efficiency_trend FLOAT,
    consistency_trend FLOAT,

    -- Context Changes
    role_change_indicator BOOLEAN DEFAULT FALSE,
    role_change_description VARCHAR(500),
    opportunity_change_score FLOAT,

    -- Predictive Metrics
    momentum_score FLOAT,
    sustainability_score FLOAT,
    buy_low_indicator BOOLEAN DEFAULT FALSE,
    sell_high_indicator BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT fk_player_trends_player_id FOREIGN KEY (player_id) REFERENCES fantasy_players(id)
);

-- Create index for player_trends
CREATE INDEX IF NOT EXISTS idx_player_trends_player_season ON player_trends(player_id, season);