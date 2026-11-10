"""Odds attach for NFL receiving yards (`player_reception_yds`) — fail-closed."""

from __future__ import annotations

import os
from typing import Any

from app.services.etl.nfl.recv_yds_model import published_recv_yards

RECV_YDS_MARKET = "player_reception_yds"
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4/sports/"
SPORT = "americanfootball_nfl"

# Mirror qb_betting.generate_betting_recommendation thresholds (no O/U classifier).
MIN_EDGE = 7.0
MIN_CONFIDENCE = 0.70
STRONG_EDGE = 12.0
STRONG_CONFIDENCE = 0.75


def normalize_player_name(name: str) -> str:
    cleaned = (
        name.replace(" Jr.", "")
        .replace(" Sr.", "")
        .replace(" III", "")
        .replace(" II", "")
    )
    aliases = {
        "CJ Stroud": "C.J. Stroud",
        "DJ Moore": "D.J. Moore",
        "AJ Brown": "A.J. Brown",
    }
    return aliases.get(cleaned, cleaned)


def get_best_line(player_lines: dict) -> dict:
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


def clear_betting_fields() -> dict[str, Any]:
    """Null betting columns when Odds attach fails or a row is unmatched."""
    return {
        "ou_line": None,
        "over_odds": None,
        "under_odds": None,
        "best_over_book": None,
        "best_under_book": None,
        "edge": None,
        "edge_percentage": None,
        "betting_recommendation": None,
        "bet_size": None,
        "recommendation_reason": None,
    }


def generate_betting_recommendation(
    prediction: float,
    ou_line: float,
    confidence: float,
) -> dict[str, Any]:
    edge = prediction - ou_line
    edge_percentage = (edge / ou_line) * 100 if ou_line > 0 else 0.0

    if confidence < MIN_CONFIDENCE:
        return {
            "recommendation": "PASS",
            "reason": f"Low confidence ({confidence:.1%})",
            "edge_percentage": edge_percentage,
            "bet_size": None,
        }
    if abs(edge_percentage) < MIN_EDGE:
        return {
            "recommendation": "PASS",
            "reason": f"Insufficient edge ({edge_percentage:.1f}%)",
            "edge_percentage": edge_percentage,
            "bet_size": None,
        }
    if edge_percentage >= MIN_EDGE:
        bet_type = "OVER"
        if edge_percentage >= STRONG_EDGE and confidence >= STRONG_CONFIDENCE:
            bet_size = "LARGE"
            reason = (
                f"Strong edge ({edge_percentage:.1f}%) + "
                f"High confidence ({confidence:.1%})"
            )
        else:
            bet_size = "MEDIUM"
            reason = f"Good edge ({edge_percentage:.1f}%)"
    else:
        bet_type = "UNDER"
        if abs(edge_percentage) >= STRONG_EDGE and confidence >= STRONG_CONFIDENCE:
            bet_size = "LARGE"
            reason = (
                f"Strong edge ({abs(edge_percentage):.1f}%) + "
                f"High confidence ({confidence:.1%})"
            )
        else:
            bet_size = "MEDIUM"
            reason = f"Good edge ({abs(edge_percentage):.1f}%)"
    return {
        "recommendation": bet_type,
        "reason": reason,
        "edge_percentage": edge_percentage,
        "bet_size": bet_size,
    }


def attach_recv_betting(
    *,
    model_yards: float,
    confidence_score: float,
    player_lines: dict,
    anchor_alpha: float | None = None,
) -> dict[str, Any] | None:
    """Soft-anchor + edge/pick when a real reception-yards line exists; else None."""
    if not player_lines:
        return None
    best = get_best_line(player_lines)
    ou_line = float(best["over"]["line"] or 0)
    if ou_line <= 0:
        return None
    published, method = published_recv_yards(
        model_yards=float(model_yards),
        ou_line=ou_line,
        line_is_real=True,
        anchor_alpha=anchor_alpha,
    )
    if published is None or method is None:
        return None
    rec = generate_betting_recommendation(
        prediction=published,
        ou_line=ou_line,
        confidence=float(confidence_score),
    )
    return {
        "predicted_receiving_yards": published,
        "model_yards": float(model_yards),
        "prediction_method": method,
        "ou_line": ou_line,
        "over_odds": best["over"]["odds"],
        "under_odds": best["under"]["odds"],
        "best_over_book": best["over"]["book"],
        "best_under_book": best["under"]["book"],
        "edge": published - ou_line,
        "edge_percentage": rec["edge_percentage"],
        "betting_recommendation": rec["recommendation"],
        "bet_size": rec["bet_size"],
        "recommendation_reason": rec["reason"],
        "confidence_score": float(confidence_score),
    }


def fetch_reception_yds_lines() -> dict[str, dict]:
    """Fetch week slate of `player_reception_yds` keyed by Odds player description.

    Fail-closed: any HTTP/off-season/budget miss returns ``{}`` (no invented lines).
    """
    from app.services.odds_api_service import sport_in_season
    from app.services.odds_api_sync import sync_odds_get

    if not sport_in_season(SPORT):
        return {}
    try:
        url = f"{BASE_URL}{SPORT}/events"
        response = sync_odds_get(
            url,
            params={"apiKey": ODDS_API_KEY, "dateFormat": "iso"},
            caller="etl.nfl.recv_yds_betting.events",
            raise_for_status=False,
        )
        if response is None or response.status_code != 200:
            return {}
        games = response.json()
        all_lines: dict[str, dict] = {}
        for game in games:
            event_id = game["id"]
            odds_response = sync_odds_get(
                f"{BASE_URL}{SPORT}/events/{event_id}/odds",
                params={
                    "apiKey": ODDS_API_KEY,
                    "regions": "us",
                    "markets": RECV_YDS_MARKET,
                    "oddsFormat": "american",
                    "bookmakers": "fanduel,draftkings,betmgm",
                },
                caller=f"etl.nfl.recv_yds_betting.odds.{event_id}",
                raise_for_status=False,
            )
            if odds_response is None or odds_response.status_code != 200:
                continue
            odds_data = odds_response.json()
            for bookmaker in odds_data.get("bookmakers", []):
                bookmaker_name = bookmaker["title"]
                for market in bookmaker.get("markets", []):
                    if market["key"] != RECV_YDS_MARKET:
                        continue
                    for outcome in market["outcomes"]:
                        player_name = outcome["description"]
                        bet_type = outcome["name"]
                        line = outcome.get("point", 0)
                        odds = outcome.get("price", 0)
                        all_lines.setdefault(player_name, {})
                        all_lines[player_name].setdefault(bookmaker_name, {})
                        all_lines[player_name][bookmaker_name][bet_type.lower()] = {
                            "line": line,
                            "odds": odds,
                        }
        return all_lines
    except Exception:
        return {}


def match_player_lines(player_name: str, all_lines: dict[str, dict]) -> dict | None:
    normalized = normalize_player_name(player_name)
    for line_player_name, lines in all_lines.items():
        if (
            normalized.lower() in line_player_name.lower()
            or line_player_name.lower() in normalized.lower()
        ):
            return lines
    return None
