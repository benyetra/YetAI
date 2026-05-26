"""MLB Game Projection Pipeline Orchestrator.

Runs the full game-level prediction pipeline:
1. Compute bullpen fatigue for all teams
2. Fetch current injury data
3. Build game features and generate predictions
4. Fetch market odds for comparison
5. Compute edge vs market and value ratings
6. Store projections in GameProjections table

PRD v2.0 §7.2 — Enhanced Pipeline Architecture.
"""

import sys
import os

import argparse
import logging
import math
from datetime import date, datetime
import requests
from sqlalchemy import text

from app.models.predictions_models import GameProjections, GameActuals

from app.services.etl.mlb._db import db_session
from app.services.etl.mlb.odds_utils import american_to_break_even_prob
from app.services.ml_model_version import (
    attach_model_version,
    resolve_mlb_game_projection_model_version,
)


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
SPORT = "baseball_mlb"
BASE_URL = "https://api.the-odds-api.com/v4/sports/"


def fetch_game_odds():
    """Fetch moneyline, totals, and spreads from The Odds API for today's games.

    Returns dict keyed by "Away @ Home" with odds data.
    """
    if not ODDS_API_KEY:
        logger.warning("No ODDS_API_KEY set, skipping odds fetch")
        return {}

    try:
        url = f"{BASE_URL}{SPORT}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "h2h,totals,spreads",
            "bookmakers": "fanduel,fanatics",
            "oddsFormat": "american",
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch odds: {e}")
        return {}

    odds_map = {}
    today_iso = date.today().isoformat()

    for event in events:
        commence = event.get("commence_time", "")
        if not commence.startswith(today_iso):
            continue

        key = f"{event['away_team']} @ {event['home_team']}"
        odds_data = {"h2h": {}, "totals": {}, "spreads": {}}

        for bm in event.get("bookmakers", []):
            for market in bm.get("markets", []):
                mkey = market.get("key", "")
                if mkey == "h2h":
                    for outcome in market.get("outcomes", []):
                        odds_data["h2h"][outcome["name"]] = outcome["price"]
                elif mkey == "totals":
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == "Over":
                            odds_data["totals"]["over"] = outcome["price"]
                            odds_data["totals"]["point"] = outcome.get("point")
                        elif outcome["name"] == "Under":
                            odds_data["totals"]["under"] = outcome["price"]
                elif mkey == "spreads":
                    for outcome in market.get("outcomes", []):
                        odds_data["spreads"][outcome["name"]] = {
                            "price": outcome["price"],
                            "point": outcome.get("point"),
                        }

        odds_map[key] = odds_data
        # Also store with reversed key for lookup flexibility
        alt_key = f"{event['home_team']} vs {event['away_team']}"
        odds_map[alt_key] = odds_data

    logger.info(f"Fetched odds for {len(odds_map) // 2} games")
    return odds_map


def compute_edge_and_value(prediction, odds_data):
    """Compute edge vs market and assign value rating.

    Args:
        prediction: dict with home_win_prob, projected_total, etc.
        odds_data: dict with h2h, totals, spreads from odds API

    Returns:
        dict with edge_vs_market_ml, edge_vs_market_total, market odds,
        ml_recommendation, total_recommendation, value_rating, model_confidence
    """
    result = {
        "edge_vs_market_ml": None,
        "edge_vs_market_total": None,
        "market_home_ml": None,
        "market_away_ml": None,
        "market_total": None,
        "market_spread": None,
        "ml_recommendation": "NO_PLAY",
        "spread_recommendation": "NO_PLAY",
        "total_recommendation": "NO_PLAY",
        "value_rating": "No Edge",
        "model_confidence": 0.5,
    }

    home_prob = prediction["home_win_prob"]
    proj_total = prediction["projected_total"]

    # Moneyline edge
    h2h = odds_data.get("h2h", {})
    home_ml = h2h.get(prediction["home_team"])
    away_ml = h2h.get(prediction["away_team"])

    if home_ml is not None:
        result["market_home_ml"] = home_ml
        market_home_prob = american_to_break_even_prob(home_ml)
        result["edge_vs_market_ml"] = round(home_prob - market_home_prob, 4)
    if away_ml is not None:
        result["market_away_ml"] = away_ml

    # Total edge
    totals = odds_data.get("totals", {})
    market_total = totals.get("point")
    if market_total is not None:
        result["market_total"] = float(market_total)
        result["edge_vs_market_total"] = round(proj_total - float(market_total), 1)

    # Spread
    spreads = odds_data.get("spreads", {})
    home_spread = spreads.get(prediction["home_team"], {})
    if home_spread:
        result["market_spread"] = home_spread.get("point")

    # ML recommendation
    edge_ml = result["edge_vs_market_ml"]
    if edge_ml is not None:
        if edge_ml > 0.03:
            result["ml_recommendation"] = "HOME"
        elif edge_ml < -0.03:
            result["ml_recommendation"] = "AWAY"

    # Total recommendation
    edge_total = result["edge_vs_market_total"]
    if edge_total is not None:
        if edge_total > 0.5:
            result["total_recommendation"] = "OVER"
        elif edge_total < -0.5:
            result["total_recommendation"] = "UNDER"

    from app.services.mlb_game_picks import spread_recommendation

    spread_side = spread_recommendation(
        prediction.get("run_line"),
        result.get("market_spread"),
    )
    if spread_side:
        result["spread_recommendation"] = spread_side

    # Model confidence: based on probability extremity and edge magnitude
    prob_confidence = abs(home_prob - 0.5) * 2.0  # 0.0 at 50/50, 1.0 at 100%
    edge_confidence = min(abs(edge_ml or 0) / 0.10, 1.0)  # Normalize to max 10% edge
    result["model_confidence"] = round(0.6 * prob_confidence + 0.4 * edge_confidence, 3)

    # Value rating
    conf = result["model_confidence"]
    edge = abs(edge_ml or 0)
    if edge >= 0.05 and conf >= 0.6:
        result["value_rating"] = "Strong"
    elif edge >= 0.02 and conf >= 0.4:
        result["value_rating"] = "Lean"
    else:
        result["value_rating"] = "No Edge"

    return result


def store_game_projections(predictions, target_date=None, *, model_version=None):
    """Upsert game projections into the database."""
    if target_date is None:
        target_date = date.today()

    if model_version is None:
        from app.services.etl.mlb.game_model import load_model

        model_version = resolve_mlb_game_projection_model_version(
            win_model=load_model("win"),
            allow_network=os.getenv("ML_MODEL_VERSION_ALLOW_S3", "1") == "1",
        )

    if any(p.get("sim_distribution") for p in predictions):
        from app.services.ml_model_version import normalize_model_version

        base = (model_version or "heuristic-v1")[:15]
        tagged = f"{base}+mc"
        model_version = normalize_model_version(tagged)

    stored = 0
    for pred in predictions:
        existing = (
            db_session.query(GameProjections)
            .filter_by(date=target_date, game_id=pred["game_id"])
            .first()
        )

        if existing:
            # Update existing projection
            for key, val in pred.items():
                if key not in ("game_id",) and hasattr(existing, key):
                    setattr(existing, key, val)
            attach_model_version(existing, model_version)
            existing.updated_at = datetime.utcnow()
        else:
            proj = GameProjections(
                date=target_date,
                game_id=pred["game_id"],
                home_team=pred["home_team"],
                away_team=pred["away_team"],
                home_team_id=pred.get("home_team_id"),
                away_team_id=pred.get("away_team_id"),
                home_pitcher_id=pred.get("home_pitcher_id"),
                home_pitcher_name=pred.get("home_pitcher_name"),
                away_pitcher_id=pred.get("away_pitcher_id"),
                away_pitcher_name=pred.get("away_pitcher_name"),
                home_win_prob=pred["home_win_prob"],
                away_win_prob=pred["away_win_prob"],
                projected_total=pred["projected_total"],
                home_projected_runs=pred.get("home_projected_runs"),
                away_projected_runs=pred.get("away_projected_runs"),
                run_line=pred.get("run_line"),
                model_confidence=pred.get("model_confidence"),
                edge_vs_market_ml=pred.get("edge_vs_market_ml"),
                edge_vs_market_total=pred.get("edge_vs_market_total"),
                market_home_ml=pred.get("market_home_ml"),
                market_away_ml=pred.get("market_away_ml"),
                market_total=pred.get("market_total"),
                market_spread=pred.get("market_spread"),
                xgb_win_prob=pred.get("xgb_win_prob"),
                blowout_run_diff=pred.get("blowout_run_diff"),
                home_bullpen_fatigue=pred.get("home_bullpen_fatigue"),
                away_bullpen_fatigue=pred.get("away_bullpen_fatigue"),
                park_factor=pred.get("park_factor"),
                temperature=pred.get("temperature"),
                wind_speed=pred.get("wind_speed"),
                ml_recommendation=pred.get("ml_recommendation"),
                spread_recommendation=pred.get("spread_recommendation"),
                total_recommendation=pred.get("total_recommendation"),
                value_rating=pred.get("value_rating"),
                venue_name=pred.get("venue_name"),
                game_time=pred.get("game_time"),
                sim_distribution=pred.get("sim_distribution"),
                model_version=model_version,
                created_at=datetime.utcnow(),
            )
            db_session.add(proj)
        stored += 1

    db_session.commit()
    logger.info(f"Stored {stored} game projections for {target_date}")
    return stored


def store_game_actuals(target_date):
    """Fetch final scores from MLB API and store GameActuals.

    Compares against stored projections for accuracy tracking.
    """
    import statsapi as mlbstatsapi

    date_str = target_date.strftime("%Y-%m-%d")
    schedule = mlbstatsapi.schedule(date=date_str)
    stored = 0

    for game in schedule:
        if game.get("status") not in ("Final", "Game Over", "Completed Early"):
            continue

        home_score = game.get("home_score")
        away_score = game.get("away_score")
        if home_score is None or away_score is None:
            continue

        game_id = game["game_id"]
        home_score = int(home_score)
        away_score = int(away_score)
        total_runs = home_score + away_score
        winner = "home" if home_score > away_score else "away"
        run_margin = abs(home_score - away_score)

        # Fetch matching projection
        proj = (
            db_session.query(GameProjections)
            .filter_by(date=target_date, game_id=game_id)
            .first()
        )

        projected_home_wp = proj.home_win_prob if proj else None
        projected_total = proj.projected_total if proj else None
        market_total = proj.market_total if proj else None

        # Compute correctness
        ml_correct = None
        total_correct = None
        spread_correct = None
        projection_error = None

        if proj:
            from app.services.mlb_game_picks import (
                derive_spread_recommendation_row,
                grade_moneyline,
                grade_spread,
                grade_total,
            )

            spread_pick = (
                proj.spread_recommendation
                or derive_spread_recommendation_row(
                    {
                        "run_line": proj.run_line,
                        "market_spread": proj.market_spread,
                    }
                )
            )

            ml_correct = grade_moneyline(proj.ml_recommendation, winner=winner)
            total_correct = grade_total(
                proj.total_recommendation,
                total_runs=total_runs,
                market_total=market_total,
                projected_total=projected_total,
            )
            if proj.market_spread is not None and spread_pick:
                spread_correct = grade_spread(
                    spread_pick,
                    home_score=home_score,
                    away_score=away_score,
                    market_spread_home=float(proj.market_spread),
                )

            projection_error = (
                round(total_runs - projected_total, 1) if projected_total else None
            )

        # Upsert
        existing = (
            db_session.query(GameActuals)
            .filter_by(date=target_date, game_id=game_id)
            .first()
        )

        if existing:
            existing.home_score = home_score
            existing.away_score = away_score
            existing.total_runs = total_runs
            existing.winner = winner
            existing.run_margin = run_margin
            existing.projected_home_win_prob = projected_home_wp
            existing.projected_total = projected_total
            existing.market_total = market_total
            existing.ml_correct = ml_correct
            existing.total_correct = total_correct
            existing.spread_correct = spread_correct
            existing.projection_error = projection_error
        else:
            actual = GameActuals(
                date=target_date,
                game_id=game_id,
                home_team=game["home_name"],
                away_team=game["away_name"],
                home_score=home_score,
                away_score=away_score,
                total_runs=total_runs,
                winner=winner,
                run_margin=run_margin,
                projected_home_win_prob=projected_home_wp,
                projected_total=projected_total,
                market_total=market_total,
                ml_correct=ml_correct,
                total_correct=total_correct,
                spread_correct=spread_correct,
                projection_error=projection_error,
            )
            db_session.add(actual)
        stored += 1

    db_session.commit()
    logger.info(f"Stored {stored} game actuals for {target_date}")
    return stored


def run_game_projection_pipeline(target_date=None):
    """Run the full game-level projection pipeline.

    Enhanced with Technical Playbook modules:
    - Weather-adjusted park factors with air density
    - TTOP adjustments by pitcher repertoire
    - Umpire effects (reduced for 2026 ABS)
    - Travel fatigue
    - Venn-Abers calibration
    - Diverse ensemble predictions

    Steps:
    1. Compute bullpen fatigue
    2. Generate game predictions (ensemble or heuristic)
    3. Fetch market odds
    4. Compute edge and value ratings
    5. Integrate blowout data
    6. Store projections
    """
    if target_date is None:
        target_date = date.today()

    logger.info(f"=== Starting game projection pipeline for {target_date} ===")

    # Step 1: Bullpen fatigue
    logger.info("Step 1: Computing bullpen fatigue...")
    try:
        from app.services.etl.mlb.bullpen_fatigue import main as run_bullpen_fatigue

        run_bullpen_fatigue()
    except Exception as e:
        logger.warning(f"Bullpen fatigue computation failed (using defaults): {e}")

    # Step 2: Generate predictions (now includes TTOP, weather, umpire, travel)
    logger.info(
        "Step 2: Generating game predictions (with Technical Playbook features)..."
    )
    from app.services.etl.mlb.game_model import (
        get_todays_games,
        predict_games,
        load_park_factors,
    )

    load_park_factors()
    games = get_todays_games()

    if not games:
        logger.info("No games scheduled today. Pipeline complete.")
        return 0

    predictions = predict_games(games)
    logger.info(f"Generated predictions for {len(predictions)} games")

    try:
        from app.services.etl.mlb.monte_carlo import enrich_predictions_with_monte_carlo

        enrich_predictions_with_monte_carlo(predictions, games)
    except Exception as e:
        logger.warning("Monte Carlo enrichment skipped: %s", e)

    # Step 3: Fetch market odds
    logger.info("Step 3: Fetching market odds...")
    odds_map = fetch_game_odds()

    # Step 4: Compute edge and value ratings
    logger.info("Step 4: Computing edge vs market and value ratings...")
    for pred in predictions:
        odds_key = f"{pred['away_team']} @ {pred['home_team']}"
        odds_data = odds_map.get(odds_key, {})

        if odds_data:
            edge_data = compute_edge_and_value(pred, odds_data)
            pred.update(edge_data)
        else:
            pred["model_confidence"] = round(abs(pred["home_win_prob"] - 0.5) * 2.0, 3)
            pred["value_rating"] = "No Edge"
            pred["ml_recommendation"] = (
                "HOME"
                if pred["home_win_prob"] > 0.55
                else ("AWAY" if pred["home_win_prob"] < 0.45 else "NO_PLAY")
            )
            pred["total_recommendation"] = "NO_PLAY"

    # Step 5: Integrate blowout data if available
    try:
        from app.models.predictions_models import BlowoutChances

        blowouts = {
            b.game_id: b.run_differential
            for b in db_session.query(BlowoutChances).all()
        }
        for pred in predictions:
            pred["blowout_run_diff"] = blowouts.get(pred["game_id"])
    except Exception:
        pass

    # Step 6: Store projections
    logger.info("Step 6: Storing game projections...")
    stored = store_game_projections(predictions, target_date)

    logger.info(f"=== Pipeline complete: {stored} games projected ===")
    return stored


def main():
    parser = argparse.ArgumentParser(description="MLB Game Projection Pipeline")
    parser.add_argument(
        "--predict", action="store_true", help="Run prediction pipeline"
    )
    parser.add_argument(
        "--store-actuals", action="store_true", help="Store game actuals (post-game)"
    )
    parser.add_argument(
        "--date", type=str, default=None, help="Target date (YYYY-MM-DD)"
    )
    args = parser.parse_args()

    from app.services.etl.mlb._db import close_session, init_session

    init_session()
    try:
        if args.date:
            target_date = date.fromisoformat(args.date)
        else:
            target_date = date.today()

        if args.store_actuals:
            from datetime import timedelta

            yesterday = target_date - timedelta(days=1)
            store_game_actuals(yesterday)
        elif args.predict:
            run_game_projection_pipeline(target_date)
        else:
            parser.print_help()
    finally:
        close_session()


if __name__ == "__main__":
    main()


def run_game_projections(target_date=None) -> dict:
    from app.services.etl.mlb._db import init_session, close_session
    from datetime import date as date_cls

    init_session()
    try:
        td = target_date or date_cls.today()
        count = run_game_projection_pipeline(td)
        return {"status": "ok", "date": td.isoformat(), "games_stored": count}
    finally:
        close_session()


def run_store_game_actuals(target_date=None) -> dict:
    from app.services.etl.mlb._db import init_session, close_session
    from datetime import date as date_cls, timedelta

    init_session()
    try:
        td = target_date or (date_cls.today() - timedelta(days=1))
        count = store_game_actuals(td)
        return {"status": "ok", "date": td.isoformat(), "actuals_stored": count}
    finally:
        close_session()
