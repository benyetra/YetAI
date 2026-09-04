#!/usr/bin/env python3
"""
QB Predictions with Betting Integration - Heroku Version
Combines dynamic QB predictions with O/U lines and betting recommendations
"""

import os
import warnings
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

import requests

from app.models.predictions_models import QBPredictions
from app.services.etl.nfl._db import db_session
from app.services.etl.nfl.nfl_common import get_current_nfl_week, get_nfl_season

warnings.filterwarnings("ignore")

# Odds API configuration
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4/sports/"
SPORT = "americanfootball_nfl"


def get_nfl_games_and_lines():
    """Get NFL games and O/U lines from odds API"""
    from app.services.odds_api_service import sport_in_season
    from app.services.odds_api_sync import sync_odds_get

    if not sport_in_season(SPORT):
        print("⏭️  NFL off-season — skipping Odds API QB lines fetch")
        return {}

    try:
        # Get NFL games
        url = f"{BASE_URL}{SPORT}/events"
        params = {"apiKey": ODDS_API_KEY, "dateFormat": "iso"}
        response = sync_odds_get(
            url,
            params=params,
            caller="etl.nfl.qb_betting.events",
            raise_for_status=False,
        )

        if response is None or response.status_code != 200:
            code = response.status_code if response is not None else "blocked"
            print(f"❌ Failed to fetch NFL games: {code}")
            return {}

        games = response.json()
        all_qb_lines = {}

        print(f"📅 Processing {len(games)} NFL games...")

        for game in games:
            event_id = game["id"]

            # Get O/U lines for this game
            odds_url = f"{BASE_URL}{SPORT}/events/{event_id}/odds"
            odds_params = {
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": "player_pass_yds",
                "oddsFormat": "american",
                "bookmakers": "fanduel,draftkings,betmgm",
            }

            odds_response = sync_odds_get(
                odds_url,
                params=odds_params,
                caller=f"etl.nfl.qb_betting.odds.{event_id}",
                raise_for_status=False,
            )
            if odds_response is not None and odds_response.status_code == 200:
                odds_data = odds_response.json()

                for bookmaker in odds_data.get("bookmakers", []):
                    bookmaker_name = bookmaker["title"]

                    for market in bookmaker.get("markets", []):
                        if market["key"] == "player_pass_yds":
                            for outcome in market["outcomes"]:
                                player_name = outcome["description"]
                                bet_type = outcome["name"]
                                line = outcome.get("point", 0)
                                odds = outcome.get("price", 0)

                                if player_name not in all_qb_lines:
                                    all_qb_lines[player_name] = {}
                                if bookmaker_name not in all_qb_lines[player_name]:
                                    all_qb_lines[player_name][bookmaker_name] = {}

                                all_qb_lines[player_name][bookmaker_name][
                                    bet_type.lower()
                                ] = {"line": line, "odds": odds}

        return all_qb_lines
    except Exception as e:
        print(f"❌ Error fetching lines: {e}")
        return {}


def get_best_line(player_lines: Dict) -> Dict:
    """Get the best available line and odds for a player"""
    best_over = {"line": 0, "odds": -110, "book": "N/A"}
    best_under = {"line": 999, "odds": -110, "book": "N/A"}

    for bookmaker, lines in player_lines.items():
        if "over" in lines:
            over_line = lines["over"]
            if over_line["line"] > best_over["line"] or (
                over_line["line"] == best_over["line"]
                and over_line["odds"] > best_over["odds"]
            ):
                best_over = {
                    "line": over_line["line"],
                    "odds": over_line["odds"],
                    "book": bookmaker,
                }

        if "under" in lines:
            under_line = lines["under"]
            if under_line["line"] < best_under["line"] or (
                under_line["line"] == best_under["line"]
                and under_line["odds"] > best_under["odds"]
            ):
                best_under = {
                    "line": under_line["line"],
                    "odds": under_line["odds"],
                    "book": bookmaker,
                }

    return {"over": best_over, "under": best_under}


def generate_betting_recommendation(
    prediction: float,
    ou_line: float,
    confidence: float,
    *,
    over_probability: float | None = None,
) -> Dict:
    """Generate betting recommendation based on prediction vs O/U line.

    When ``over_probability`` from the QB O/U classifier is available, require
    agreement with the yards-edge call. Disagreement always yields PASS.
    """
    edge = prediction - ou_line
    edge_percentage = (edge / ou_line) * 100 if ou_line > 0 else 0

    # Tightened vs prior 5%/10%: reduce coin-flip O/U recommendations.
    min_edge = 7.0
    min_confidence = 0.70
    strong_edge = 12.0
    strong_confidence = 0.75

    ml_rec = None
    if over_probability is not None:
        from app.services.etl.nfl.qb_ou_classifier import recommendation_from_over_prob

        ml_rec = recommendation_from_over_prob(float(over_probability))

    if confidence < min_confidence:
        return {
            "recommendation": "PASS",
            "reason": f"Low confidence ({confidence:.1%})",
            "edge_percentage": edge_percentage,
            "bet_size": None,
            "over_probability": over_probability,
        }

    if abs(edge_percentage) < min_edge and (
        ml_rec is None or ml_rec.get("recommendation") == "PASS"
    ):
        return {
            "recommendation": "PASS",
            "reason": f"Insufficient edge ({edge_percentage:.1f}%)",
            "edge_percentage": edge_percentage,
            "bet_size": None,
            "over_probability": over_probability,
        }

    if edge_percentage >= min_edge:
        bet_type = "OVER"
        if edge_percentage >= strong_edge and confidence >= strong_confidence:
            bet_size = "LARGE"
            reason = f"Strong edge ({edge_percentage:.1f}%) + High confidence ({confidence:.1%})"
        else:
            bet_size = "MEDIUM"
            reason = f"Good edge ({edge_percentage:.1f}%)"
    elif edge_percentage <= -min_edge:
        bet_type = "UNDER"
        if abs(edge_percentage) >= strong_edge and confidence >= strong_confidence:
            bet_size = "LARGE"
            reason = f"Strong edge ({abs(edge_percentage):.1f}%) + High confidence ({confidence:.1%})"
        else:
            bet_size = "MEDIUM"
            reason = f"Good edge ({abs(edge_percentage):.1f}%)"
    elif ml_rec and ml_rec.get("recommendation") in {"OVER", "UNDER"}:
        bet_type = ml_rec["recommendation"]
        bet_size = "SMALL"
        reason = ml_rec.get("reason") or "ML O/U edge"
    else:
        return {
            "recommendation": "PASS",
            "reason": "No significant edge",
            "edge_percentage": edge_percentage,
            "bet_size": None,
            "over_probability": over_probability,
        }

    # Classifier disagreement → always PASS (no strong-edge override).
    if (
        ml_rec
        and ml_rec.get("recommendation") in {"OVER", "UNDER"}
        and ml_rec["recommendation"] != bet_type
    ):
        return {
            "recommendation": "PASS",
            "reason": (
                f"Yards edge ({bet_type}) disagrees with ML "
                f"({ml_rec['recommendation']}, P(over)={over_probability:.1%})"
            ),
            "edge_percentage": edge_percentage,
            "bet_size": None,
            "over_probability": over_probability,
        }

    if ml_rec and ml_rec.get("recommendation") == bet_type:
        reason = f"{reason}; ML agrees (P(over)={over_probability:.1%})"

    return {
        "recommendation": bet_type,
        "reason": reason,
        "edge_percentage": edge_percentage,
        "bet_size": bet_size,
        "over_probability": over_probability,
    }


def normalize_player_name(name: str) -> str:
    """Normalize player names for matching"""
    name = (
        name.replace(" Jr.", "")
        .replace(" Sr.", "")
        .replace(" III", "")
        .replace(" II", "")
    )
    name_mapping = {
        "CJ Stroud": "C.J. Stroud",
        "DJ Moore": "D.J. Moore",
        "AJ Brown": "A.J. Brown",
    }
    return name_mapping.get(name, name)


def _run_qb_betting_core():
    """Main function to update QB predictions with betting data"""
    print("🏈 QB Predictions with Betting Integration - Heroku")
    print("=" * 60)

    season = get_nfl_season()
    week = get_current_nfl_week(season)

    # Get current QB predictions
    qb_predictions = (
        db_session.query(QBPredictions)
        .filter_by(season=season, week=week)
        .limit(32)
        .all()
    )
    print(f"📊 Found {len(qb_predictions)} QB predictions")

    # If no predictions exist, generate them first
    if len(qb_predictions) == 0:
        print("🔄 No QB predictions found. Generating predictions first...")
        # Import and run the dynamic QB script logic
        from app.services.etl.nfl.qb_dynamic import run as generate_dynamic_predictions

        generate_dynamic_predictions()

        # Re-query for predictions after generation
        qb_predictions = (
            db_session.query(QBPredictions)
            .filter_by(season=season, week=week)
            .limit(32)
            .all()
        )
        print(f"📊 After generation: Found {len(qb_predictions)} QB predictions")

    # Get O/U lines
    print("📈 Fetching O/U lines from odds API...")
    all_lines = get_nfl_games_and_lines()
    print(f"✅ Found lines for {len(all_lines)} players")

    # Debug: show which players have lines
    if all_lines:
        print("📋 Players with lines from API:")
        for player_name in list(all_lines.keys())[:10]:  # Show first 10
            print(f"   - {player_name}")
        if len(all_lines) > 10:
            print(f"   ... and {len(all_lines) - 10} more")

    updated_count = 0
    matched_count = 0

    for qb in qb_predictions:
        qb_name = qb.qb_player_name
        normalized_name = normalize_player_name(qb_name)

        # Try to find matching lines
        lines = None
        for line_player_name in all_lines.keys():
            if (
                normalized_name.lower() in line_player_name.lower()
                or line_player_name.lower() in normalized_name.lower()
            ):
                lines = all_lines[line_player_name]
                break

        if lines:
            matched_count += 1
            best_lines = get_best_line(lines)
            ou_line = best_lines["over"]["line"]

            if ou_line > 0:
                over_prob = None
                fi = (
                    qb.feature_importance
                    if isinstance(qb.feature_importance, dict)
                    else {}
                )
                fi = dict(fi) if fi else {}
                feat_ctx = (
                    fi.get("features") if isinstance(fi.get("features"), dict) else {}
                )
                feat_ctx = dict(feat_ctx) if feat_ctx else {}

                # Reinject real prop line into feature vector + publish yards
                try:
                    from app.services.etl.nfl.qb_passing_yards_ml import (
                        apply_published_yards_after_line,
                        predict_yards_ml_loaded,
                        production_method_for_published,
                        qb_ml_enabled,
                        recenter_qb_interval,
                        reinject_pass_yds_line,
                    )

                    ml_yards = None
                    if feat_ctx:
                        feat_ctx = reinject_pass_yds_line(
                            feat_ctx, ou_line=float(ou_line)
                        )
                        fi["features"] = feat_ctx
                        ml_yards = predict_yards_ml_loaded(feat_ctx)
                    tier_raw = fi.get("tier_yards")
                    if tier_raw is None:
                        tier_raw = feat_ctx.get("tier_yards")
                    if tier_raw is None:
                        tier_raw = qb.predicted_passing_yards
                    yards, pub_method = apply_published_yards_after_line(
                        tier_yards=float(tier_raw),
                        ou_line=float(ou_line),
                        ml_yards=ml_yards,
                        ml_enabled=qb_ml_enabled(),
                    )
                    qb.predicted_passing_yards = float(yards)
                    qb.prediction_interval_lower, qb.prediction_interval_upper = (
                        recenter_qb_interval(
                            float(yards),
                            qb.prediction_interval_lower,
                            qb.prediction_interval_upper,
                        )
                    )
                    qb.prediction_method = production_method_for_published(
                        pub_method,
                        existing_method=qb.prediction_method,
                    )
                    if ml_yards is not None and pub_method != "gbm":
                        fi["ml_shadow_yards"] = float(ml_yards)
                    qb.feature_importance = fi
                except Exception:
                    pass

                try:
                    from app.services.etl.nfl.qb_ou_classifier import (
                        predict_over_probability_loaded,
                    )

                    over_prob = predict_over_probability_loaded(feat_ctx or {}, ou_line)
                except Exception:
                    over_prob = None

                recommendation = generate_betting_recommendation(
                    qb.predicted_passing_yards,
                    ou_line,
                    qb.model_confidence or 0.5,
                    over_probability=over_prob,
                )

                # Update QB prediction with betting data
                qb.ou_line = ou_line
                qb.over_odds = best_lines["over"]["odds"]
                qb.under_odds = best_lines["under"]["odds"]
                qb.best_over_book = best_lines["over"]["book"]
                qb.best_under_book = best_lines["under"]["book"]
                qb.betting_recommendation = recommendation["recommendation"]
                qb.bet_size = recommendation["bet_size"]
                qb.edge_percentage = recommendation["edge_percentage"]
                qb.recommendation_reason = recommendation["reason"]
                if over_prob is not None:
                    fi = (
                        dict(qb.feature_importance)
                        if isinstance(qb.feature_importance, dict)
                        else dict(fi)
                    )
                    fi["ml_over_probability"] = round(float(over_prob), 3)
                    qb.feature_importance = fi

                db_session.commit()
                updated_count += 1

                print(
                    f"  ✅ {qb_name}: {ou_line} O/U → {recommendation['recommendation']} ({recommendation['bet_size'] or 'N/A'})"
                )

    print(f"\n📊 BETTING INTEGRATION SUMMARY:")
    print(f"   🎯 QBs with predictions: {len(qb_predictions)}")
    print(f"   📈 QBs with lines available: {matched_count}")
    print(f"   ✅ QBs updated with betting data: {updated_count}")
    match_rate = (
        (matched_count / len(qb_predictions) * 100) if len(qb_predictions) > 0 else 0
    )
    print(f"   📊 Match rate: {match_rate:.1f}%")

    # Show recommendations
    strong_bets = (
        db_session.query(QBPredictions)
        .filter(
            QBPredictions.season == season,
            QBPredictions.week == week,
            QBPredictions.bet_size == "LARGE",
        )
        .all()
    )

    medium_bets = (
        db_session.query(QBPredictions)
        .filter(
            QBPredictions.season == season,
            QBPredictions.week == week,
            QBPredictions.bet_size == "MEDIUM",
        )
        .all()
    )

    print(f"\n🎯 BETTING RECOMMENDATIONS:")
    print(f"   🔥 Strong Bets: {len(strong_bets)}")
    print(f"   📈 Medium Bets: {len(medium_bets)}")

    if strong_bets:
        print(f"\n🔥 STRONG BETS:")
        for bet in strong_bets:
            print(
                f"   {bet.qb_player_name}: {bet.betting_recommendation} {bet.ou_line} ({bet.edge_percentage:+.1f}%)"
            )

    print(f"\n✅ Betting integration complete!")


if __name__ == "__main__":
    from app.services.etl.nfl._db import init_session, close_session

    init_session()
    try:
        _run_qb_betting_core()
    finally:
        close_session()


def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session

    init_session()
    try:
        _run_qb_betting_core()
        return {"status": "ok", "task": "nfl_qb_betting"}
    finally:
        close_session()
