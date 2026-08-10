"""Attach Odds API ``player_anytime_td`` lines to anytime-TD predictions."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from app.core.database import SessionLocal
from app.models.predictions_models import NFLAnytimeTDPredictions
from app.services.etl.nfl.nfl_common import get_current_nfl_week, resolve_nfl_season
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

# Minimum model edge over market implied prob to recommend OVER.
ANYTIME_TD_EDGE_THRESHOLD = 0.05

ODDS_API_KEY_ENV = "ODDS_API_KEY"
ODDS_BASE_URL = "https://api.the-odds-api.com/v4/sports"
SPORT = "americanfootball_nfl"
MARKET = "player_anytime_td"
BOOKMAKER_PRIORITY = ["pinnacle", "fanduel", "draftkings", "betmgm"]


def american_to_implied_prob(odds: int | float) -> float:
    """Convert American odds to implied probability (no vig removal)."""
    o = float(odds)
    if o < 0:
        return abs(o) / (abs(o) + 100.0)
    return 100.0 / (o + 100.0)


def compute_edge(td_probability: float, implied_prob: float) -> float:
    return td_probability - implied_prob


def recommendation_for_edge(
    edge: float,
    *,
    threshold: float = ANYTIME_TD_EDGE_THRESHOLD,
) -> str:
    return "OVER" if edge >= threshold else "NO_PLAY"


def attach_betting_fields(
    *,
    td_probability: float,
    market_odds: int,
) -> dict[str, Any]:
    implied = american_to_implied_prob(market_odds)
    edge = compute_edge(td_probability, implied)
    return {
        "market_odds": market_odds,
        "market_implied_prob": implied,
        "edge": edge,
        "recommendation": recommendation_for_edge(edge),
    }


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


def _is_better_yes_odds(candidate: int, current: int | None) -> bool:
    if current is None:
        return True
    return candidate > current


def parse_player_anytime_td_outcomes(odds_payload: dict[str, Any]) -> dict[str, int]:
    """Extract best Yes price per player from one event odds payload."""
    best: dict[str, int] = {}
    for bookmaker in odds_payload.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != MARKET:
                continue
            for outcome in market.get("outcomes", []):
                if str(outcome.get("name", "")).lower() != "yes":
                    continue
                player = outcome.get("description")
                price = outcome.get("price")
                if not player or price is None:
                    continue
                price_i = int(price)
                if _is_better_yes_odds(price_i, best.get(player)):
                    best[player] = price_i
    return best


def _compact_name(name: str) -> str:
    """Alphanumeric lowercase key for punctuation-insensitive equality."""
    cleaned = normalize_player_name(name).lower()
    return "".join(ch for ch in cleaned if ch.isalnum())


def _name_first_last(name: str) -> tuple[list[str], str]:
    parts = normalize_player_name(name).split()
    if not parts:
        return [], ""
    return parts[:-1], parts[-1].lower()


def match_player_odds(
    prediction_name: str,
    odds_by_player: dict[str, int],
) -> int | None:
    """Match prediction player name to odds map (exact → compact → last-name)."""
    pred_norm = normalize_player_name(prediction_name).lower()
    pred_compact = _compact_name(prediction_name)
    pred_first_parts, pred_last = _name_first_last(prediction_name)

    entries: list[tuple[str, str, int]] = []
    for odds_name, price in odds_by_player.items():
        entries.append(
            (
                normalize_player_name(odds_name).lower(),
                _compact_name(odds_name),
                price,
            )
        )

    for odds_norm, _, price in entries:
        if pred_norm == odds_norm:
            return price

    for _, odds_compact, price in entries:
        if pred_compact == odds_compact:
            return price

    if not pred_last:
        return None

    last_matches: list[int] = []
    for odds_norm, _, price in entries:
        odds_first_parts, odds_last = _name_first_last(odds_norm)
        if odds_last != pred_last:
            continue
        if not pred_first_parts:
            last_matches.append(price)
            continue
        pred_first = pred_first_parts[0].lower()
        odds_first = odds_first_parts[0].lower() if odds_first_parts else ""
        if pred_first == odds_first:
            last_matches.append(price)
            continue
        if pred_first[0] == odds_first[0]:
            last_matches.append(price)

    if len(last_matches) == 1:
        return last_matches[0]
    return None


def _odds_get(path: str, params: dict[str, Any]):
    api_key = os.environ.get(ODDS_API_KEY_ENV)
    if not api_key:
        logger.warning("%s not set; skipping anytime TD odds fetch", ODDS_API_KEY_ENV)
        return None
    from app.services.odds_api_sync import sync_odds_get

    return sync_odds_get(
        f"{ODDS_BASE_URL}/{path}",
        params={"apiKey": api_key, **params},
        caller=f"etl.nfl.anytime_td_betting.{path}",
        timeout=30,
        raise_for_status=False,
    )


def fetch_anytime_td_odds() -> dict[str, int]:
    """Fetch ``player_anytime_td`` Yes odds for all upcoming NFL events."""
    from app.services.odds_api_service import sport_in_season

    if not sport_in_season(SPORT):
        logger.info("NFL off-season — skipping anytime TD odds fetch")
        return {}

    events_resp = _odds_get(f"{SPORT}/events", {"dateFormat": "iso"})
    if events_resp is None or events_resp.status_code != 200:
        code = events_resp.status_code if events_resp is not None else "blocked"
        logger.warning("Failed to fetch NFL events for anytime TD: %s", code)
        return {}

    all_odds: dict[str, int] = {}
    for game in events_resp.json():
        event_id = game.get("id")
        if not event_id:
            continue
        odds_resp = _odds_get(
            f"{SPORT}/events/{event_id}/odds",
            {
                "regions": "us",
                "markets": MARKET,
                "oddsFormat": "american",
                "bookmakers": ",".join(BOOKMAKER_PRIORITY),
            },
        )
        if odds_resp is None or odds_resp.status_code != 200:
            continue
        for player, price in parse_player_anytime_td_outcomes(odds_resp.json()).items():
            if _is_better_yes_odds(price, all_odds.get(player)):
                all_odds[player] = price
    return all_odds


def _prediction_to_upsert_row(
    pred: NFLAnytimeTDPredictions,
    betting: dict[str, Any],
) -> dict[str, Any]:
    return {
        "season": pred.season,
        "week": pred.week,
        "game_date": pred.game_date,
        "player_id": pred.player_id,
        "player_name": pred.player_name,
        "position": pred.position,
        "team_name": pred.team_name,
        "opponent_team_name": pred.opponent_team_name,
        "expected_tds": pred.expected_tds,
        "td_probability": pred.td_probability,
        "confidence_score": pred.confidence_score,
        "features": pred.features,
        "model_version": pred.model_version,
        "prediction_date": pred.prediction_date,
        "created_at": pred.created_at or datetime.utcnow(),
        **betting,
    }


def run(*, season: int | None = None, week: int | None = None) -> dict[str, Any]:
    """Load predictions, attach market odds/edge/recommendation, upsert."""
    resolved_season = resolve_nfl_season(season)
    resolved_week = week if week is not None else get_current_nfl_week(resolved_season)

    odds_by_player = fetch_anytime_td_odds()

    db = SessionLocal()
    try:
        predictions = (
            db.query(NFLAnytimeTDPredictions)
            .filter_by(season=resolved_season, week=resolved_week)
            .all()
        )
        upsert_rows: list[dict[str, Any]] = []
        matched = 0

        for pred in predictions:
            market_odds = match_player_odds(pred.player_name, odds_by_player)
            if market_odds is None:
                continue
            matched += 1
            betting = attach_betting_fields(
                td_probability=pred.td_probability,
                market_odds=market_odds,
            )
            upsert_rows.append(_prediction_to_upsert_row(pred, betting))

        if upsert_rows:
            upsert_many(
                db,
                NFLAnytimeTDPredictions,
                upsert_rows,
                conflict_keys=["season", "week", "player_id"],
                update_keys=[
                    "market_odds",
                    "market_implied_prob",
                    "edge",
                    "recommendation",
                ],
            )
            db.commit()

        return {
            "status": "ok",
            "season": resolved_season,
            "week": resolved_week,
            "predictions": len(predictions),
            "matched": matched,
            "updated": len(upsert_rows),
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
