"""Parse Odds API events into pred_wnba_game_lines upsert rows (consensus)."""

from __future__ import annotations

import statistics
from datetime import datetime

from app.services.etl.wnba._espn import EASTERN
from app.services.etl.wnba._team_id_map import name_to_wnba_id, normalize_team_name


def _consensus(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return statistics.mean(vals)


def _consensus_int(values: list) -> int | None:
    avg = _consensus(values)
    return int(round(avg)) if avg is not None else None


def _extract_market(book: dict, market_key: str) -> dict | None:
    for market in book.get("markets", []):
        if market.get("key") == market_key:
            return market
    return None


def game_line_row_from_event(event: dict) -> dict | None:
    """Build one consensus row from a live or historical Odds API event."""
    home_raw = event.get("home_team") or ""
    away_raw = event.get("away_team") or ""
    home_name = normalize_team_name(home_raw)
    away_name = normalize_team_name(away_raw)
    if not home_name or not away_name:
        return None

    commence_raw = event.get("commence_time")
    if not commence_raw:
        return None
    commence = datetime.fromisoformat(str(commence_raw).replace("Z", "+00:00"))
    game_date = commence.astimezone(EASTERN).date()

    spread_home_vals: list[float] = []
    spread_away_vals: list[float] = []
    spread_home_odds_vals: list[int] = []
    spread_away_odds_vals: list[int] = []
    total_vals: list[float] = []
    over_odds_vals: list[int] = []
    under_odds_vals: list[int] = []
    ml_home_vals: list[int] = []
    ml_away_vals: list[int] = []

    for book in event.get("bookmakers", []):
        spreads = _extract_market(book, "spreads")
        if spreads:
            for outcome in spreads["outcomes"]:
                if outcome["name"] == home_raw:
                    spread_home_vals.append(outcome["point"])
                    if outcome.get("price") is not None:
                        spread_home_odds_vals.append(outcome["price"])
                elif outcome["name"] == away_raw:
                    spread_away_vals.append(outcome["point"])
                    if outcome.get("price") is not None:
                        spread_away_odds_vals.append(outcome["price"])
        totals = _extract_market(book, "totals")
        if totals:
            for outcome in totals["outcomes"]:
                if outcome["name"] == "Over":
                    total_vals.append(outcome["point"])
                    if outcome.get("price") is not None:
                        over_odds_vals.append(outcome["price"])
                elif outcome["name"] == "Under":
                    if outcome.get("price") is not None:
                        under_odds_vals.append(outcome["price"])
        moneyline = _extract_market(book, "h2h")
        if moneyline:
            for outcome in moneyline["outcomes"]:
                if outcome["name"] == home_raw and outcome.get("price") is not None:
                    ml_home_vals.append(outcome["price"])
                elif outcome["name"] == away_raw and outcome.get("price") is not None:
                    ml_away_vals.append(outcome["price"])

    return {
        "game_date": game_date,
        "home_team_id": name_to_wnba_id(home_name),
        "away_team_id": name_to_wnba_id(away_name),
        "home_team_name": home_name,
        "away_team_name": away_name,
        "odds_api_event_id": event.get("id"),
        "game_time": commence,
        "spread_home": _consensus(spread_home_vals),
        "spread_away": _consensus(spread_away_vals),
        "spread_home_odds": _consensus_int(spread_home_odds_vals),
        "spread_away_odds": _consensus_int(spread_away_odds_vals),
        "total": _consensus(total_vals),
        "over_odds": _consensus_int(over_odds_vals),
        "under_odds": _consensus_int(under_odds_vals),
        "moneyline_home": _consensus_int(ml_home_vals),
        "moneyline_away": _consensus_int(ml_away_vals),
        "bookmaker": "consensus",
        "last_updated": datetime.utcnow(),
    }


def game_line_rows_from_events(events: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for event in events:
        row = game_line_row_from_event(event)
        if row:
            rows.append(row)
    return rows
