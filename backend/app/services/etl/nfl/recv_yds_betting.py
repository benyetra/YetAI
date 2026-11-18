"""Odds attach for NFL receiving yards (`player_reception_yds`) — fail-closed."""

from __future__ import annotations

import os
from typing import Any

from app.services.etl._consensus_attach import LEGACY_NFL_PROP_BOOKS
from app.services.etl.nba._fanduel_lines import PROP_BOOKS
from app.services.etl.nfl import recv_yds_model
from app.services.etl.nfl.recv_yds_model import p_over as model_p_over
from app.services.etl.nfl.recv_yds_model import published_recv_yards

RECV_YDS_MARKET = "player_reception_yds"
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4/sports/"
SPORT = "americanfootball_nfl"

MIN_CONFIDENCE = 0.70
# A side needs this much more probability than its price's breakeven.
MIN_PROB_MARGIN = 0.03
STRONG_PROB_MARGIN = 0.07
STRONG_CONFIDENCE = 0.75
DEFAULT_PRICE = -110  # breakeven price when a side has no stored price


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
    """Best book per side plus the consensus line (see ``prop_lines.best_lines``)."""
    from app.services.etl.nfl.prop_lines import best_lines

    return best_lines(player_lines)


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
    over_odds: float | None = None,
    under_odds: float | None = None,
) -> dict[str, Any]:
    """Call a side only when P(that side) beats its price's breakeven.

    ``prediction`` must be the model's own MEAN (not the line-anchored number,
    which sits near the median): P(over) comes from a skewed distribution with
    that mean (``recv_yds_model.p_over``), so a mean above the line does not
    by itself make an over.
    """
    from app.services.odds_math import breakeven_rate

    edge = prediction - ou_line
    edge_percentage = (edge / ou_line) * 100 if ou_line > 0 else 0.0
    prob_over = model_p_over(prediction, ou_line)
    out = {
        "recommendation": "PASS",
        "edge_percentage": edge_percentage,
        "bet_size": None,
        "p_over": prob_over,
    }
    if confidence < MIN_CONFIDENCE:
        return {**out, "reason": f"Low confidence ({confidence:.1%})"}
    margins = {
        "OVER": prob_over - breakeven_rate(over_odds or DEFAULT_PRICE),
        "UNDER": (1 - prob_over) - breakeven_rate(under_odds or DEFAULT_PRICE),
    }
    side = max(margins, key=margins.get)
    margin = margins[side]
    if margin < MIN_PROB_MARGIN:
        return {
            **out,
            "reason": f"No side beats its price (P(over) {prob_over:.1%})",
        }
    strong = margin >= STRONG_PROB_MARGIN and confidence >= STRONG_CONFIDENCE
    prob = prob_over if side == "OVER" else 1 - prob_over
    if not recv_yds_model.RECV_CV_FITTED:
        return {
            **out,
            "reason": f"shadow: would be {side} {prob:.1%}, CV not fitted",
        }
    return {
        **out,
        "recommendation": side,
        "bet_size": "LARGE" if strong else "MEDIUM",
        "reason": f"{side.title()} {prob:.1%} vs breakeven, +{margin:.1%}",
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
    ou_line = float(best["consensus"] or 0)
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
    # P(over) uses the raw model mean; the soft-anchored number is display only.
    rec = generate_betting_recommendation(
        prediction=float(model_yards),
        ou_line=ou_line,
        confidence=float(confidence_score),
        over_odds=best["over"]["odds"],
        under_odds=best["under"]["odds"],
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
        "edge_percentage": (published - ou_line) / ou_line * 100,
        "betting_recommendation": rec["recommendation"],
        "bet_size": rec["bet_size"],
        "recommendation_reason": rec["reason"],
        "confidence_score": float(confidence_score),
        "p_over": rec["p_over"],
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
                    # All 10 books (1 region, same credits) for the consensus
                    # snapshots; stored lines read the 3 legacy books by key.
                    "bookmakers": PROP_BOOKS,
                },
                caller=f"etl.nfl.recv_yds_betting.odds.{event_id}",
                raise_for_status=False,
            )
            if odds_response is None or odds_response.status_code != 200:
                continue
            odds_data = odds_response.json()
            for bookmaker in odds_data.get("bookmakers", []):
                if bookmaker.get("key") not in LEGACY_NFL_PROP_BOOKS:
                    continue
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
    """Lines for this player: same name ignoring punctuation and suffixes
    ("A.J. Brown" / "AJ Brown", "Brian Thomas Jr" / "Brian Thomas Jr.").

    Substring matching attached other players' lines ("Josh Allen" inside a
    longer name) and the alias table missed whichever spelling it did not list.
    """
    from app.services.etl.nfl.player_names import find_by_player_name

    return find_by_player_name(player_name, all_lines)
