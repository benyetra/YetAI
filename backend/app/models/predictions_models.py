"""
YetiBets prediction models ported to pure SQLAlchemy.
Source: YetiBets/database/models.py — mechanical port per YETIBETS_YETAI_MERGE.md.
Tables are prefixed with `pred_` to keep the predictions namespace clean.
This module is intentionally NOT imported by app/main.py yet; that wiring lands
with the alembic baseline migration (Development-b0j).
"""

from datetime import datetime, date
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class HistoricalPitcherStats(Base):
    __tablename__ = "pred_historical_pitcher_stats"
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    pitch_hand = Column(String, nullable=False)
    season = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    strikeouts = Column(Integer, nullable=False)
    innings_pitched = Column(Float, nullable=False)
    opponent_team = Column(String, nullable=False)
    at_bats = Column(Integer, nullable=False)
    walks = Column(Integer, nullable=False)
    hits = Column(Integer, nullable=False)
    baseOnBalls = Column(Integer, nullable=False)
    whip = Column(Float, nullable=False)
    numberOfPitches = Column(Integer, nullable=False)


class Pitcher(Base):
    __tablename__ = "pred_pitcher"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False)
    pitch_hand = Column(String(8), nullable=False)
    team = Column(String(64), nullable=False)
    opponent = Column(String(64), nullable=False)
    game_time = Column(DateTime, nullable=False)
    venue_name = Column(String(64), nullable=False)
    k_per_9 = Column(Float, nullable=False)
    last_5_avg_k_per_9 = Column(Float, nullable=False)
    opponent_k_rate = Column(Float, nullable=False)
    combined_score = Column(Float, nullable=False)
    fanduel_point = Column(Float, nullable=False)
    fanduel_price = Column(Float, nullable=False)
    fanduel_flag = Column(String(1), nullable=False, default="n")
    game_status = Column(String(32), nullable=False)
    pitcher_id = Column(String(64), nullable=False)
    projected_strikeouts = Column(Float, nullable=False)
    projected_innings = Column(Float, nullable=False)
    projected_at_bats = Column(Float, nullable=False)
    game_id = Column(Integer, nullable=False)


class Homer(Base):
    __tablename__ = "pred_homer"
    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String(50), nullable=False)
    player_name = Column(String(100), nullable=False)
    team = Column(String(50), nullable=False)
    opponent = Column(String(50), nullable=False)
    opponent_pitcher = Column(String(100), nullable=False)
    opponent_pitcher_hand = Column(String(10), nullable=False)
    game_time = Column(DateTime, nullable=False)
    venue_name = Column(String(50), nullable=False)
    hits_last_10_games = Column(Integer, nullable=False)
    batting_average_vs_handedness = Column(Float, nullable=False)
    batting_average_vs_pitcher = Column(Float, nullable=False)
    hits_vs_pitcher = Column(Integer, nullable=False)
    at_bats_vs_pitcher = Column(Integer, nullable=False)
    home_runs_last_10_games = Column(Integer, nullable=False)
    homer_score = Column(Float, nullable=True)
    game_id = Column(Integer, nullable=False)


class Hitter(Base):
    __tablename__ = "pred_hitter"
    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String(50), nullable=False)
    player_name = Column(String(100), nullable=False)
    team = Column(String(50), nullable=False)
    opponent = Column(String(50), nullable=False)
    opponent_pitcher = Column(String(100), nullable=False)
    opponent_pitcher_hand = Column(String(10), nullable=False)
    game_time = Column(DateTime, nullable=False)
    venue_name = Column(String(50), nullable=False)
    hits_last_10_games = Column(Integer, nullable=False)
    batting_average_vs_handedness = Column(Float, nullable=False)
    batting_average_vs_pitcher = Column(Float, nullable=False)
    hits_vs_pitcher = Column(Integer, nullable=False)
    at_bats_vs_pitcher = Column(Integer, nullable=False)
    combined_score = Column(Float, nullable=False)
    game_id = Column(Integer, nullable=False)

    def __repr__(self):
        return f"<BatterStats {self.player_name}>"


class Weather(Base):
    __tablename__ = "pred_weather"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stadium = Column(String(100), nullable=False)
    game_time = Column(DateTime, nullable=False)
    weather_code = Column(String(50), nullable=False)
    temperature = Column(Float, nullable=False)
    wind_speed = Column(Float, nullable=False)
    wind_direction = Column(String(10), nullable=False)
    humidity = Column(Float, nullable=False)
    venue_name = Column(String(100), nullable=False)
    precipitation_probability = Column(Float, nullable=False)
    rain_intensity = Column(Float, nullable=False)


class NFLTeam(Base):
    __tablename__ = "pred_nfl_team"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, unique=True, nullable=False)
    name = Column(String(50), nullable=False)
    location = Column(String(50), nullable=False)

    def __repr__(self):
        return f"<NFLTeam {self.name}>"


class Kickers(Base):
    __tablename__ = "pred_kickers"
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, unique=True, nullable=False)
    name = Column(String, nullable=False)
    team_id = Column(Integer, nullable=False)
    team_name = Column(String, nullable=False)
    venue_name = Column(String, nullable=False)
    opponent_team_name = Column(String, nullable=False)
    team_red_zone_efficiency = Column(Float, nullable=True)
    opponent_red_zone_efficiency = Column(Float, nullable=True)
    third_down_conversion_rate = Column(Float, nullable=True)
    redzone_touchdown_pct = Column(Float, nullable=True)
    redzone_field_goal_pct = Column(Float, nullable=True)
    career_surface_stats = Column(JSON, nullable=True)
    career_location_stats = Column(JSON, nullable=True)
    career_field_position_stats = Column(JSON, nullable=True)
    game_time = Column(DateTime, nullable=False)
    game_stats = Column(JSON, nullable=True)
    projected_field_goals = Column(Float, nullable=True)
    # Weather and venue information
    temperature = Column(Float, nullable=True)
    wind_speed = Column(Float, nullable=True)
    weather_conditions = Column(String, nullable=True)
    venue_type = Column(String, nullable=True)  # dome/outdoor
    surface_type = Column(String, nullable=True)  # grass/turf


class KickerActuals(Base):
    __tablename__ = "pred_kicker_actuals"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    kicker_id = Column(String, nullable=False)
    kicker_name = Column(String, nullable=True)
    team_name = Column(String, nullable=True)
    opponent_name = Column(String, nullable=True)
    venue_name = Column(String, nullable=True)
    # Actual performance
    actual_field_goals_made = Column(Integer, nullable=False)
    actual_field_goals_attempted = Column(Integer, nullable=False)
    actual_longest_fg = Column(Integer, nullable=True)
    # Weather conditions during game
    game_temperature = Column(Float, nullable=True)
    game_wind_speed = Column(Float, nullable=True)
    # Projected performance (from our predictions)
    projected_field_goals = Column(Float, nullable=False)
    # Results analysis
    hit_over_1_5 = Column(Boolean, nullable=True)  # Did they make 2+ FGs?
    correct_prediction = Column(Boolean, nullable=True)  # Did our prediction match?
    prediction_confidence = Column(Float, nullable=True)  # How confident were we?


class FieldGoalAttempt(Base):
    __tablename__ = "pred_field_goal_attempts"
    id = Column(Integer, primary_key=True)
    game_id = Column(String(50), nullable=False)
    play_id = Column(Float, nullable=True)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    game_date = Column(Date, nullable=False)
    posteam = Column(String(10), nullable=False)
    defteam = Column(String(10), nullable=False)
    kicker_player_name = Column(String(100), nullable=False)
    kicker_player_id = Column(String(20), nullable=False)
    field_goal_result = Column(String(20), nullable=False)
    kick_distance = Column(Float, nullable=False)
    score_differential = Column(Float, nullable=True)
    qtr = Column(Float, nullable=True)
    down = Column(Float, nullable=True)
    ydstogo = Column(Float, nullable=True)
    yardline_100 = Column(Float, nullable=True)
    game_seconds_remaining = Column(Float, nullable=True)
    home_team = Column(String(10), nullable=True)
    away_team = Column(String(10), nullable=True)
    weather = Column(Text, nullable=True)
    temp = Column(Float, nullable=True)
    wind = Column(Float, nullable=True)
    roof = Column(String(20), nullable=True)
    surface = Column(String(30), nullable=True)
    stadium = Column(String(100), nullable=True)
    stadium_id = Column(String(20), nullable=True)
    season_type = Column(String(10), nullable=True)
    wp = Column(Float, nullable=True)
    wpa = Column(Float, nullable=True)
    home_wp = Column(Float, nullable=True)
    away_wp = Column(Float, nullable=True)
    is_made = Column(Integer, nullable=False)
    is_missed = Column(Integer, nullable=False)
    is_blocked = Column(Integer, nullable=False)
    distance_band = Column(String(10), nullable=True)
    is_clutch = Column(Integer, nullable=False)
    is_game_winning = Column(Integer, nullable=False)


class KickerPerformanceMetrics(Base):
    __tablename__ = "pred_kicker_performance_metrics"
    id = Column(Integer, primary_key=True)
    kicker_player_id = Column(String(20), nullable=False)
    kicker_player_name = Column(String(100), nullable=False)
    total_attempts = Column(Integer, nullable=False)
    total_made = Column(Integer, nullable=False)
    fg_percentage = Column(Float, nullable=False)
    avg_distance = Column(Float, nullable=False)
    max_distance = Column(Float, nullable=False)
    clutch_attempts = Column(Integer, nullable=False)
    game_winning_attempts = Column(Integer, nullable=False)
    # Distance-specific stats
    under_30_attempts = Column(Integer, nullable=False, default=0)
    under_30_made = Column(Integer, nullable=False, default=0)
    thirty_39_attempts = Column(Integer, nullable=False, default=0)
    thirty_39_made = Column(Integer, nullable=False, default=0)
    forty_49_attempts = Column(Integer, nullable=False, default=0)
    forty_49_made = Column(Integer, nullable=False, default=0)
    fifty_59_attempts = Column(Integer, nullable=False, default=0)
    fifty_59_made = Column(Integer, nullable=False, default=0)
    sixty_plus_attempts = Column(Integer, nullable=False, default=0)
    sixty_plus_made = Column(Integer, nullable=False, default=0)
    # Weather performance
    cold_weather_attempts = Column(Integer, nullable=False, default=0)
    cold_weather_made = Column(Integer, nullable=False, default=0)
    windy_attempts = Column(Integer, nullable=False, default=0)
    windy_made = Column(Integer, nullable=False, default=0)
    dome_attempts = Column(Integer, nullable=False, default=0)
    dome_made = Column(Integer, nullable=False, default=0)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)


class WeatherImpactMetrics(Base):
    __tablename__ = "pred_weather_impact_metrics"
    id = Column(Integer, primary_key=True)
    temp_band = Column(String(20), nullable=True)
    wind_band = Column(String(20), nullable=True)
    total_attempts = Column(Integer, nullable=False)
    total_made = Column(Integer, nullable=False)
    success_rate = Column(Float, nullable=False)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)


class KickerPredictions(Base):
    __tablename__ = "pred_kicker_predictions"
    id = Column(Integer, primary_key=True)
    kicker_player_id = Column(String(20), nullable=False)
    kicker_player_name = Column(String(100), nullable=False)
    team_id = Column(Integer, nullable=False)
    team_name = Column(String, nullable=False)
    opponent_team_name = Column(String, nullable=False)
    game_date = Column(DateTime, nullable=False)
    venue_name = Column(String, nullable=False)
    # Enhanced predictions
    predicted_fg_attempts = Column(Float, nullable=False)
    predicted_fg_made = Column(Float, nullable=False)
    predicted_success_rate = Column(Float, nullable=False)
    # Distance-specific predictions
    short_distance_prob = Column(Float, nullable=True)  # <30 yards
    medium_distance_prob = Column(Float, nullable=True)  # 30-49 yards
    long_distance_prob = Column(Float, nullable=True)  # 50+ yards
    # Situational predictions
    clutch_situation_prob = Column(Float, nullable=True)
    weather_adjusted_prob = Column(Float, nullable=True)
    # Model confidence and features
    model_confidence = Column(Float, nullable=True)
    feature_importance = Column(JSON, nullable=True)
    prediction_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Weather conditions
    temperature = Column(Float, nullable=True)
    wind_speed = Column(Float, nullable=True)
    roof_type = Column(String(20), nullable=True)
    surface_type = Column(String(30), nullable=True)

    def __init__(
        self,
        kicker_player_id,
        kicker_player_name,
        team_id,
        team_name,
        venue_name,
        opponent_team_name,
        game_date,
        predicted_fg_attempts,
        predicted_fg_made,
        predicted_success_rate,
    ):
        self.kicker_player_id = kicker_player_id
        self.kicker_player_name = kicker_player_name
        self.team_id = team_id
        self.team_name = team_name
        self.venue_name = venue_name
        self.opponent_team_name = opponent_team_name
        self.game_date = game_date
        self.predicted_fg_attempts = predicted_fg_attempts
        self.predicted_fg_made = predicted_fg_made
        self.predicted_success_rate = predicted_success_rate


class TeamStats(Base):
    __tablename__ = "pred_team_stats"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, unique=True, nullable=False)
    red_zone_efficiency = Column(Float, nullable=False)
    opponent_red_zone_efficiency = Column(Float, nullable=False)
    fg_given_up = Column(Float, nullable=False)
    third_down_conversion_rate = Column(Float, nullable=False)


class NFLWeather(Base):
    __tablename__ = "pred_nfl_weather"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stadium = Column(String(100), nullable=False)
    game_time = Column(DateTime, nullable=False)
    weather_code = Column(String(50), nullable=False)
    temperature = Column(Float, nullable=False)
    wind_speed = Column(Float, nullable=False)
    wind_direction = Column(String(10), nullable=False)
    humidity = Column(Float, nullable=False)
    venue_name = Column(String(100), nullable=False)
    precipitation_probability = Column(Float, nullable=False)
    rain_intensity = Column(Float, nullable=False)


class StrikeoutProjections(Base):
    __tablename__ = "pred_strikeout_projections"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    pitcher_id = Column(String, nullable=False)
    pitcher_name = Column(String, nullable=True)
    projected_strikeouts = Column(Float, nullable=False)
    projected_innings_pitched = Column(Float, nullable=False)
    projected_at_bats = Column(Float, nullable=False)
    fanduel_line = Column(Float, nullable=True)
    fanduel_over_under = Column(String(7), nullable=True)
    park_id = Column(String, nullable=True)


class StrikeoutActuals(Base):
    __tablename__ = "pred_strikeout_actuals"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    pitcher_id = Column(String, nullable=False)
    pitcher_name = Column(String, nullable=True)
    actual_strikeouts = Column(Float, nullable=False)
    actual_innings_pitched = Column(Float, nullable=False)
    actual_at_bats = Column(Float, nullable=False)
    projected_strikeouts = Column(Float, nullable=False)
    projected_innings_pitched = Column(Float, nullable=False)
    projected_at_bats = Column(Float, nullable=False)
    correct_prediction = Column(Boolean, nullable=True)
    park_id = Column(String, nullable=True)


class ProjectedHits(Base):
    __tablename__ = "pred_projected_hits"
    id = Column(Integer, primary_key=True)
    batter_id = Column(Integer, nullable=False)
    batter_name = Column(String(100), nullable=False)
    date = Column(Date, nullable=False)
    projected_hits = Column(Integer, nullable=False)
    actual_hits = Column(Integer, default=0)


class ProjectedHomers(Base):
    __tablename__ = "pred_projected_homers"
    id = Column(Integer, primary_key=True)
    batter_id = Column(Integer, nullable=False)
    batter_name = Column(String(100), nullable=False)
    date = Column(Date, nullable=False)
    projected_homers = Column(Integer, nullable=False)
    actual_homers = Column(Integer, default=0)


class HitActuals(Base):
    __tablename__ = "pred_hit_actuals"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    batter_id = Column(String, nullable=False)
    batter_name = Column(String, nullable=True)
    actual_hits = Column(Integer, nullable=False)
    projected_hits = Column(Integer, nullable=False)
    correct_prediction = Column(Boolean, nullable=True)


class HomerActuals(Base):
    __tablename__ = "pred_homer_actuals"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    batter_id = Column(String, nullable=False)
    batter_name = Column(String, nullable=True)
    actual_homers = Column(Integer, nullable=False)
    projected_homers = Column(Integer, nullable=False)
    correct_prediction = Column(Boolean, nullable=True)


class BlowoutChances(Base):
    __tablename__ = "pred_blowout_chances"
    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, nullable=False)
    home_team = Column(String(100), nullable=False)
    away_team = Column(String(100), nullable=False)
    home_expected_runs = Column(Float, nullable=False)
    away_expected_runs = Column(Float, nullable=False)
    home_pitcher_effectiveness = Column(Float, nullable=False)
    away_pitcher_effectiveness = Column(Float, nullable=False)
    run_differential = Column(Float, nullable=False)
    blowout_team = Column(String(10), nullable=False)


class Quarterbacks(Base):
    __tablename__ = "pred_quarterbacks"
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, unique=True, nullable=False)
    name = Column(String, nullable=False)
    team_id = Column(Integer, nullable=False)
    team_name = Column(String, nullable=False)
    venue_name = Column(String, nullable=False)
    opponent_team_name = Column(String, nullable=False)
    game_time = Column(DateTime, nullable=False)
    fanduel_price = Column(Float, nullable=True)
    fanduel_point = Column(Float, nullable=True)
    fanduel_flag = Column(String(1), nullable=True, default="n")

    # Season stats
    season_passing_yards = Column(Float, nullable=True)
    completion_pct = Column(Float, nullable=True)
    completions = Column(Integer, nullable=True)
    ESPN_qbr = Column(Float, nullable=True)
    interception_pct = Column(Float, nullable=True)
    interceptions = Column(Integer, nullable=True)
    passing_attempts = Column(Integer, nullable=True)
    passing_td_pct = Column(Float, nullable=True)
    passing_touchdowns = Column(Integer, nullable=True)
    passing_yards = Column(Float, nullable=True)
    passing_yards_per_game = Column(Float, nullable=True)
    qb_rating = Column(Float, nullable=True)
    sacks = Column(Integer, nullable=True)
    team_games_played = Column(Integer, nullable=True)
    yards_per_completion = Column(Float, nullable=True)
    yards_per_game = Column(Float, nullable=True)
    yards_per_pass_attempt = Column(Float, nullable=True)
    quarterback_rating = Column(Float, nullable=True)

    # Career stats
    career_passing_yards = Column(Float, nullable=True)
    career_completion_pct = Column(Float, nullable=True)
    career_completions = Column(Integer, nullable=True)
    career_ESPN_qbr = Column(Float, nullable=True)
    career_interceptions = Column(Integer, nullable=True)
    career_passing_attempts = Column(Integer, nullable=True)
    career_passing_touchdowns = Column(Integer, nullable=True)
    career_passing_yards_per_game = Column(Float, nullable=True)
    career_qbr = Column(Float, nullable=True)
    career_sacks = Column(Integer, nullable=True)
    career_team_games_played = Column(Integer, nullable=True)
    career_yards_per_completion = Column(Float, nullable=True)
    career_yards_per_game = Column(Float, nullable=True)
    career_yards_per_pass_attempt = Column(Float, nullable=True)

    # Defensive stats
    opponent_pass_yards_allowed_per_game = Column(Float, nullable=True)
    hurries = Column(Float, nullable=True)
    avg_sack_yards = Column(Float, nullable=True)
    passes_batted_down = Column(Float, nullable=True)
    passes_defended = Column(Float, nullable=True)
    sacks_opponent = Column(Integer, nullable=True)
    sack_yards_opponent = Column(Float, nullable=True)
    tackles_for_loss = Column(Float, nullable=True)
    total_tackles = Column(Float, nullable=True)
    points_allowed = Column(Float, nullable=True)
    defensive_interceptions = Column(Float, nullable=True)

    # Weather conditions
    wind_speed = Column(Float, nullable=True)
    temperature = Column(Float, nullable=True)
    precipitation_probability = Column(Float, nullable=True)

    # Projected stat
    projected_passing_yards = Column(Float, nullable=True)

    def __init__(
        self,
        player_id,
        name,
        team_id,
        team_name,
        venue_name,
        opponent_team_name,
        game_time,
        fanduel_price,
        fanduel_point,
        fanduel_flag,
        season_passing_yards,
        career_passing_yards,
        completion_pct,
        completions,
        ESPN_qbr,
        interception_pct,
        interceptions,
        passing_attempts,
        passing_td_pct,
        passing_touchdowns,
        passing_yards,
        passing_yards_per_game,
        qb_rating,
        sacks,
        team_games_played,
        yards_per_completion,
        yards_per_game,
        yards_per_pass_attempt,
        quarterback_rating,
        career_completion_pct,
        career_completions,
        career_ESPN_qbr,
        career_interceptions,
        career_passing_attempts,
        career_passing_touchdowns,
        career_passing_yards_per_game,
        career_qbr,
        career_sacks,
        career_team_games_played,
        career_yards_per_completion,
        career_yards_per_game,
        career_yards_per_pass_attempt,
        opponent_pass_yards_allowed_per_game,
        hurries,
        avg_sack_yards,
        passes_batted_down,
        passes_defended,
        sacks_opponent,
        sack_yards_opponent,
        tackles_for_loss,
        total_tackles,
        points_allowed,
        defensive_interceptions,
        wind_speed,
        temperature,
        precipitation_probability,
        projected_passing_yards,
    ):
        self.player_id = player_id
        self.name = name
        self.team_id = team_id
        self.team_name = team_name
        self.venue_name = venue_name
        self.opponent_team_name = opponent_team_name
        self.game_time = game_time
        self.fanduel_price = fanduel_price
        self.fanduel_point = fanduel_point
        self.fanduel_flag = fanduel_flag
        self.season_passing_yards = season_passing_yards
        self.career_passing_yards = career_passing_yards
        self.completion_pct = completion_pct
        self.completions = completions
        self.ESPN_qbr = ESPN_qbr
        self.interception_pct = interception_pct
        self.interceptions = interceptions
        self.passing_attempts = passing_attempts
        self.passing_td_pct = passing_td_pct
        self.passing_touchdowns = passing_touchdowns
        self.passing_yards = passing_yards
        self.passing_yards_per_game = passing_yards_per_game
        self.qb_rating = qb_rating
        self.sacks = sacks
        self.team_games_played = team_games_played
        self.yards_per_completion = yards_per_completion
        self.yards_per_game = yards_per_game
        self.yards_per_pass_attempt = yards_per_pass_attempt
        self.quarterback_rating = quarterback_rating

        # Career stats
        self.career_completion_pct = career_completion_pct
        self.career_completions = career_completions
        self.career_ESPN_qbr = career_ESPN_qbr
        self.career_interceptions = career_interceptions
        self.career_passing_attempts = career_passing_attempts
        self.career_passing_touchdowns = career_passing_touchdowns
        self.career_passing_yards_per_game = career_passing_yards_per_game
        self.career_qbr = career_qbr
        self.career_sacks = career_sacks
        self.career_team_games_played = career_team_games_played
        self.career_yards_per_completion = career_yards_per_completion
        self.career_yards_per_game = career_yards_per_game
        self.career_yards_per_pass_attempt = career_yards_per_pass_attempt

        # Defensive stats
        self.opponent_pass_yards_allowed_per_game = opponent_pass_yards_allowed_per_game
        self.hurries = hurries
        self.avg_sack_yards = avg_sack_yards
        self.passes_batted_down = passes_batted_down
        self.passes_defended = passes_defended
        self.sacks_opponent = sacks_opponent
        self.sack_yards_opponent = sack_yards_opponent
        self.tackles_for_loss = tackles_for_loss
        self.total_tackles = total_tackles
        self.points_allowed = points_allowed
        self.defensive_interceptions = defensive_interceptions

        # Weather conditions
        self.wind_speed = wind_speed
        self.temperature = temperature
        self.precipitation_probability = precipitation_probability

        # Projected stat
        self.projected_passing_yards = projected_passing_yards


class PlayerCareerData(Base):
    __tablename__ = "pred_player_career_data"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False)  # Reference to player
    season = Column(String(20), nullable=False)  # e.g., "2024-25"
    points = Column(Float, nullable=True)
    fg_attempts = Column(Float, nullable=True)
    fg_percentage = Column(Float, nullable=True)
    three_pt_attempts = Column(Float, nullable=True)
    three_pt_percentage = Column(Float, nullable=True)
    ft_attempts = Column(Float, nullable=True)
    ft_percentage = Column(Float, nullable=True)
    minutes = Column(Float, nullable=True)
    steals = Column(Float, nullable=True)
    turnovers = Column(Float, nullable=True)
    blocks = Column(Float, nullable=True)
    personal_fouls = Column(Float, nullable=True)
    plus_minus = Column(Float, nullable=True)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("player_id", "season", name="unique_player_season_for_career"),
    )

    def __repr__(self):
        return f"<PlayerCareerData Player ID: {self.player_id}, Season: {self.season}>"


class TeamDefenseStats(Base):
    __tablename__ = "pred_team_defense_stats"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, nullable=False, unique=True)
    team_name = Column(String(100), nullable=True)

    # Core defensive stats (what opponents score against this team)
    points_allowed_per_game = Column(Float, nullable=True)
    assists_allowed_per_game = Column(Float, nullable=True)
    rebounds_allowed_per_game = Column(Float, nullable=True)
    offensive_rebounds_allowed_per_game = Column(Float, nullable=True)
    defensive_rebounds = Column(Float, nullable=True)

    # Shooting defense (opponent shooting stats against this team)
    field_goal_pct_allowed = Column(Float, nullable=True)
    three_pt_pct_allowed = Column(Float, nullable=True)
    three_pt_made_allowed_per_game = Column(Float, nullable=True)
    three_pt_attempted_allowed_per_game = Column(Float, nullable=True)
    free_throws_allowed_per_game = Column(Float, nullable=True)

    # Defensive activity stats
    turnovers = Column(Float, nullable=True)
    steals = Column(Float, nullable=True)
    blocks = Column(Float, nullable=True)
    personal_fouls = Column(Float, nullable=True)

    # Pace and efficiency
    pace = Column(Float, nullable=True)
    defensive_rating = Column(Float, nullable=True)

    last_updated = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<TeamDefenseStats Team ID: {self.team_id}, Team: {self.team_name}>"


class TeamOffenseStats(Base):
    __tablename__ = "pred_team_offense_stats"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, unique=True, nullable=False)
    team_name = Column(String(100), nullable=False)
    games_played = Column(Integer, nullable=True)
    turnovers_per_game = Column(Float, nullable=True)
    pace = Column(Float, nullable=True)
    points_per_game = Column(Float, nullable=True)
    assists_per_game = Column(Float, nullable=True)
    offensive_rebounds_per_game = Column(Float, nullable=True)
    field_goals_made_per_game = Column(Float, nullable=True)
    field_goal_percentage = Column(Float, nullable=True)
    three_point_percentage = Column(Float, nullable=True)

    def __repr__(self):
        return f"<TeamOffenseStats {self.team_name}>"


class RecentGames(Base):
    __tablename__ = "pred_recent_games"
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False)
    game_date = Column(Date, nullable=False)
    opponent_team_id = Column(Integer, nullable=False)
    # Basic stats
    points = Column(Float)
    fg_attempts = Column(Float)
    fg_percentage = Column(Float)
    three_pt_attempts = Column(Float)
    three_pt_percentage = Column(Float)
    three_pt_made = Column(Float)
    ft_attempts = Column(Float)
    ft_percentage = Column(Float)
    minutes = Column(Float)
    field_goals_made = Column(Float)
    free_throws_made = Column(Float)
    offensive_rebounds = Column(Float)
    defensive_rebounds = Column(Float)
    rebounds = Column(Float)
    assists = Column(Float)
    turnovers = Column(Float)
    steals = Column(Float)
    blocks = Column(Float)
    personal_fouls = Column(Float)
    double_double = Column(Boolean)
    triple_double = Column(Boolean)

    # Game context
    home_game = Column(Boolean, nullable=True)  # True if home game, False if away

    # Advanced metrics
    true_shooting_percentage = Column(Float, nullable=True)
    usage_percentage = Column(Float, nullable=True)
    estimated_usage_percentage = Column(Float, nullable=True)
    assist_percentage = Column(Float, nullable=True)
    effective_field_goal_percentage = Column(Float, nullable=True)
    estimated_pace = Column(Float, nullable=True)
    pace = Column(Float, nullable=True)
    pace_per_40 = Column(Float, nullable=True)
    possessions = Column(Float, nullable=True)
    player_impact_estimate = Column(Float, nullable=True)
    plus_minus = Column(Float, nullable=True)
    defensive_rating = Column(Float, nullable=True)
    offensive_rating = Column(Float, nullable=True)
    net_rating = Column(Float, nullable=True)
    assist_ratio = Column(Float, nullable=True)
    offensive_rebound_percentage = Column(Float, nullable=True)
    defensive_rebound_percentage = Column(Float, nullable=True)
    rebound_percentage = Column(Float, nullable=True)
    team_turnover_percentage = Column(Float, nullable=True)
    assist_to_turnover_ratio = Column(Float, nullable=True)
    estimated_assist_to_turnover_ratio = Column(Float, nullable=True)

    # New shooting splits fields
    dunks = Column(Float, nullable=True)  # Dunks FGA
    layups = Column(Float, nullable=True)  # Layups FGA
    close_shots = Column(Float, nullable=True)  # Close shots FGA (aggregated)

    __table_args__ = (
        UniqueConstraint(
            "player_id", "game_date", name="unique_recent_games_player_game_date"
        ),
    )


class TeamRoster(Base):
    __tablename__ = "pred_team_roster"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    last_updated = Column(DateTime, nullable=False)
    position = Column(String, nullable=True)

    def __repr__(self):
        return f"<TeamRoster Team ID: {self.team_id}, Player ID: {self.player_id}>"


class PointsProjections(Base):
    __tablename__ = "pred_points_projections"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String, nullable=True)
    opponent_team_name = Column(String, nullable=True)
    projected_points = Column(Float, nullable=False)
    fanduel_line = Column(Float, nullable=True)
    fanduel_over_under = Column(String(7), nullable=True)


class PointsActuals(Base):
    __tablename__ = "pred_points_actuals"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String, nullable=True)
    opponent_team_name = Column(String, nullable=True)
    actual_points = Column(Float, nullable=False)
    projected_points = Column(Float, nullable=False)
    correct_prediction = Column(Boolean, nullable=True)


class ThreePointProjections(Base):
    __tablename__ = "pred_three_point_projections"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String, nullable=True)
    opponent_team_name = Column(String, nullable=True)
    projected_three_pt_made = Column(Float, nullable=True)
    fanduel_line = Column(Float, nullable=True)
    fanduel_over_under = Column(String, nullable=True)

    def __repr__(self):
        return f"<ThreePointProjections Player ID: {self.player_id}, Date: {self.date}, Projected 3PT Made: {self.projected_three_pt_made}>"


class ActualThreePointMade(Base):
    __tablename__ = "pred_actual_three_point_made"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=True)
    opponent_team_name = Column(String(100), nullable=True)
    actual_three_pt_made = Column(Float, nullable=False)
    projected_three_pt_made = Column(
        Float, nullable=True
    )  # Optional for easier tracking of model performance
    correct_prediction = Column(
        Boolean, nullable=True
    )  # True if projection was correct

    def __repr__(self):
        return f"<ActualThreePointMade Player ID: {self.player_id}, Date: {self.date}, Actual 3PT Made: {self.actual_three_pt_made}>"


class TodayActivePlayers(Base):
    __tablename__ = "pred_today_active_players"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    position = Column(String(50), nullable=True)
    team_id = Column(Integer, nullable=False)  # The player's team ID
    team_name = Column(String(100), nullable=False)  # The player's team name
    opponent_team_id = Column(Integer, nullable=False)  # The opposing team ID
    opponent_team_name = Column(String(100), nullable=False)  # The opposing team name
    game_date = Column(Date, nullable=False)  # Store date of the game
    is_home_game = Column(Boolean, nullable=True)  # True if home game, False if away

    __table_args__ = (
        UniqueConstraint("player_id", "game_date", name="unique_player_game_date"),
    )

    def __repr__(self):
        return f"<TodayActivePlayers Player ID: {self.player_id}, Game Date: {self.game_date}>"


class YesterdaysPlayers(Base):
    __tablename__ = "pred_yesterdays_players"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(50), nullable=False)
    position = Column(String(10), nullable=True)
    team_id = Column(Integer, nullable=False)
    team_name = Column(String(50), nullable=True)
    opponent_team_id = Column(Integer, nullable=True)
    opponent_team_name = Column(String(50), nullable=True)
    game_date = Column(Date, nullable=False)


class PlayerStats(Base):
    __tablename__ = "pred_player_stats"

    player_id = Column(Integer, primary_key=True)
    avg_minutes = Column(Float, nullable=True)


class FreeThrowPredictions(Base):
    __tablename__ = "pred_free_throw_predictions"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    predicted_free_throws = Column(Float, nullable=False)
    actual_free_throws = Column(Float, nullable=True)  # Optional for validation
    minutes_played = Column(Float, nullable=True)  # Actual minutes in the game
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<FreeThrowPredictions Player ID: {self.player_id}, Predicted: {self.predicted_free_throws}>"


class BettingCorner(Base):
    __tablename__ = "pred_betting_corner"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)  # Name of the bet
    odds = Column(String(50), nullable=False)  # Odds for the bet
    date = Column(Date, nullable=False)  # Date of the bet
    result = Column(String(20), nullable=False, default="Pending")  # Result of the bet

    def __repr__(self):
        return f"<BettingCorner {self.name} ({self.result})>"


class NoStealsProjections(Base):
    __tablename__ = "pred_no_steals_projections"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    probability_no_steals = Column(Float, nullable=False)


class NoStealsActuals(Base):
    __tablename__ = "pred_no_steals_actuals"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    actual_no_steals = Column(Boolean, nullable=False)
    probability_no_steals = Column(Float, nullable=True)
    correct_prediction = Column(Boolean, nullable=True)


class StealsProjections(Base):
    __tablename__ = "pred_steals_projections"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    projected_steals = Column(Float, nullable=False)
    fanduel_line = Column(Float, nullable=True)
    fanduel_over_under = Column(String(7), nullable=True)


class StealsActuals(Base):
    __tablename__ = "pred_steals_actuals"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    actual_steals = Column(Float, nullable=False)
    projected_steals = Column(Float, nullable=True)
    correct_prediction = Column(Boolean, nullable=True)


class BlocksProjections(Base):
    __tablename__ = "pred_blocks_projections"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    projected_blocks = Column(Float, nullable=False)


class BlocksActuals(Base):
    __tablename__ = "pred_blocks_actuals"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    actual_blocks = Column(Float, nullable=False)
    projected_blocks = Column(Float, nullable=True)
    correct_prediction = Column(Boolean, nullable=True)


class AssistsProjections(Base):
    __tablename__ = "pred_assists_projections"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    projected_assists = Column(Float, nullable=False)


class AssistsActuals(Base):
    __tablename__ = "pred_assists_actuals"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    actual_assists = Column(Float, nullable=False)
    projected_assists = Column(Float, nullable=True)
    correct_prediction = Column(Boolean, nullable=True)


class ReboundsProjections(Base):
    __tablename__ = "pred_rebounds_projections"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    projected_rebounds = Column(Float, nullable=False)
    projected_offensive_rebounds = Column(Float, nullable=True)
    projected_defensive_rebounds = Column(Float, nullable=True)


class ReboundsActuals(Base):
    __tablename__ = "pred_rebounds_actuals"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    actual_rebounds = Column(Float, nullable=False)
    actual_offensive_rebounds = Column(Float, nullable=True)
    actual_defensive_rebounds = Column(Float, nullable=True)
    projected_rebounds = Column(Float, nullable=True)
    correct_prediction = Column(Boolean, nullable=True)


class FreeThrowActuals(Base):
    __tablename__ = "pred_free_throw_actuals"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    actual_free_throws = Column(Float, nullable=False)
    projected_free_throws = Column(Float, nullable=False)
    correct_prediction = Column(
        Boolean, nullable=True
    )  # True if the prediction was correct

    def __repr__(self):
        return f"<FreeThrowActuals Player ID: {self.player_id}, Date: {self.date}, Actual Free Throws: {self.actual_free_throws}>"


class PRAProjections(Base):
    """Points + Rebounds + Assists combo prop projections"""

    __tablename__ = "pred_pra_projections"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)

    # Individual components
    projected_points = Column(Float, nullable=False)
    projected_rebounds = Column(Float, nullable=False)
    projected_assists = Column(Float, nullable=False)

    # Combined projection
    projected_pra = Column(Float, nullable=False)

    # Confidence/variance metrics
    pra_floor = Column(Float, nullable=True)  # Low estimate
    pra_ceiling = Column(Float, nullable=True)  # High estimate

    # Sportsbook lines for comparison
    fanduel_line = Column(Float, nullable=True)
    fanduel_over_under = Column(String(7), nullable=True)

    def __repr__(self):
        return f"<PRAProjections {self.player_name}: {self.projected_pra:.1f} PRA vs {self.opponent_team_name}>"


class PRAActuals(Base):
    """Points + Rebounds + Assists actual results for accuracy tracking"""

    __tablename__ = "pred_pra_actuals"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)

    # Individual components
    actual_points = Column(Float, nullable=False)
    actual_rebounds = Column(Float, nullable=False)
    actual_assists = Column(Float, nullable=False)

    # Combined actual
    actual_pra = Column(Float, nullable=False)

    # For accuracy tracking
    projected_pra = Column(Float, nullable=True)
    prediction_error = Column(Float, nullable=True)  # actual - projected
    correct_prediction = Column(Boolean, nullable=True)

    def __repr__(self):
        return (
            f"<PRAActuals {self.player_name}: {self.actual_pra:.1f} PRA on {self.date}>"
        )


class TopPerformers(Base):
    __tablename__ = "pred_top_performers"

    id = Column(Integer, primary_key=True)
    game_date = Column(Date, nullable=False)
    matchup = Column(String(100), nullable=False, unique=True)
    top_scorer = Column(String(100), nullable=True)
    top_assist = Column(String(100), nullable=True)
    top_rebound = Column(String(100), nullable=True)
    top_three_pt = Column(String(100), nullable=True)

    def __repr__(self):
        return f"<TopPerformers {self.matchup} - {self.game_date}>"


class ValueBet(Base):
    __tablename__ = "pred_value_bets"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True, default=date.today)
    game = Column(String, nullable=False)
    team = Column(String, nullable=False)
    estimated_prob = Column(Float, nullable=False)
    implied_prob = Column(Float, nullable=False)
    expected_value = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("date", "game", "team", name="uq_date_game_team"),
    )


class DailyHRPredictions(Base):
    __tablename__ = "pred_daily_hr_predictions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True, default=date.today)
    batter_id = Column(Integer, nullable=False)
    batter_name = Column(String(100), nullable=False)
    pitcher_name = Column(String(100), nullable=True)
    park_id = Column(String(100), nullable=True)
    predicted_prob = Column(Float, nullable=False)

    def __repr__(self):
        return f"<DailyHRPredictions {self.date} - {self.batter_name} vs {self.pitcher_name} {self.predicted_prob:.3f}>"


class QBPredictions(Base):
    __tablename__ = "pred_qb_predictions"
    id = Column(Integer, primary_key=True)
    qb_player_id = Column(String(20), nullable=False)
    qb_player_name = Column(String(100), nullable=False)
    team_id = Column(Integer, nullable=False)
    team_name = Column(String, nullable=False)
    opponent_team_name = Column(String, nullable=False)
    game_date = Column(DateTime, nullable=False)
    venue_name = Column(String, nullable=False)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)

    # Enhanced predictions
    predicted_passing_yards = Column(Float, nullable=False)
    predicted_attempts = Column(Float, nullable=True)
    predicted_completions = Column(Float, nullable=True)
    predicted_touchdowns = Column(Float, nullable=True)
    predicted_interceptions = Column(Float, nullable=True)

    # Prediction confidence and intervals
    model_confidence = Column(Float, nullable=True)
    prediction_interval_lower = Column(Float, nullable=True)
    prediction_interval_upper = Column(Float, nullable=True)

    # Model metadata
    prediction_method = Column(
        String(50), nullable=True
    )  # 'ml_ensemble', 'enhanced_features', etc.
    model_version = Column(String(20), nullable=True)
    features_used = Column(Integer, nullable=True)
    feature_importance = Column(JSON, nullable=True)

    # Situational factors
    weather_temperature = Column(Float, nullable=True)
    weather_wind_speed = Column(Float, nullable=True)
    weather_conditions = Column(String(50), nullable=True)
    dome_game = Column(Boolean, nullable=True)
    primetime_game = Column(Boolean, nullable=True)
    divisional_game = Column(Boolean, nullable=True)

    # Game context
    spread = Column(Float, nullable=True)
    total_points = Column(Float, nullable=True)
    implied_team_total = Column(Float, nullable=True)

    # QB performance metrics used in prediction
    qb_recent_form = Column(Float, nullable=True)
    qb_vs_defense_rating = Column(Float, nullable=True)
    matchup_advantage = Column(Float, nullable=True)

    # Over/Under Betting Information
    ou_line = Column(Float, nullable=True)  # Passing yards O/U line
    over_odds = Column(Integer, nullable=True)  # Odds for over bet
    under_odds = Column(Integer, nullable=True)  # Odds for under bet
    best_over_book = Column(String(50), nullable=True)  # Best bookmaker for over
    best_under_book = Column(String(50), nullable=True)  # Best bookmaker for under
    betting_recommendation = Column(
        String(20), nullable=True
    )  # 'OVER', 'UNDER', 'PASS'
    bet_size = Column(String(10), nullable=True)  # 'LARGE', 'MEDIUM', 'SMALL'
    edge_percentage = Column(Float, nullable=True)  # Calculated edge in percentage
    recommendation_reason = Column(
        String(200), nullable=True
    )  # Reason for recommendation

    # Metadata
    prediction_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<QBPredictions {self.qb_player_name} vs {self.opponent_team_name} - {self.predicted_passing_yards} yards>"


class QBActuals(Base):
    __tablename__ = "pred_qb_actuals"
    id = Column(Integer, primary_key=True)
    game_date = Column(DateTime, nullable=False)
    qb_player_id = Column(String(20), nullable=False)
    qb_player_name = Column(String(100), nullable=False)
    team_name = Column(String, nullable=False)
    opponent_team_name = Column(String, nullable=False)
    venue_name = Column(String, nullable=True)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)

    # Actual performance
    actual_passing_yards = Column(Float, nullable=False)
    actual_attempts = Column(Integer, nullable=True)
    actual_completions = Column(Integer, nullable=True)
    actual_touchdowns = Column(Integer, nullable=True)
    actual_interceptions = Column(Integer, nullable=True)
    actual_completion_pct = Column(Float, nullable=True)
    actual_yards_per_attempt = Column(Float, nullable=True)
    actual_passer_rating = Column(Float, nullable=True)

    # Game conditions
    game_temperature = Column(Float, nullable=True)
    game_wind_speed = Column(Float, nullable=True)
    game_weather = Column(String(50), nullable=True)

    # Game context
    final_score_team = Column(Integer, nullable=True)
    final_score_opponent = Column(Integer, nullable=True)
    game_script = Column(String(20), nullable=True)  # 'positive', 'negative', 'neutral'

    # Prediction comparison (from our predictions)
    predicted_passing_yards = Column(Float, nullable=False)
    prediction_error = Column(Float, nullable=True)  # actual - predicted
    prediction_accuracy = Column(Float, nullable=True)  # abs(error) / actual
    hit_over_under = Column(Boolean, nullable=True)  # Did they hit betting lines?
    correct_prediction = Column(Boolean, nullable=True)  # Did our prediction match?
    prediction_confidence = Column(Float, nullable=True)  # How confident were we?
    prediction_method = Column(String(50), nullable=True)  # Which method was used

    # Advanced metrics
    epa_per_play = Column(Float, nullable=True)
    cpoe = Column(Float, nullable=True)  # Completion % over expected
    air_yards_per_attempt = Column(Float, nullable=True)
    pressure_rate_faced = Column(Float, nullable=True)

    # Metadata
    data_collection_date = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<QBActuals {self.qb_player_name} vs {self.opponent_team_name} - {self.actual_passing_yards} yards>"


# NHL Models
class NHLTeam(Base):
    __tablename__ = "pred_nhl_teams"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    abbrev = Column(String(10), nullable=False)
    conference = Column(String(50), nullable=True)
    division = Column(String(50), nullable=True)
    venue_name = Column(String(100), nullable=True)


class NHLGoalie(Base):
    __tablename__ = "pred_nhl_goalies"
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    team_id = Column(Integer, nullable=False)
    team_name = Column(String(100), nullable=False)
    sweater_number = Column(Integer, nullable=True)

    # Season stats
    games_played = Column(Integer, nullable=True)
    wins = Column(Integer, nullable=True)
    losses = Column(Integer, nullable=True)
    ot_losses = Column(Integer, nullable=True)
    saves = Column(Integer, nullable=True)
    shots_against = Column(Integer, nullable=True)
    save_pct = Column(Float, nullable=True)
    goals_against_avg = Column(Float, nullable=True)
    shutouts = Column(Integer, nullable=True)

    # Recent form (last 5 games)
    last_5_saves = Column(Integer, nullable=True)
    last_5_shots_against = Column(Integer, nullable=True)
    last_5_save_pct = Column(Float, nullable=True)
    last_5_games_played = Column(Integer, nullable=True)

    # Last 10 games
    last_10_saves = Column(Integer, nullable=True)
    last_10_shots_against = Column(Integer, nullable=True)
    last_10_save_pct = Column(Float, nullable=True)
    last_10_games_played = Column(Integer, nullable=True)

    # Home/Away splits
    home_games_played = Column(Integer, nullable=True)
    home_save_pct = Column(Float, nullable=True)
    home_saves = Column(Integer, nullable=True)
    home_shots_against = Column(Integer, nullable=True)

    away_games_played = Column(Integer, nullable=True)
    away_save_pct = Column(Float, nullable=True)
    away_saves = Column(Integer, nullable=True)
    away_shots_against = Column(Integer, nullable=True)

    # Last game info (for back-to-back detection)
    last_game_date = Column(Date, nullable=True)
    last_game_saves = Column(Integer, nullable=True)
    last_game_shots = Column(Integer, nullable=True)

    # Momentum tracking (hot/cold streaks)
    last_5_sv_pct_trend = Column(
        Float, nullable=True
    )  # Positive = improving, Negative = declining
    is_hot_streak = Column(Boolean, nullable=True)  # Last 3 games above season average
    is_cold_streak = Column(Boolean, nullable=True)  # Last 3 games below season average

    # Injury/Health tracking
    injury_status = Column(
        String(50), nullable=True
    )  # 'healthy', 'day-to-day', 'ir', 'out'
    injury_description = Column(String(200), nullable=True)  # Brief injury description
    games_since_injury = Column(
        Integer, nullable=True
    )  # Games played since returning from injury
    last_injury_date = Column(Date, nullable=True)  # Last reported injury date

    # Workload/Fatigue tracking
    games_in_last_7_days = Column(Integer, nullable=True)
    games_in_last_14_days = Column(Integer, nullable=True)
    shots_faced_last_7_days = Column(
        Integer, nullable=True
    )  # Total shots in last 7 days
    avg_toi_last_5_games = Column(Float, nullable=True)  # Average time on ice (minutes)
    is_overworked = Column(Boolean, nullable=True)  # Flag for heavy recent workload

    # Career vs opponent stats (JSON format)
    career_vs_opponent_stats = Column(JSON, nullable=True)
    # Format: {"team_name": {"games": 5, "saves": 150, "shots": 165, "sv_pct": 0.909}}

    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)


class NHLTeamStats(Base):
    __tablename__ = "pred_nhl_team_stats"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, unique=True, nullable=False)
    team_name = Column(String(100), nullable=False)

    # Season stats
    games_played = Column(Integer, nullable=True)
    wins = Column(Integer, nullable=True)
    losses = Column(Integer, nullable=True)
    ot_losses = Column(Integer, nullable=True)

    # Offensive stats
    goals_for = Column(Integer, nullable=True)
    goals_for_per_game = Column(Float, nullable=True)
    shots_for = Column(Integer, nullable=True)
    shots_for_per_game = Column(Float, nullable=True)
    shooting_pct = Column(Float, nullable=True)  # Goals / Shots
    power_play_pct = Column(Float, nullable=True)
    pp_opportunities_per_game = Column(Float, nullable=True)
    power_play_goals_for = Column(Integer, nullable=True)
    power_play_goals_against = Column(Integer, nullable=True)

    # Defensive stats
    goals_against = Column(Integer, nullable=True)
    goals_against_per_game = Column(Float, nullable=True)
    shots_against = Column(Integer, nullable=True)
    shots_against_per_game = Column(Float, nullable=True)
    penalty_kill_pct = Column(Float, nullable=True)
    sh_goals_against_per_game = Column(Float, nullable=True)
    blocked_shots_per_game = Column(Float, nullable=True)
    high_danger_chances_against_per_game = Column(Float, nullable=True)
    avg_shot_distance = Column(Float, nullable=True)

    # Recent form (last 10 games)
    last_10_shots_for_per_game = Column(Float, nullable=True)
    last_10_shots_against_per_game = Column(Float, nullable=True)
    last_10_goals_for_per_game = Column(Float, nullable=True)
    last_10_goals_against_per_game = Column(Float, nullable=True)
    last_10_shooting_pct = Column(Float, nullable=True)  # Recent shooting efficiency

    # Shot quality metrics (for expected goals calculations)
    high_danger_shots_for = Column(
        Integer, nullable=True
    )  # Shots from high-danger areas
    high_danger_goals = Column(Integer, nullable=True)  # Goals from high-danger shots
    expected_goals_for = Column(Float, nullable=True)  # xGF based on shot quality
    expected_goals_against = Column(
        Float, nullable=True
    )  # xGA based on shot quality allowed

    # Opponent quality ranking
    offensive_rating = Column(
        Float, nullable=True
    )  # Composite offensive rating (0-100)
    defensive_rating = Column(
        Float, nullable=True
    )  # Composite defensive rating (0-100)
    overall_strength = Column(Float, nullable=True)  # Overall team strength (0-100)

    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)


class NHLPlayer(Base):
    __tablename__ = "pred_nhl_players"
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    team_id = Column(Integer, nullable=False)
    team_name = Column(String(100), nullable=False)
    position = Column(String(10), nullable=False)  # L, R, C, D
    sweater_number = Column(Integer, nullable=True)

    # Season stats
    games_played = Column(Integer, nullable=True)
    goals = Column(Integer, nullable=True)
    assists = Column(Integer, nullable=True)
    points = Column(Integer, nullable=True)
    shots = Column(Integer, nullable=True)
    shots_per_game = Column(Float, nullable=True)
    toi_per_game = Column(Float, nullable=True)  # Time on ice per game in minutes

    # Recent form (last 10 games)
    last_10_shots = Column(Integer, nullable=True)
    last_10_shots_per_game = Column(Float, nullable=True)
    last_10_goals = Column(Integer, nullable=True)
    last_10_games_played = Column(Integer, nullable=True)

    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)


class NHLGameStats(Base):
    __tablename__ = "pred_nhl_game_stats"
    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, unique=True, nullable=False)
    season = Column(Integer, nullable=False)
    game_type = Column(Integer, nullable=False)  # 2 = regular season, 3 = playoffs
    game_date = Column(Date, nullable=False)
    game_state = Column(String(20), nullable=False)  # FINAL, LIVE, etc.

    # Teams
    home_team_id = Column(Integer, nullable=False)
    home_team_name = Column(String(100), nullable=False)
    away_team_id = Column(Integer, nullable=False)
    away_team_name = Column(String(100), nullable=False)

    # Scores
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)

    # Shots
    home_sog = Column(Integer, nullable=True)
    away_sog = Column(Integer, nullable=True)

    venue_name = Column(String(100), nullable=True)

    # Goalie info
    home_goalie_id = Column(Integer, nullable=True)
    home_goalie_name = Column(String(100), nullable=True)
    home_goalie_saves = Column(Integer, nullable=True)
    home_goalie_shots_against = Column(Integer, nullable=True)
    home_goalie_save_pct = Column(Float, nullable=True)

    away_goalie_id = Column(Integer, nullable=True)
    away_goalie_name = Column(String(100), nullable=True)
    away_goalie_saves = Column(Integer, nullable=True)
    away_goalie_shots_against = Column(Integer, nullable=True)
    away_goalie_save_pct = Column(Float, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class NHLGoaliePredictions(Base):
    __tablename__ = "pred_nhl_goalie_predictions"
    id = Column(Integer, primary_key=True)
    game_date = Column(Date, nullable=False)
    game_id = Column(Integer, nullable=True)  # NHL game ID
    goalie_id = Column(Integer, nullable=False)
    goalie_name = Column(String(100), nullable=False)
    team_id = Column(Integer, nullable=False)
    team_name = Column(String(100), nullable=False)
    opponent_team_id = Column(Integer, nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    venue_name = Column(String(100), nullable=True)
    is_home = Column(Boolean, nullable=True)
    game_time = Column(DateTime, nullable=True)
    starter_confirmed = Column(Boolean, nullable=True, default=False)
    confirmation_time = Column(DateTime, nullable=True)  # When starter was confirmed
    was_scratch = Column(
        Boolean, nullable=True, default=False
    )  # If goalie was scratched before game

    # Predictions
    predicted_saves = Column(Float, nullable=False)
    predicted_shots_against = Column(Float, nullable=False)
    predicted_save_pct = Column(Float, nullable=False)

    # Goalie stats used in prediction
    goalie_season_save_pct = Column(Float, nullable=True)
    goalie_recent_save_pct = Column(Float, nullable=True)
    opponent_shots_avg = Column(Float, nullable=True)

    # Betting line from DraftKings
    sportsbook = Column(String(50), nullable=True, default="DraftKings")
    saves_line = Column(Float, nullable=True)  # O/U line for saves
    over_odds = Column(Integer, nullable=True)  # American odds for OVER
    under_odds = Column(Integer, nullable=True)  # American odds for UNDER
    line_available = Column(Boolean, nullable=True, default=False)

    # Betting recommendation
    betting_recommendation = Column(
        String(50), nullable=True
    )  # 'OVER 28.5', 'UNDER 28.5', 'PASS'
    edge_category = Column(String(20), nullable=True)  # 'HIGH', 'MEDIUM', 'LOW'
    confidence = Column(Float, nullable=True)  # 0-100
    edge_saves = Column(Float, nullable=True)  # Difference between prediction and line

    # Model info
    model_version = Column(String(20), nullable=True)
    features_used = Column(JSON, nullable=True)

    # Advanced prediction features
    special_teams_adjustment = Column(Float, nullable=True)
    shot_quality_adjustment = Column(Float, nullable=True)
    vs_team_historical_adjustment = Column(Float, nullable=True)
    expected_goals_against = Column(Float, nullable=True)
    opponent_pp_pct = Column(Float, nullable=True)
    goalie_career_vs_opponent_sv_pct = Column(Float, nullable=True)

    prediction_date = Column(DateTime, nullable=False, default=datetime.utcnow)


class NHLGoalieActuals(Base):
    __tablename__ = "pred_nhl_goalie_actuals"
    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, nullable=False)
    game_date = Column(Date, nullable=False)
    goalie_id = Column(Integer, nullable=False)
    goalie_name = Column(String(100), nullable=False)
    team_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    venue_name = Column(String(100), nullable=True)  # Specific arena
    is_home = Column(Boolean, nullable=True)

    # Actuals
    actual_saves = Column(Integer, nullable=False)
    actual_shots_against = Column(Integer, nullable=False)
    actual_save_pct = Column(Float, nullable=False)
    actual_goals_against = Column(Integer, nullable=False)
    actual_toi = Column(String(10), nullable=True)
    decision = Column(String(5), nullable=True)  # W, L, OT

    # Shot quality metrics
    high_danger_saves = Column(Integer, nullable=True)
    high_danger_shots_against = Column(Integer, nullable=True)
    high_danger_save_pct = Column(Float, nullable=True)
    expected_goals_against = Column(Float, nullable=True)  # xGA
    goals_saved_above_expected = Column(Float, nullable=True)  # GSAx

    # Predictions comparison
    predicted_saves = Column(Float, nullable=True)
    predicted_shots_against = Column(Float, nullable=True)
    prediction_error = Column(Float, nullable=True)
    correct_prediction = Column(Boolean, nullable=True)

    # Sportsbook line and recommendation tracking
    sportsbook = Column(String(50), nullable=True)
    saves_line = Column(Float, nullable=True)
    over_odds = Column(Integer, nullable=True)
    under_odds = Column(Integer, nullable=True)
    betting_recommendation = Column(
        String(50), nullable=True
    )  # e.g., "OVER 28.5", "UNDER 28.5", "PASS"
    edge_category = Column(String(20), nullable=True)  # HIGH, MEDIUM, LOW
    edge_saves = Column(Float, nullable=True)
    recommendation_correct = Column(
        Boolean, nullable=True
    )  # Did the recommendation win?

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class NHLTeamShotsPredictions(Base):
    __tablename__ = "pred_nhl_team_shots_predictions"
    id = Column(Integer, primary_key=True)
    game_date = Column(Date, nullable=False)
    team_id = Column(Integer, nullable=False)
    team_name = Column(String(100), nullable=False)
    opponent_team_id = Column(Integer, nullable=False)
    opponent_team_name = Column(String(100), nullable=False)

    # Predictions
    predicted_shots = Column(Float, nullable=False)
    shots_line = Column(Float, nullable=True)
    betting_recommendation = Column(String(20), nullable=True)
    confidence = Column(Float, nullable=True)

    prediction_date = Column(DateTime, nullable=False, default=datetime.utcnow)


class NHLPlayerShotsPredictions(Base):
    __tablename__ = "pred_nhl_player_shots_predictions"
    id = Column(Integer, primary_key=True)
    game_date = Column(Date, nullable=False)
    game_time_et = Column(DateTime, nullable=True)
    player_id = Column(Integer, nullable=False)
    player_name = Column(String(100), nullable=False)
    team_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)

    # Predictions
    predicted_shots = Column(Float, nullable=False)
    shots_line = Column(Float, nullable=True)
    betting_recommendation = Column(String(20), nullable=True)
    confidence = Column(Float, nullable=True)

    prediction_date = Column(DateTime, nullable=False, default=datetime.utcnow)


class NHLTeamTotalsPredictions(Base):
    __tablename__ = "pred_nhl_team_totals_predictions"
    id = Column(Integer, primary_key=True)
    game_date = Column(Date, nullable=False)
    game_time_et = Column(DateTime, nullable=True)
    home_team_id = Column(Integer, nullable=False)
    home_team_name = Column(String(100), nullable=False)
    away_team_id = Column(Integer, nullable=False)
    away_team_name = Column(String(100), nullable=False)

    # Predictions
    predicted_home_goals = Column(Float, nullable=False)
    predicted_away_goals = Column(Float, nullable=False)
    predicted_total_goals = Column(Float, nullable=False)
    suggested_ou_line = Column(Float, nullable=False)

    # Betting line from DraftKings
    draftkings_ou_line = Column(Float, nullable=True)
    over_odds = Column(Integer, nullable=True)
    under_odds = Column(Integer, nullable=True)

    # Prediction quality
    confidence = Column(Float, nullable=True)
    edge = Column(Float, nullable=True)  # Difference between our line and DK line
    betting_recommendation = Column(String(20), nullable=True)

    prediction_date = Column(DateTime, nullable=False, default=datetime.utcnow)


# =============================================================================
# NBA PREDICTION ENHANCEMENT MODELS
# =============================================================================


class PlayerInjuryStatus(Base):
    """
    Track player injury status for more accurate predictions.
    Updated daily from RotoWire and other sources.
    """

    __tablename__ = "pred_player_injury_status"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False, index=True)
    player_name = Column(String(100), nullable=False)

    # Injury status: healthy, questionable, doubtful, out, ir (injured reserve)
    status = Column(String(20), nullable=False, default="healthy")
    injury_type = Column(String(100), nullable=True)  # e.g., "ankle", "knee", "rest"

    # Return tracking
    games_missed = Column(Integer, default=0)  # Consecutive games missed
    last_game_date = Column(Date, nullable=True)  # Last game played
    expected_return_date = Column(Date, nullable=True)

    # Timestamps
    date_updated = Column(DateTime, nullable=False, default=datetime.utcnow)
    date_injured = Column(Date, nullable=True)

    __table_args__ = (UniqueConstraint("player_id", name="unique_player_injury"),)

    def __repr__(self):
        return f"<PlayerInjuryStatus {self.player_name}: {self.status}>"

    def get_injury_multiplier(self):
        """
        Calculate projection multiplier based on injury status.
        Returns a value between 0.0 and 1.0.
        """
        if self.status == "healthy":
            # If returning from injury, apply recovery adjustment
            if self.games_missed and self.games_missed > 0:
                # Gradual recovery: 85% first game back, increases each game
                recovery_games = min(self.games_missed, 10)
                if recovery_games >= 5:
                    return 0.85  # Long absence = bigger adjustment
                elif recovery_games >= 3:
                    return 0.90
                else:
                    return 0.95
            return 1.0
        elif self.status == "questionable":
            return 0.90  # 10% reduction if questionable
        elif self.status == "doubtful":
            return 0.80  # 20% reduction if doubtful
        elif self.status in ["out", "ir"]:
            return 0.0  # Don't project if out
        return 1.0


class PredictionAccuracy(Base):
    """
    Track prediction accuracy for continuous improvement.
    Stores each prediction alongside its actual result for analysis.
    """

    __tablename__ = "pred_prediction_accuracy"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False, index=True)
    player_name = Column(String(100), nullable=False)
    game_date = Column(Date, nullable=False, index=True)

    # Stat type: points, assists, rebounds, three_pt_made, steals, blocks, free_throws
    stat_type = Column(String(30), nullable=False, index=True)

    # Prediction vs Actual
    projected_value = Column(Float, nullable=False)
    actual_value = Column(Float, nullable=True)  # Null until game completes

    # Error metrics (calculated after game)
    error = Column(Float, nullable=True)  # actual - projected
    absolute_error = Column(Float, nullable=True)  # |error|
    percentage_error = Column(Float, nullable=True)  # |error| / actual * 100

    # Context for analysis
    opponent_team_id = Column(Integer, nullable=True)
    is_home_game = Column(Boolean, nullable=True)
    minutes_played = Column(Float, nullable=True)

    # Feature values at prediction time (for debugging/analysis)
    features_json = Column(Text, nullable=True)  # JSON blob of features used

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "player_id", "game_date", "stat_type", name="unique_prediction_accuracy"
        ),
        Index("idx_accuracy_date_stat", "game_date", "stat_type"),
    )

    def __repr__(self):
        return f"<PredictionAccuracy {self.player_name} {self.stat_type}: proj={self.projected_value}, actual={self.actual_value}>"

    def calculate_error(self):
        """Calculate error metrics once actual value is known."""
        if self.actual_value is not None:
            self.error = self.actual_value - self.projected_value
            self.absolute_error = abs(self.error)
            if self.actual_value > 0:
                self.percentage_error = (self.absolute_error / self.actual_value) * 100
            else:
                self.percentage_error = 0 if self.projected_value == 0 else 100


class PlayerExpectedMinutes(Base):
    """
    Track expected minutes for players based on recent performance and role.
    Used to adjust projections when minutes are likely to change.
    """

    __tablename__ = "pred_player_expected_minutes"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False, index=True)
    player_name = Column(String(100), nullable=False)

    # Recent minutes data
    avg_minutes_5 = Column(Float, nullable=True)  # Last 5 games
    avg_minutes_10 = Column(Float, nullable=True)  # Last 10 games
    avg_minutes_season = Column(Float, nullable=True)  # Season average

    # Minutes consistency
    minutes_std_dev = Column(Float, nullable=True)  # Standard deviation
    min_minutes_10 = Column(Float, nullable=True)  # Minimum in last 10
    max_minutes_10 = Column(Float, nullable=True)  # Maximum in last 10

    # Role indicators
    is_starter = Column(Boolean, nullable=True)  # Based on recent games
    starter_rate = Column(Float, nullable=True)  # % of games as starter

    # Situational adjustments
    b2b_minutes_avg = Column(Float, nullable=True)  # Avg minutes on back-to-backs
    home_minutes_avg = Column(Float, nullable=True)  # Avg home minutes
    away_minutes_avg = Column(Float, nullable=True)  # Avg away minutes

    # Expected minutes for today (calculated value)
    expected_minutes_today = Column(Float, nullable=True)
    minutes_confidence = Column(Float, nullable=True)  # 0-1 confidence score

    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("player_id", name="unique_player_expected_minutes"),
    )

    def __repr__(self):
        return f"<PlayerExpectedMinutes {self.player_name}: {self.expected_minutes_today} min>"

    def get_minutes_multiplier(self, baseline_minutes=30.0):
        """
        Calculate a projection multiplier based on expected vs baseline minutes.
        """
        if not self.expected_minutes_today or not baseline_minutes:
            return 1.0

        ratio = self.expected_minutes_today / baseline_minutes
        # Cap adjustment at +-20%
        return max(0.80, min(ratio, 1.20))


class NBAGameLines(Base):
    """
    Store Vegas lines for NBA games - spread and totals.
    Used for:
    - Blowout risk prediction (high spread = star players may rest in 4th)
    - Pace prediction (high total = fast-paced game = more stats)
    - Game script modeling (favorites vs underdogs play differently)
    """

    __tablename__ = "pred_nba_game_lines"

    id = Column(Integer, primary_key=True)
    game_date = Column(Date, nullable=False, index=True)

    # Game identification
    home_team_id = Column(Integer, nullable=True)
    away_team_id = Column(Integer, nullable=True)
    home_team_name = Column(String(100), nullable=False)
    away_team_name = Column(String(100), nullable=False)

    # External IDs for matching
    odds_api_event_id = Column(String(100), nullable=True)
    game_time = Column(DateTime, nullable=True)

    # Spread lines (negative = home favorite)
    spread_home = Column(Float, nullable=True)  # e.g., -7.5 means home favored by 7.5
    spread_away = Column(Float, nullable=True)  # e.g., +7.5
    spread_home_odds = Column(Integer, nullable=True)  # American odds
    spread_away_odds = Column(Integer, nullable=True)

    # Total (over/under) lines
    total = Column(Float, nullable=True)  # e.g., 224.5
    over_odds = Column(Integer, nullable=True)
    under_odds = Column(Integer, nullable=True)

    # Moneyline
    moneyline_home = Column(Integer, nullable=True)  # e.g., -280
    moneyline_away = Column(Integer, nullable=True)  # e.g., +230

    # Source tracking
    bookmaker = Column(String(50), nullable=True, default="consensus")
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "game_date", "home_team_name", "away_team_name", name="unique_nba_game_line"
        ),
        Index("idx_nba_game_lines_date", "game_date"),
    )

    def __repr__(self):
        return f"<NBAGameLines {self.away_team_name} @ {self.home_team_name}: spread={self.spread_home}, total={self.total}>"

    def get_blowout_risk(self):
        """
        Calculate probability of a blowout (star players benched in 4th quarter).
        High spread = higher blowout risk.

        Returns:
            float: 0.0 to 1.0 probability of blowout
        """
        if self.spread_home is None:
            return 0.15  # Default 15% blowout risk

        abs_spread = abs(self.spread_home)

        # Blowout risk increases with spread
        # Spread 0-3: ~5% blowout risk
        # Spread 4-7: ~10% blowout risk
        # Spread 8-12: ~20% blowout risk
        # Spread 13+: ~35% blowout risk
        if abs_spread <= 3:
            return 0.05
        elif abs_spread <= 7:
            return 0.10
        elif abs_spread <= 12:
            return 0.20
        elif abs_spread <= 15:
            return 0.30
        else:
            return 0.40

    def get_pace_multiplier(self):
        """
        Calculate pace multiplier based on total.
        Higher total = faster pace = more stats.

        Returns:
            float: Multiplier for pace adjustment (0.92 to 1.08)
        """
        if self.total is None:
            return 1.0

        # NBA average total is ~220-225
        LEAGUE_AVG_TOTAL = 222.5

        pace_ratio = self.total / LEAGUE_AVG_TOTAL

        # Cap at +-8% adjustment
        return max(0.92, min(pace_ratio, 1.08))

    def get_minutes_risk_for_team(self, team_name):
        """
        Calculate minutes risk factor for a team based on spread.
        Favorites with big leads rest starters.
        Underdogs in blowouts also rest starters.

        Args:
            team_name: Team name to check

        Returns:
            float: Minutes multiplier (0.85 to 1.0)
        """
        if self.spread_home is None:
            return 1.0

        is_home = team_name.lower() in self.home_team_name.lower()
        spread = self.spread_home if is_home else self.spread_away

        abs_spread = abs(spread) if spread else 0

        # Favorites rest starters when winning big
        # Underdogs rest starters when losing big
        # Both scenarios = reduced minutes
        blowout_risk = self.get_blowout_risk()

        # Expected minutes reduction due to blowout risk
        # 40% blowout risk = 6% minutes reduction on average
        minutes_reduction = blowout_risk * 0.15  # Max 6% reduction

        return 1.0 - minutes_reduction


class NBATotalsProjections(Base):
    """
    Store NBA game totals (over/under) projections.
    Predicts expected total combined points for both teams.
    """

    __tablename__ = "pred_nba_totals_projections"

    id = Column(Integer, primary_key=True)
    game_date = Column(Date, nullable=False, index=True)

    # Game identification
    home_team_id = Column(Integer, nullable=True)
    away_team_id = Column(Integer, nullable=True)
    home_team_name = Column(String(100), nullable=False)
    away_team_name = Column(String(100), nullable=False)

    # Core projection
    projected_total = Column(Float, nullable=False)
    home_projected_score = Column(Float, nullable=True)
    away_projected_score = Column(Float, nullable=True)

    # Base projection components (before adjustments)
    base_projection = Column(Float, nullable=True)
    expected_pace = Column(Float, nullable=True)
    home_offensive_rating = Column(Float, nullable=True)
    away_offensive_rating = Column(Float, nullable=True)
    home_defensive_rating = Column(Float, nullable=True)
    away_defensive_rating = Column(Float, nullable=True)

    # Adjustments applied
    injury_adjustment = Column(Float, nullable=True, default=0.0)
    rest_adjustment = Column(Float, nullable=True, default=0.0)
    venue_adjustment = Column(Float, nullable=True, default=0.0)
    form_adjustment = Column(Float, nullable=True, default=0.0)
    total_adjustment = Column(Float, nullable=True, default=0.0)

    # Market comparison
    market_total = Column(Float, nullable=True)  # Vegas line
    edge = Column(Float, nullable=True)  # projected - market
    recommendation = Column(String(20), nullable=True)  # OVER, UNDER, NO_PLAY
    confidence_score = Column(Float, nullable=True)  # 0.0 to 1.0

    # Key factors (JSON for flexibility)
    injury_report = Column(JSON, nullable=True)
    factors = Column(JSON, nullable=True)

    # Projected starting lineups (JSON)
    home_starters = Column(JSON, nullable=True)
    away_starters = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "game_date",
            "home_team_name",
            "away_team_name",
            name="unique_nba_totals_projection",
        ),
        Index("idx_nba_totals_projections_date", "game_date"),
        Index("idx_nba_totals_projections_edge", "edge"),
    )

    def __repr__(self):
        return f"<NBATotalsProjections {self.away_team_name} @ {self.home_team_name}: projected={self.projected_total}, edge={self.edge}>"

    def get_value_rating(self):
        """
        Get value rating based on edge size.
        Returns: LOW, MEDIUM, HIGH, VERY_HIGH
        """
        if self.edge is None:
            return None

        abs_edge = abs(self.edge)
        if abs_edge < 2:
            return "LOW"
        elif abs_edge < 3:
            return "MEDIUM"
        elif abs_edge < 5:
            return "HIGH"
        else:
            return "VERY_HIGH"


class NBATotalsActuals(Base):
    """
    Store actual game totals for accuracy tracking.
    """

    __tablename__ = "pred_nba_totals_actuals"

    id = Column(Integer, primary_key=True)
    game_date = Column(Date, nullable=False, index=True)

    # Game identification
    home_team_id = Column(Integer, nullable=True)
    away_team_id = Column(Integer, nullable=True)
    home_team_name = Column(String(100), nullable=False)
    away_team_name = Column(String(100), nullable=False)

    # Actual results
    actual_total = Column(Integer, nullable=False)
    home_actual_score = Column(Integer, nullable=True)
    away_actual_score = Column(Integer, nullable=True)

    # Projection details (for comparison)
    projected_total = Column(Float, nullable=True)
    market_total = Column(Float, nullable=True)

    # Results
    projection_error = Column(Float, nullable=True)  # actual - projected
    market_error = Column(Float, nullable=True)  # actual - market
    was_over = Column(Boolean, nullable=True)  # actual > market
    correct_prediction = Column(Boolean, nullable=True)  # Did we pick correctly?

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "game_date",
            "home_team_name",
            "away_team_name",
            name="unique_nba_totals_actual",
        ),
        Index("idx_nba_totals_actuals_date", "game_date"),
    )

    def __repr__(self):
        return f"<NBATotalsActuals {self.away_team_name} @ {self.home_team_name}: actual={self.actual_total}>"


class NBATeamPaceEfficiency(Base):
    """
    Store enhanced team pace and efficiency metrics for totals prediction.
    Updated daily with rolling averages.
    """

    __tablename__ = "pred_nba_team_pace_efficiency"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, nullable=False)
    team_name = Column(String(100), nullable=False)
    date = Column(Date, nullable=False, index=True)

    # Pace metrics
    pace = Column(Float, nullable=True)  # Possessions per 48 minutes
    pace_rank = Column(Integer, nullable=True)
    pace_l5 = Column(Float, nullable=True)  # Last 5 games
    pace_l10 = Column(Float, nullable=True)  # Last 10 games
    home_pace = Column(Float, nullable=True)
    away_pace = Column(Float, nullable=True)

    # Offensive efficiency
    offensive_rating = Column(Float, nullable=True)  # Points per 100 possessions
    offensive_rating_rank = Column(Integer, nullable=True)
    offensive_rating_l5 = Column(Float, nullable=True)
    offensive_rating_l10 = Column(Float, nullable=True)
    points_per_game = Column(Float, nullable=True)

    # Defensive efficiency
    defensive_rating = Column(
        Float, nullable=True
    )  # Points allowed per 100 possessions
    defensive_rating_rank = Column(Integer, nullable=True)
    defensive_rating_l5 = Column(Float, nullable=True)
    defensive_rating_l10 = Column(Float, nullable=True)
    points_allowed_per_game = Column(Float, nullable=True)

    # Net rating
    net_rating = Column(Float, nullable=True)

    # Shooting metrics
    true_shooting_pct = Column(Float, nullable=True)
    effective_fg_pct = Column(Float, nullable=True)
    three_pt_rate = Column(Float, nullable=True)
    three_pt_pct = Column(Float, nullable=True)
    free_throw_rate = Column(Float, nullable=True)

    # Historical totals
    avg_game_total = Column(Float, nullable=True)  # Average combined score
    avg_home_total = Column(Float, nullable=True)
    avg_away_total = Column(Float, nullable=True)
    over_under_record = Column(String(20), nullable=True)  # e.g., "15-10"

    # Games played
    games_played = Column(Integer, nullable=True)

    # Timestamps
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("team_id", "date", name="unique_team_pace_efficiency"),
        Index("idx_team_pace_efficiency_date", "date"),
    )

    def __repr__(self):
        return f"<NBATeamPaceEfficiency {self.team_name}: pace={self.pace}, ortg={self.offensive_rating}, drtg={self.defensive_rating}>"


class NBATotalsAccuracy(Base):
    """
    Track accuracy metrics for totals predictions over time.
    """

    __tablename__ = "pred_nba_totals_accuracy"

    id = Column(Integer, primary_key=True)
    date_range_start = Column(Date, nullable=False)
    date_range_end = Column(Date, nullable=False)

    # Volume
    total_games = Column(Integer, nullable=False)

    # Error metrics
    mean_absolute_error = Column(Float, nullable=True)
    root_mean_square_error = Column(Float, nullable=True)

    # Directional accuracy
    directional_accuracy = Column(Float, nullable=True)  # % correct over/under
    over_accuracy = Column(Float, nullable=True)
    under_accuracy = Column(Float, nullable=True)

    # Value plays
    value_plays_count = Column(Integer, nullable=True)  # 3+ point edge
    value_plays_accuracy = Column(Float, nullable=True)
    value_plays_roi = Column(Float, nullable=True)

    # By edge size
    edge_1_2_count = Column(Integer, nullable=True)
    edge_1_2_accuracy = Column(Float, nullable=True)
    edge_2_3_count = Column(Integer, nullable=True)
    edge_2_3_accuracy = Column(Float, nullable=True)
    edge_3_5_count = Column(Integer, nullable=True)
    edge_3_5_accuracy = Column(Float, nullable=True)
    edge_5_plus_count = Column(Integer, nullable=True)
    edge_5_plus_accuracy = Column(Float, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_nba_totals_accuracy_dates", "date_range_start", "date_range_end"),
    )

    def __repr__(self):
        return f"<NBATotalsAccuracy {self.date_range_start} to {self.date_range_end}: MAE={self.mean_absolute_error}, Dir%={self.directional_accuracy}>"


# ============================================================================
# NBA TANK WATCH MODELS
# ============================================================================


class TankTeam(Base):
    """Tracks NBA teams for the 2026 draft tank race.

    Core entity updated after each game via NBA API polling.
    Per PRD section 9.1.
    """

    __tablename__ = "pred_tank_teams"
    id = Column(Integer, primary_key=True)

    # Team identification
    team_id = Column(String(10), unique=True, nullable=False)  # e.g., SAC, IND, BKN
    team_name = Column(String(100), nullable=False)  # e.g., Sacramento Kings
    conference = Column(String(10), nullable=False)  # Eastern or Western

    # Current record
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    win_pct = Column(Float, nullable=False, default=0.0)

    # Tank ranking (computed from worst record among pick-controlling teams)
    tank_rank = Column(Integer, nullable=True)

    # Pick status - OWN_PICK, PROTECTED, SWAP_RIGHTS, TRADED_AWAY
    pick_status = Column(String(20), nullable=False, default="OWN_PICK")

    # Protection details
    protection_type = Column(
        String(50), nullable=True
    )  # e.g., top-4, top-8, 1-4 and 10-30
    protection_safe = Column(
        Boolean, nullable=True, default=True
    )  # True if currently in protected range
    pick_destination = Column(
        String(200), nullable=True
    )  # Team(s) that receive pick if protection fails

    # Lottery odds
    lottery_odds_top1 = Column(Float, nullable=True)  # Probability of #1 overall pick
    lottery_odds_top4 = Column(Float, nullable=True)  # Probability of top-4 pick

    # Swap rights
    swap_rights_holder = Column(
        String(100), nullable=True
    )  # Team holding swap rights, if any

    # Schedule analysis
    remaining_schedule_sos = Column(
        Float, nullable=True
    )  # Strength of remaining schedule

    # Additional context
    notes = Column(Text, nullable=True)  # Additional context and trade details

    # Metadata
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return (
            f"<TankTeam #{self.tank_rank} {self.team_name} ({self.wins}-{self.losses})>"
        )


class DiscordFadeAlert(Base):
    """Tracks each live game monitored by the Discord bot.

    Manages alert state, cooldowns, and outcomes.
    Per PRD section 9.2.
    """

    __tablename__ = "pred_discord_fade_alerts"
    id = Column(Integer, primary_key=True)

    # Game identification
    game_id = Column(String(50), unique=True, nullable=False)  # From NBA/SportRadar API
    tank_team_id = Column(String(10), nullable=False)  # FK to TankTeam.team_id
    opponent_id = Column(String(10), nullable=False)  # Opponent team identifier

    # Alert tracking
    alert_count = Column(Integer, nullable=False, default=0)  # Max 2
    last_alert_at = Column(DateTime, nullable=True)  # For cooldown logic
    alert_message_id = Column(
        String(50), nullable=True
    )  # Discord message ID for threading

    # Game state
    game_status = Column(
        String(20), nullable=False, default="SCHEDULED"
    )  # SCHEDULED, LIVE, FINAL
    tank_team_score = Column(Integer, nullable=True)
    opponent_score = Column(Integer, nullable=True)
    quarter = Column(String(10), nullable=True)  # Q1, Q2, Q3, Q4, OT
    game_clock = Column(String(10), nullable=True)  # Time remaining

    # Alert state
    fade_triggered = Column(
        Boolean, nullable=False, default=False
    )  # Whether a fade alert was sent
    lead_at_alert = Column(Integer, nullable=True)  # Point lead when alert fired

    # Outcome tracking
    fade_correct = Column(
        Boolean, nullable=True
    )  # Null while live; True if tank team lost
    outcome_posted = Column(
        Boolean, nullable=False, default=False
    )  # Whether follow-up was posted

    # Metadata
    game_date = Column(Date, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_fade_alerts_game_date", "game_date"),
        Index("idx_fade_alerts_tank_team", "tank_team_id"),
    )

    def __repr__(self):
        return f"<DiscordFadeAlert {self.tank_team_id} vs {self.opponent_id} - {self.game_status}>"


class FadeSeasonTracker(Base):
    """Aggregated season-level stats for the Tank Fade strategy.

    Used for the running accuracy record displayed in Discord.
    Per PRD section 9.3.
    """

    __tablename__ = "pred_fade_season_tracker"
    id = Column(Integer, primary_key=True)

    # Season identifier
    season = Column(String(10), unique=True, nullable=False)  # e.g., 2025-26

    # Fade tracking
    total_fades = Column(
        Integer, nullable=False, default=0
    )  # Total fade alerts triggered
    correct_fades = Column(Integer, nullable=False, default=0)  # Tank team lost
    incorrect_fades = Column(Integer, nullable=False, default=0)  # Tank team won

    # Computed metrics
    fade_accuracy = Column(Float, nullable=True)  # correct_fades / total_fades

    # Lead analysis
    avg_lead_at_alert = Column(
        Float, nullable=True
    )  # Average point lead when alert fired
    avg_final_margin = Column(
        Float, nullable=True
    )  # Average final margin in faded games

    # Metadata
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<FadeSeasonTracker {self.season}: {self.correct_fades}-{self.incorrect_fades} ({self.fade_accuracy:.1%})>"


# ─── MLB GAME-LEVEL PROJECTIONS (PRD v2.0) ────────────────────────────────────


class GameProjections(Base):
    __tablename__ = "pred_game_projections"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    game_id = Column(Integer, nullable=False)

    # Teams
    home_team = Column(String(100), nullable=False)
    away_team = Column(String(100), nullable=False)
    home_team_id = Column(Integer, nullable=True)
    away_team_id = Column(Integer, nullable=True)

    # Pitchers
    home_pitcher_id = Column(String(64), nullable=True)
    home_pitcher_name = Column(String(100), nullable=True)
    away_pitcher_id = Column(String(64), nullable=True)
    away_pitcher_name = Column(String(100), nullable=True)

    # Core projections
    home_win_prob = Column(Float, nullable=False)
    away_win_prob = Column(Float, nullable=False)
    projected_total = Column(Float, nullable=False)
    home_projected_runs = Column(Float, nullable=True)
    away_projected_runs = Column(Float, nullable=True)
    run_line = Column(Float, nullable=True)

    # Confidence & market comparison
    model_confidence = Column(Float, nullable=True)
    edge_vs_market_ml = Column(Float, nullable=True)
    edge_vs_market_total = Column(Float, nullable=True)

    # Market lines (from The Odds API)
    market_home_ml = Column(Integer, nullable=True)
    market_away_ml = Column(Integer, nullable=True)
    market_total = Column(Float, nullable=True)
    market_spread = Column(Float, nullable=True)

    # Component model outputs
    xgb_win_prob = Column(Float, nullable=True)
    blowout_run_diff = Column(Float, nullable=True)

    # Feature snapshots
    home_bullpen_fatigue = Column(Float, nullable=True)
    away_bullpen_fatigue = Column(Float, nullable=True)
    park_factor = Column(Float, nullable=True)
    temperature = Column(Float, nullable=True)
    wind_speed = Column(Float, nullable=True)

    # Recommendations
    ml_recommendation = Column(String(20), nullable=True)
    total_recommendation = Column(String(20), nullable=True)
    value_rating = Column(String(20), nullable=True)

    # Venue & time
    venue_name = Column(String(100), nullable=True)
    game_time = Column(DateTime, nullable=True)

    # Metadata
    model_version = Column(String(20), nullable=True, default="v1.0")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("date", "game_id", name="unique_game_projection"),
    )

    def __repr__(self):
        return f"<GameProjections {self.date} {self.away_team}@{self.home_team} WP:{self.home_win_prob:.1%}>"


class GameActuals(Base):
    __tablename__ = "pred_game_actuals"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    game_id = Column(Integer, nullable=False)

    # Teams
    home_team = Column(String(100), nullable=False)
    away_team = Column(String(100), nullable=False)

    # Results
    home_score = Column(Integer, nullable=False)
    away_score = Column(Integer, nullable=False)
    total_runs = Column(Integer, nullable=False)
    winner = Column(String(10), nullable=False)
    run_margin = Column(Integer, nullable=False)

    # Projection comparison (denormalized for query speed)
    projected_home_win_prob = Column(Float, nullable=True)
    projected_total = Column(Float, nullable=True)
    market_total = Column(Float, nullable=True)

    # Result tracking
    ml_correct = Column(Boolean, nullable=True)
    total_correct = Column(Boolean, nullable=True)
    spread_correct = Column(Boolean, nullable=True)
    projection_error = Column(Float, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("date", "game_id", name="unique_game_actual"),)

    def __repr__(self):
        return f"<GameActuals {self.date} {self.away_team}@{self.home_team} {self.away_score}-{self.home_score}>"


class ModelAccuracy(Base):
    __tablename__ = "pred_model_accuracy"
    id = Column(Integer, primary_key=True)

    date_range_start = Column(Date, nullable=False)
    date_range_end = Column(Date, nullable=False)
    window_type = Column(String(20), nullable=False)

    # Volume
    total_games = Column(Integer, nullable=False)

    # Moneyline accuracy
    ml_correct = Column(Integer, nullable=True)
    ml_accuracy = Column(Float, nullable=True)
    brier_score = Column(Float, nullable=True)
    log_loss = Column(Float, nullable=True)

    # O/U accuracy
    total_correct = Column(Integer, nullable=True)
    total_accuracy = Column(Float, nullable=True)
    total_mae = Column(Float, nullable=True)

    # ATS / Run Line
    ats_correct = Column(Integer, nullable=True)
    ats_accuracy = Column(Float, nullable=True)

    # Edge performance
    strong_edge_count = Column(Integer, nullable=True)
    strong_edge_accuracy = Column(Float, nullable=True)
    lean_edge_count = Column(Integer, nullable=True)
    lean_edge_accuracy = Column(Float, nullable=True)

    # Market comparison
    vs_market_ml_accuracy = Column(Float, nullable=True)
    vs_market_total_accuracy = Column(Float, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "date_range_end", "window_type", name="unique_accuracy_window"
        ),
    )

    def __repr__(self):
        return f"<ModelAccuracy {self.window_type} ending {self.date_range_end}: ML {self.ml_accuracy}%>"


class BullpenFatigue(Base):
    __tablename__ = "pred_bullpen_fatigue"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    team_name = Column(String(100), nullable=False)
    team_id = Column(Integer, nullable=False)

    # Fatigue metrics
    ip_last_3_days = Column(Float, nullable=True)
    ip_last_5_days = Column(Float, nullable=True)
    ip_last_7_days = Column(Float, nullable=True)
    high_leverage_ip_last_3 = Column(Float, nullable=True)

    # Composite index (0.0 = fully rested, 1.0 = fully fatigued)
    fatigue_index = Column(Float, nullable=False)

    # Individual reliever details
    reliever_details = Column(JSON, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", "team_id", name="unique_bullpen_fatigue"),
    )

    def __repr__(self):
        return f"<BullpenFatigue {self.team_name} {self.date}: fatigue={self.fatigue_index:.2f}>"


# --------------------------------------------------------------------------- #
# Pikkit Bet Ingestion + Prop Alert Models
# --------------------------------------------------------------------------- #


class PikkitBet(Base):
    """Pikkit bet record, RDS-derived schema (preserved verbatim from
    YetiBets RDS during the YetAI migration). Primary key is pikkit_id
    (Pikkit's own bet UUID); there is no surrogate integer id column.
    """

    __tablename__ = "pred_pikkit_bets"
    pikkit_id = Column(String, primary_key=True)
    institution_id = Column(String, nullable=False)
    type = Column(String, nullable=False)  # e.g. straight, parlay
    is_sgp = Column(Boolean, nullable=True)
    is_live = Column(Boolean, nullable=True)
    is_dfs = Column(Boolean, nullable=True)
    is_future = Column(Boolean, nullable=True)
    status = Column(String, nullable=False)  # open, active, settled, etc.
    amount = Column(Numeric(10, 2), nullable=False)  # stake
    amount_units = Column(Numeric(10, 4), nullable=True)
    profit = Column(Numeric(10, 2), nullable=True)
    profit_units = Column(Numeric(10, 4), nullable=True)
    odds = Column(Numeric(12, 4), nullable=False)
    promo_info = Column(JSONB, nullable=True)
    placed_at = Column(DateTime(timezone=True), nullable=True)
    settled_at = Column(DateTime(timezone=True), nullable=True)
    raw = Column(JSONB, nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=False)

    def __repr__(self):
        return f"<PikkitBet {self.pikkit_id} {self.status}>"


class PikkitPick(Base):
    """Pikkit pick (leg) record, RDS-derived schema. Primary key is pikkit_id
    (Pikkit's own pick UUID). bet_id FKs to PikkitBet.pikkit_id.
    """

    __tablename__ = "pred_pikkit_picks"
    pikkit_id = Column(String, primary_key=True)
    bet_id = Column(String, ForeignKey("pred_pikkit_bets.pikkit_id"), nullable=False)
    pick_name = Column(Text, nullable=False)  # e.g. "Over 0.5 - Ohtani HR"
    status = Column(String, nullable=False)
    odds = Column(Numeric(12, 4), nullable=False)
    sport_id = Column(String, nullable=False)
    league_id = Column(String, nullable=False)
    event_id = Column(String, nullable=False)
    market_id = Column(String, nullable=False)
    outcome_id = Column(String, nullable=False)
    team_id = Column(String, nullable=True)
    player_id = Column(String, nullable=True)
    event_starts_at = Column(DateTime(timezone=True), nullable=True)
    event_is_final = Column(Boolean, nullable=True)

    def __repr__(self):
        return f"<PikkitPick {self.pikkit_id} {self.pick_name}>"


class PropMarketDefinition(Base):
    __tablename__ = "pred_prop_market_definitions"
    market_id = Column(String(100), primary_key=True)
    sport_id = Column(String(20), nullable=False, default="mlb")
    display_name = Column(String(100), nullable=False)  # e.g. "Home Runs"
    stat_key = Column(String(50), nullable=False)  # e.g. "home_runs"
    side = Column(String(10), nullable=False)  # 'batter' or 'pitcher'
    active = Column(Boolean, nullable=False, default=True)

    def __repr__(self):
        return f"<PropMarketDefinition {self.display_name} ({self.stat_key})>"


class PropAlertLog(Base):
    __tablename__ = "pred_prop_alert_log"
    id = Column(Integer, primary_key=True)
    pick_id = Column(String(100), nullable=False, index=True)
    game_pk = Column(Integer, nullable=False)
    play_id = Column(String(50), nullable=False)
    alert_type = Column(
        String(30), nullable=False
    )  # threshold_cleared, progress, under_killed
    stat_count = Column(Float, nullable=False)
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    discord_message_id = Column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint("pick_id", "play_id", "alert_type", name="unique_prop_alert"),
    )
