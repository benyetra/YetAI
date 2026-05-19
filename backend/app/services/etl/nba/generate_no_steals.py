"""Qualitative 'no steals' prop picks — port of YetiBets no_steals.py."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal
from app.models.predictions_models import (
    NoStealsActuals,
    NoStealsProjections,
    PlayerCareerData,
    RecentGames,
    TeamOffenseStats,
    TeamRoster,
    TodayActivePlayers,
)
from app.services.etl.nba._espn import now_eastern

logger = logging.getLogger(__name__)

db = None


def _today():
    return now_eastern().date()


def fetch_recent_data(player_id, limit=5):
    """
    Fetch recent game data for a player, limited by the number of games.
    """
    try:
        recent_games = (
            db.query(RecentGames).filter_by(player_id=player_id)
            .order_by(RecentGames.game_date.desc())
            .limit(limit)
            .all()
        )
        logger.info(f"Fetched {len(recent_games)} recent games for player {player_id}.")
        return recent_games
    except SQLAlchemyError as e:
        logger.error(f"Error fetching recent games for player {player_id}: {e}")
        return []

def fetch_historical_matchup_data(player_id, opponent_team_id, limit=5):
    """
    Fetch historical matchups between the player and the opponent team.
    """
    try:
        historical_games = (
            db.query(RecentGames).filter_by(player_id=player_id, opponent_team_id=opponent_team_id)
            .order_by(RecentGames.game_date.desc())
            .limit(limit)
            .all()
        )
        logger.info(f"Fetched {len(historical_games)} historical matchups for player {player_id} against team {opponent_team_id}.")
        return historical_games
    except SQLAlchemyError as e:
        logger.error(f"Error fetching historical matchups for player {player_id}: {e}")
        return []

def get_position_multiplier(position):
    """
    Adjust steal expectations based on player position.
    Guards generate significantly more steals than big men.

    Args:
        position: Player position string (e.g., 'PG', 'SG', 'SF', 'PF', 'C', or combos like 'PG-SG')

    Returns:
        Float: Position multiplier (0.6 to 1.3)
    """
    if not position:
        return 1.0

    multipliers = {
        'PG': 1.3,   # Point guards get most steals (handle ball most, pressure ball-handlers)
        'SG': 1.2,   # Shooting guards (still in passing lanes)
        'SF': 1.0,   # Small forwards (baseline)
        'PF': 0.7,   # Power forwards (less perimeter defense)
        'C': 0.6     # Centers get fewest steals (not in passing lanes)
    }

    # Handle combo positions like 'PG-SG' or 'F-C'
    if '-' in position:
        positions = position.split('-')
        valid_positions = [p.strip() for p in positions if p.strip() in multipliers]
        if valid_positions:
            return sum(multipliers[p] for p in valid_positions) / len(valid_positions)

    # Handle generic positions like 'G' (guard) or 'F' (forward)
    if position == 'G':
        return 1.25  # Average of PG and SG
    elif position == 'F':
        return 0.85  # Average of SF and PF

    return multipliers.get(position, 1.0)

def get_advanced_defensive_profile(recent_games):
    """
    Calculate player's defensive engagement level using advanced metrics.
    Players who are engaged defensively (good ratings, rebounding, impact) generate more steals.

    Args:
        recent_games: List of RecentGames objects

    Returns:
        Float: Defensive engagement multiplier (0.7 to 1.3)
    """
    if not recent_games or len(recent_games) == 0:
        return 1.0

    # Filter games with actual data
    games_with_data = [g for g in recent_games if g.minutes and g.minutes > 5]
    if not games_with_data:
        return 1.0

    # 1. Defensive Rating (lower is better - points allowed per 100 possessions)
    defensive_ratings = [g.defensive_rating for g in games_with_data if g.defensive_rating]
    if defensive_ratings:
        avg_def_rating = sum(defensive_ratings) / len(defensive_ratings)
        # NBA average is ~110-115, excellent is <105, poor is >118
        # Better defense = more steals
        rating_factor = 115 / max(avg_def_rating, 95)  # Cap to avoid extreme values
        rating_factor = max(0.8, min(rating_factor, 1.2))  # Bound between 0.8 and 1.2
    else:
        rating_factor = 1.0

    # 2. Plus/Minus (positive = winning player, correlates with good defense)
    plus_minus_values = [g.plus_minus for g in games_with_data if g.plus_minus is not None]
    if plus_minus_values:
        avg_plus_minus = sum(plus_minus_values) / len(plus_minus_values)
        # Convert to factor: +10 = 1.05, -10 = 0.95, cap at ±20
        plus_minus_factor = 1.0 + (max(-20, min(avg_plus_minus, 20)) / 200)  # Small adjustment
    else:
        plus_minus_factor = 1.0

    # 3. Defensive Rebound Percentage (engaged defenders fight for rebounds AND steals)
    def_reb_pcts = [g.defensive_rebound_percentage for g in games_with_data if g.defensive_rebound_percentage]
    if def_reb_pcts:
        avg_def_reb_pct = sum(def_reb_pcts) / len(def_reb_pcts)
        # Good defensive rebounders: 15-25%, excellent: >25%
        # This shows defensive engagement
        rebound_factor = 1.0 + ((avg_def_reb_pct - 15) / 100)  # Normalize around 15%
        rebound_factor = max(0.9, min(rebound_factor, 1.15))  # Bound
    else:
        rebound_factor = 1.0

    # 4. Usage Percentage (higher usage = more time with ball = more steal opportunities)
    usage_pcts = [g.usage_percentage for g in games_with_data if g.usage_percentage]
    if usage_pcts:
        avg_usage = sum(usage_pcts) / len(usage_pcts)
        # Higher usage players are more involved, see more action
        # NBA average usage: ~20%, stars: >28%
        usage_factor = 1.0 + ((avg_usage - 20) / 100)  # Small boost for high usage
        usage_factor = max(0.95, min(usage_factor, 1.1))  # Bound
    else:
        usage_factor = 1.0

    # Combine all factors with weights
    # Defensive rating is most important, then rebounding (shows engagement), then plus/minus, then usage
    defensive_engagement = (
        0.4 * rating_factor +
        0.3 * rebound_factor +
        0.2 * plus_minus_factor +
        0.1 * usage_factor
    )

    # Final bounds
    defensive_engagement = max(0.7, min(defensive_engagement, 1.3))

    logger.info(f"Defensive profile: rating={rating_factor:.3f}, reb={rebound_factor:.3f}, "
               f"plus_minus={plus_minus_factor:.3f}, usage={usage_factor:.3f}, "
               f"final={defensive_engagement:.3f}")

    return defensive_engagement

def get_opponent_ball_handling_factor(opponent_team_id, opponent_offense_stats):
    """
    Calculate how sloppy the opponent is with the ball based on assist-to-turnover ratio.
    Not all turnovers are stealable (travels, offensive fouls, etc.), so we focus on
    ball-handling quality.

    Args:
        opponent_team_id: Opponent team ID
        opponent_offense_stats: TeamOffenseStats object

    Returns:
        Float: Ball-handling sloppiness factor (0.7 to 1.5)
    """
    try:
        # Get opponent players' recent games to calculate team A/TO ratio
        opponent_roster = db.query(TeamRoster).filter_by(team_id=opponent_team_id).all()
        if not opponent_roster:
            logger.warning(f"No roster found for opponent team {opponent_team_id}")
            return 1.0

        opponent_player_ids = [p.player_id for p in opponent_roster]

        # Get recent games for opponent's players (last 10 games per player, roughly 2 weeks of team data)
        recent_opponent_games = (
            db.query(RecentGames)
            .filter(RecentGames.player_id.in_(opponent_player_ids))
            .order_by(RecentGames.game_date.desc())
            .limit(50)  # Get enough data for team aggregate
            .all()
        )

        if not recent_opponent_games:
            logger.warning(f"No recent games for opponent team {opponent_team_id}")
            return 1.0

        # Calculate team's collective A/TO ratio
        total_assists = sum(g.assists or 0 for g in recent_opponent_games)
        total_turnovers = sum(g.turnovers or 0 for g in recent_opponent_games)

        if total_turnovers == 0:
            logger.info(f"Opponent team {opponent_team_id} has 0 turnovers (very careful)")
            return 0.8  # Very careful team, fewer steal opportunities

        team_ato_ratio = total_assists / total_turnovers

        # NBA league average A/TO ratio is approximately 1.4-1.6
        # Higher ratio = better ball-handling = fewer steals
        # Lower ratio = sloppy ball-handling = more steals
        LEAGUE_AVG_ATO = 1.5

        # Calculate factor: lower ratio increases steal opportunities
        ball_handling_factor = LEAGUE_AVG_ATO / max(team_ato_ratio, 0.8)  # Avoid division issues

        # Bound the factor to reasonable range
        ball_handling_factor = max(0.7, min(ball_handling_factor, 1.5))

        # Also consider raw assists (high assists = good passers = harder to steal from)
        assists_per_game = opponent_offense_stats.assists_per_game if opponent_offense_stats.assists_per_game else 25
        if assists_per_game > 28:  # Elite passing team
            ball_handling_factor *= 0.95  # Slightly reduce steal opportunities
        elif assists_per_game < 22:  # Poor passing team
            ball_handling_factor *= 1.05  # Slightly increase steal opportunities

        logger.info(f"Opponent A/TO ratio: {team_ato_ratio:.2f}, ball_handling_factor: {ball_handling_factor:.3f}")

        return ball_handling_factor

    except Exception as e:
        logger.error(f"Error calculating opponent ball handling factor: {e}")
        return 1.0

def calculate_weighted_steals_per_min(recent_games):
    """
    Calculate steals per minute with recency weighting.
    More recent games are weighted more heavily as they better reflect current form.

    Args:
        recent_games: List of RecentGames objects (ordered by date descending)

    Returns:
        Float: Weighted steals per minute
    """
    if not recent_games:
        return 0

    total_weighted_steals = 0
    total_weighted_minutes = 0
    total_weight = 0

    num_games = len(recent_games)

    for i, game in enumerate(recent_games):
        # Exponential weighting: most recent game gets highest weight
        # Formula: 0.5 + (0.5 / n) * (n - i - 1)
        # This gives weights like: [1.0, 0.9, 0.8, 0.7, 0.6] for 5 games
        weight = 0.5 + (0.5 / num_games) * (num_games - i - 1)

        steals = game.steals or 0
        minutes = game.minutes or 0

        total_weighted_steals += steals * weight
        total_weighted_minutes += minutes * weight
        total_weight += weight

    if total_weighted_minutes == 0:
        return 0

    weighted_steals_per_min = total_weighted_steals / total_weighted_minutes

    logger.info(f"Weighted steals/min: {weighted_steals_per_min:.4f} "
               f"(vs simple avg: {sum(g.steals or 0 for g in recent_games) / max(sum(g.minutes or 0 for g in recent_games), 1):.4f})")

    return weighted_steals_per_min

def get_combined_pace_factor(player_team_id, opponent_pace):
    """
    Calculate game pace factor using both teams' pace.
    Faster games create more possessions and more steal opportunities for both teams.

    Args:
        player_team_id: Player's team ID
        opponent_pace: Opponent's pace from TeamOffenseStats

    Returns:
        Float: Combined pace factor relative to league average
    """
    try:
        # Get player's team recent games to determine their pace
        team_roster = db.query(TeamRoster).filter_by(team_id=player_team_id).limit(5).all()
        if not team_roster:
            logger.warning(f"No roster found for player team {player_team_id}")
            return opponent_pace / 100.0

        team_player_ids = [p.player_id for p in team_roster]

        # Get recent team games
        recent_team_games = (
            db.query(RecentGames)
            .filter(RecentGames.player_id.in_(team_player_ids))
            .order_by(RecentGames.game_date.desc())
            .limit(20)  # Get recent games
            .all()
        )

        if recent_team_games:
            # Filter for games with pace data
            paces = [g.pace for g in recent_team_games if g.pace and g.pace > 0]
            if paces:
                player_team_pace = sum(paces) / len(paces)
                logger.info(f"Player team pace: {player_team_pace:.1f}")
            else:
                player_team_pace = 100.0  # League average default
                logger.info(f"No pace data for player team, using league average")
        else:
            player_team_pace = 100.0
            logger.info(f"No recent games for player team, using league average pace")

        # Average both teams' pace to get expected game pace
        # When fast team plays slow team, actual pace is between both
        expected_game_pace = (player_team_pace + opponent_pace) / 2.0

        # Normalize to league average (100)
        pace_factor = expected_game_pace / 100.0

        logger.info(f"Combined pace factor: {pace_factor:.3f} "
                   f"(player: {player_team_pace:.1f}, opponent: {opponent_pace:.1f}, game: {expected_game_pace:.1f})")

        return pace_factor

    except Exception as e:
        logger.error(f"Error calculating combined pace factor: {e}")
        # Fallback to just opponent pace
        return opponent_pace / 100.0 if opponent_pace else 1.0

def calculate_no_steals_probability(player_career, recent_games, opponent_offense_stats, historical_matchups, avg_minutes,
                                   player_position, player_team_id, opponent_team_id):
    """
    Calculate the probability of a player recording no steals in the game.
    Now includes Tier 1 improvements: position context, advanced defensive metrics,
    opponent ball-handling analysis, recency weighting, and combined pace factors.

    Args:
        player_career: PlayerCareerData object
        recent_games: List of RecentGames objects (ordered by date descending)
        opponent_offense_stats: TeamOffenseStats object
        historical_matchups: List of historical RecentGames against this opponent
        avg_minutes: Average minutes played in recent games
        player_position: Player's position (e.g., 'PG', 'SG', 'SF', etc.)
        player_team_id: Player's team ID
        opponent_team_id: Opponent's team ID

    Returns:
        Float: Probability of recording zero steals (0.0 to 1.0)
    """
    try:
        logger.info(f"=== Starting steal probability calculation ===")

        # ========== TIER 1 IMPROVEMENT #4: Recency Weighting ==========
        # Use weighted average for recent games (most recent = higher weight)
        recent_steals_per_min = calculate_weighted_steals_per_min(recent_games)

        # Fallback to career if no recent data
        career_steals_per_min = (
            (player_career.steals / player_career.minutes)
            if player_career and player_career.minutes and player_career.minutes > 0 else 0
        )

        if recent_steals_per_min == 0:
            logger.warning(f"Player has 0 weighted steals/min in recent games, using career average")
            recent_steals_per_min = career_steals_per_min

        # Validate historical matchup stats - Check for division by zero and minimum sample size
        total_matchup_minutes = sum(game.minutes or 0 for game in historical_matchups)
        if not historical_matchups or len(historical_matchups) < 2 or total_matchup_minutes == 0:
            # Not enough matchup data, use recent stats
            matchup_steals_per_min = recent_steals_per_min
            weight_matchup = 0  # Don't weight unreliable matchup data
            weight_recent = 0.7
            weight_career = 0.3
            logger.info(f"Insufficient matchup data, adjusting weights: career={weight_career}, recent={weight_recent}")
        else:
            # Use weighted average for matchups too
            matchup_steals_per_min = calculate_weighted_steals_per_min(historical_matchups)
            weight_career = 0.3
            weight_recent = 0.5
            weight_matchup = 0.2
            logger.info(f"Using all three sources: career={weight_career}, recent={weight_recent}, matchup={weight_matchup}")

        # Weighted average of career, recent, and matchup stats
        base_steals_per_min = (
            weight_career * career_steals_per_min +
            weight_recent * recent_steals_per_min +
            weight_matchup * matchup_steals_per_min
        )

        logger.info(f"Base steals/min: {base_steals_per_min:.4f} "
                   f"(career: {career_steals_per_min:.4f}, recent: {recent_steals_per_min:.4f}, "
                   f"matchup: {matchup_steals_per_min:.4f})")

        # ========== TIER 1 IMPROVEMENT #1: Position Context ==========
        position_factor = get_position_multiplier(player_position)
        logger.info(f"Position: {player_position}, Position factor: {position_factor:.2f}")

        # ========== TIER 1 IMPROVEMENT #2: Advanced Defensive Metrics ==========
        defensive_engagement = get_advanced_defensive_profile(recent_games)

        # ========== TIER 1 IMPROVEMENT #3: Opponent Ball-Handling Analysis ==========
        ball_handling_factor = get_opponent_ball_handling_factor(opponent_team_id, opponent_offense_stats)

        # Opponent factors - use league averages as defaults
        LEAGUE_AVG_TURNOVERS = 14.0
        LEAGUE_AVG_PACE = 100.0

        opponent_turnovers = opponent_offense_stats.turnovers_per_game if opponent_offense_stats.turnovers_per_game else LEAGUE_AVG_TURNOVERS
        opponent_pace = opponent_offense_stats.pace if opponent_offense_stats.pace else LEAGUE_AVG_PACE

        # Basic turnover factor (still useful for raw volume)
        turnover_factor = opponent_turnovers / LEAGUE_AVG_TURNOVERS

        # ========== TIER 1 IMPROVEMENT #5: Combined Pace Factor ==========
        pace_factor = get_combined_pace_factor(player_team_id, opponent_pace)

        # ========== CALCULATE EXPECTED STEALS WITH ALL TIER 1 FACTORS ==========
        expected_steals = (
            base_steals_per_min *          # Base steal rate
            avg_minutes *                   # Expected playing time
            position_factor *               # Position adjustment (guards > big men)
            defensive_engagement *          # How defensively engaged the player is
            turnover_factor *               # Raw turnover volume
            ball_handling_factor *          # Opponent's ball-handling quality
            pace_factor                     # Game pace from both teams
        )

        # Use Poisson distribution to calculate the probability of zero steals
        from scipy.stats import poisson
        probability_no_steals = poisson.pmf(0, expected_steals)

        # Ensure probability is between 0 and 1
        probability_no_steals = max(0, min(probability_no_steals, 1))

        logger.info(f"=== TIER 1 CALCULATION SUMMARY ===")
        logger.info(f"Base steals/min: {base_steals_per_min:.4f}")
        logger.info(f"Expected minutes: {avg_minutes:.1f}")
        logger.info(f"Position factor ({player_position}): {position_factor:.3f}")
        logger.info(f"Defensive engagement: {defensive_engagement:.3f}")
        logger.info(f"Turnover factor: {turnover_factor:.3f}")
        logger.info(f"Ball-handling factor: {ball_handling_factor:.3f}")
        logger.info(f"Pace factor: {pace_factor:.3f}")
        logger.info(f"Expected steals: {expected_steals:.3f}")
        logger.info(f"Probability NO steals: {probability_no_steals:.3f}")
        logger.info(f"=====================================")

        return round(probability_no_steals, 2)
    except Exception as e:
        logger.error(f"Error calculating no steals probability: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0

def project_no_steals():
    """
    Project the probability of players recording no steals for today's games.
    Save only players with a probability > 80% and an average of 17+ minutes played.
    """
    today = _today()
    try:
        players = db.query(TodayActivePlayers).filter_by(game_date=today).all()
        logger.info(f"Found {len(players)} active players for {today}.")
    except SQLAlchemyError as e:
        logger.error(f"Error fetching today's active players: {e}")
        return

    # Determine current season (e.g., "2024-25")
    current_year = today.year
    current_month = today.month
    if current_month >= 10:  # NBA season starts in October
        current_season = f"{current_year}-{str(current_year + 1)[-2:]}"
    else:
        current_season = f"{current_year - 1}-{str(current_year)[-2:]}"

    projections = []
    for player in players:
        try:
            # Fetch career data for current season only
            player_career = (db.query(PlayerCareerData)
                           .filter_by(player_id=player.player_id, season=current_season)
                           .first())
            if not player_career:
                logger.warning(f"No current season ({current_season}) career data found for player {player.player_id}. Skipping.")
                continue

            # Validate career data freshness (updated within last 7 days)
            if player_career.last_updated:
                days_since_update = (datetime.datetime.now() - player_career.last_updated).days
                if days_since_update > 7:
                    logger.warning(f"Player {player.player_id} career data is {days_since_update} days old. Proceeding with caution.")

            # Fetch recent game data
            recent_games = fetch_recent_data(player.player_id)
            if not recent_games:
                logger.warning(f"No recent game data found for player {player.player_id}. Skipping.")
                continue

            # Validate recent games are actually recent (within last 30 days)
            most_recent_game_date = max(game.game_date for game in recent_games)
            days_since_last_game = (today - most_recent_game_date).days
            if days_since_last_game > 30:
                logger.warning(f"Player {player.player_id} hasn't played in {days_since_last_game} days. Skipping.")
                continue
            elif days_since_last_game > 7:
                logger.info(f"Player {player.player_id} last played {days_since_last_game} days ago. Proceeding with caution.")

            # Calculate average minutes played in recent games
            avg_minutes = sum(game.minutes or 0 for game in recent_games) / len(recent_games)

            # Skip players with average minutes < 17
            if avg_minutes < 17:
                logger.info(f"Player {player.player_id} has average minutes {avg_minutes:.2f}, skipping.")
                continue

            # Fetch historical matchup data
            historical_matchups = fetch_historical_matchup_data(player.player_id, player.opponent_team_id)

            # Fetch opponent offensive stats
            opponent_offense_stats = db.query(TeamOffenseStats).filter_by(team_id=player.opponent_team_id).first()
            if not opponent_offense_stats:
                logger.warning(f"No offensive stats found for opponent team {player.opponent_team_id}. Skipping.")
                continue

            # Note: TeamOffenseStats doesn't have last_updated field, so we can't validate freshness
            # This should be added to the model in the future for data quality validation

            # Get player position from TodayActivePlayers or TeamRoster
            player_position = player.position  # From TodayActivePlayers
            if not player_position:
                # Fallback to TeamRoster
                roster_entry = db.query(TeamRoster).filter_by(player_id=player.player_id).first()
                player_position = roster_entry.position if roster_entry else None

            if not player_position:
                logger.warning(f"No position found for player {player.player_id}, using default factor")

            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {player.player_name} ({player_position}) vs {player.opponent_team_name}")
            logger.info(f"{'='*60}")

            # Calculate probability of no steals with TIER 1 improvements
            probability_no_steals = calculate_no_steals_probability(
                player_career=player_career,
                recent_games=recent_games,
                opponent_offense_stats=opponent_offense_stats,
                historical_matchups=historical_matchups,
                avg_minutes=avg_minutes,
                player_position=player_position,
                player_team_id=player.team_id,
                opponent_team_id=player.opponent_team_id
            )

            # Skip players with probability <= 80%
            if probability_no_steals <= 0.80:
                logger.info(f"Player {player.player_id} has no steals probability {probability_no_steals:.2f}, skipping.")
                continue

            # Prepare projection
            projection = NoStealsProjections(
                date=today,
                player_id=player.player_id,
                player_name=player.player_name,
                opponent_team_name=player.opponent_team_name,
                probability_no_steals=probability_no_steals,
            )
            projections.append(projection)
            logger.info(f"Player {player.player_id} added with probability {probability_no_steals:.2f} and avg minutes {avg_minutes:.2f}.")
        except Exception as e:
            logger.error(f"Error processing player {player.player_id}: {e}")
            continue

    # Save projections to database
    try:
        db.bulk_save_objects(projections)
        db.commit()
        logger.info(f"Saved {len(projections)} no steals projections for {today}.")
    except SQLAlchemyError as e:
        logger.error(f"Error saving projections to database: {e}")

def fetch_yesterdays_games():
    """
    Fetch games from yesterday.
    """
    yesterday = _today() - datetime.timedelta(days=1)
    try:
        players = db.query(TodayActivePlayers).filter_by(game_date=yesterday).all()
        logger.info(f"Found {len(players)} players for yesterday ({yesterday}).")
        return players
    except SQLAlchemyError as e:
        logger.error(f"Error fetching yesterday's games: {e}")
        return []

def save_yesterdays_results():
    """
    Compare yesterday's predictions with actual results and store them.
    """
    yesterday = _today() - datetime.timedelta(days=1)
    players = fetch_yesterdays_games()
    if not players:
        logger.warning(f"No players found for yesterday ({yesterday}).")
        return

    results = []
    for player in players:
        try:
            # Fetch yesterday's prediction
            prediction = db.query(NoStealsProjections).filter_by(date=yesterday, player_id=player.player_id).first()
            if not prediction:
                logger.warning(f"No prediction found for player {player.player_id} on {yesterday}. Skipping.")
                continue

            # Fetch actual stats
            recent_game = db.query(RecentGames).filter_by(player_id=player.player_id, game_date=yesterday).first()
            if not recent_game:
                logger.warning(f"No actual game data found for player {player.player_id} on {yesterday}. Skipping.")
                continue

            # Determine if the player had no steals
            actual_no_steals = recent_game.steals == 0

            # We predict "no steals" when probability > 0.5
            # Since we only save predictions with probability > 0.80, all predictions are "no steals"
            # Correct prediction means: we predicted no steals AND player actually got no steals
            predicted_no_steals = prediction.probability_no_steals > 0.5
            correct_prediction = (actual_no_steals == predicted_no_steals)

            # Additional metrics for analysis
            # For high-confidence predictions (>0.80), we expect high accuracy
            confidence_level = "very_high" if prediction.probability_no_steals >= 0.90 else "high"

            # Save result
            result = NoStealsActuals(
                date=yesterday,
                player_id=player.player_id,
                player_name=player.player_name,
                opponent_team_name=player.opponent_team_name,
                actual_no_steals=actual_no_steals,
                probability_no_steals=prediction.probability_no_steals,
                correct_prediction=correct_prediction,
            )

            results.append(result)
            logger.info(f"Player {player.player_id} ({player.player_name}): "
                       f"Predicted={prediction.probability_no_steals:.2f} ({confidence_level}), "
                       f"Actual={'No steals' if actual_no_steals else f'{recent_game.steals} steals'}, "
                       f"Correct={correct_prediction}")
        except Exception as e:
            logger.error(f"Error processing result for player {player.player_id}: {e}")
            continue

    # Save results to database
    try:
        db.bulk_save_objects(results)
        db.commit()
        logger.info(f"Saved {len(results)} results for yesterday ({yesterday}).")
    except SQLAlchemyError as e:
        logger.error(f"Error saving results to database: {e}")



def store_no_steals_actuals() -> dict:
    global db
    db = SessionLocal()
    try:
        save_yesterdays_results()
        return {"status": "ok"}
    finally:
        db.close()


def run() -> dict:
    global db
    db = SessionLocal()
    try:
        save_yesterdays_results()
        project_no_steals()
        count = db.query(NoStealsProjections).filter(
            NoStealsProjections.date == _today()
        ).count()
        return {"status": "ok", "date": _today().isoformat(), "projections": count}
    finally:
        db.close()
