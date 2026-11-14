"""Shared NHL boxscore fetch + pure extractors.

Pulled out of `collect_goalie_actuals` so the three new shot/total actuals
writers can hit the same endpoints without duplicating HTTP code.

Pure extract functions (extract_team_shots, extract_player_shots,
extract_team_totals) are easy to test against a fixture dict — no DB,
no network.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import requests

NHL_API_BASE = "https://api-web.nhle.com/v1"


def _client():
    from app.services.etl.nhl.nhl_api_client import NHLAPIClient

    return NHLAPIClient()


def get_completed_games_for_date(target_date: date) -> list[dict[str, Any]]:
    """Schedule endpoint → games on ``target_date`` whose state is OFF/FINAL.

    ``/schedule/{date}`` returns a 7-day ``gameWeek``; only the day whose own
    ``date`` is the target counts, otherwise a run for one date would stamp the
    whole week's games with it.
    """
    url = f"{NHL_API_BASE}/schedule/{target_date.strftime('%Y-%m-%d')}"
    try:
        response = _client()._get(url)  # backs off on 429
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []

    target = target_date.isoformat()
    games: list[dict[str, Any]] = []
    for game_day in data.get("gameWeek", []):
        if game_day.get("date") != target:
            continue
        for game in game_day.get("games", []):
            if game.get("gameState") in ("OFF", "FINAL"):
                games.append(game)
    return games


def run_for_grading_dates(update_fn, task: str) -> dict[str, Any]:
    """Run one collector's ``update_fn(date)`` over the shared lookback window."""
    from app.services.etl.grading_window import grading_dates

    results = [update_fn(d) for d in grading_dates("nhl")]
    return {
        "status": "ok",
        "task": task,
        "dates": [r["date"] for r in results],
        "games_processed": sum(r["games_processed"] for r in results),
        "rows_inserted": sum(r["rows_inserted"] for r in results),
        "rows_updated": sum(r["rows_updated"] for r in results),
    }


def upsert_row(db, model: Any, key_filters: list[Any], row: dict[str, Any]) -> str:
    """Insert ``row`` or update the existing match. Returns inserted/updated/unchanged.

    Re-collecting a date corrects a partial row (blank names, missing mirror)
    instead of skipping it, and a clean re-run changes nothing.
    """
    existing = db.query(model).filter(*key_filters).first()
    if existing is None:
        db.add(model(**row))
        return "inserted"
    changed = False
    for key, value in row.items():
        if getattr(existing, key, None) != value:
            setattr(existing, key, value)
            changed = True
    return "updated" if changed else "unchanged"


def get_game_boxscore(game_id: int) -> Optional[dict[str, Any]]:
    """Boxscore endpoint → JSON dict or None on transport failure."""
    url = f"{NHL_API_BASE}/gamecenter/{game_id}/boxscore"
    try:
        response = _client()._get(url)  # backs off on 429
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Pure extractors over a boxscore JSON payload.
# ---------------------------------------------------------------------------


def _team_name(team: dict[str, Any]) -> str:
    """Team name in the form the projection writers store: ``placeName`` ("Colorado").

    The real NHL team object has abbrev/commonName/placeName/id/score/sog and no
    ``name``; daily_predictions stores placeName too, so the two sides spell alike.
    """
    for key in ("placeName", "commonName", "name"):
        value = (team.get(key) or {}).get("default")
        if value:
            return value
    return team.get("abbrev") or ""


def _team_id(team: dict[str, Any]) -> Optional[int]:
    return team.get("id")


def extract_team_shots(
    boxscore: dict[str, Any], *, game_id: int, game_date: date
) -> list[dict[str, Any]]:
    """Two rows per game — home + away — with per-team shots-on-goal totals.

    Boxscore puts team-level shots at homeTeam.sog / awayTeam.sog.
    """
    if not boxscore:
        return []
    away = boxscore.get("awayTeam") or {}
    home = boxscore.get("homeTeam") or {}
    rows: list[dict[str, Any]] = []

    away_sog = away.get("sog")
    home_sog = home.get("sog")
    if away_sog is not None:
        rows.append(
            {
                "game_id": game_id,
                "game_date": game_date,
                "team_id": _team_id(away),
                "team_name": _team_name(away),
                "opponent_team_id": _team_id(home),
                "opponent_team_name": _team_name(home),
                "actual_shots": int(away_sog),
            }
        )
    if home_sog is not None:
        rows.append(
            {
                "game_id": game_id,
                "game_date": game_date,
                "team_id": _team_id(home),
                "team_name": _team_name(home),
                "opponent_team_id": _team_id(away),
                "opponent_team_name": _team_name(away),
                "actual_shots": int(home_sog),
            }
        )
    return rows


def extract_player_shots(
    boxscore: dict[str, Any], *, game_id: int, game_date: date
) -> list[dict[str, Any]]:
    """One row per skater with their shots-on-goal total.

    Boxscore lays out players under
    `playerByGameStats.{awayTeam|homeTeam}.{forwards|defense}[]` each with
    a `sog` field. Goalies are excluded — they're handled by the goalie
    actuals writer.
    """
    if not boxscore:
        return []
    stats = boxscore.get("playerByGameStats") or {}
    if not stats:
        return []
    away = boxscore.get("awayTeam") or {}
    home = boxscore.get("homeTeam") or {}
    rows: list[dict[str, Any]] = []

    side_meta = {
        "awayTeam": (_team_name(away), _team_name(home)),
        "homeTeam": (_team_name(home), _team_name(away)),
    }

    for side, (team_name, opp_name) in side_meta.items():
        side_stats = stats.get(side) or {}
        for position, players in side_stats.items():
            if position == "goalies":
                continue
            for p in players:
                pid = p.get("playerId")
                sog = p.get("sog")
                if pid is None or sog is None:
                    continue
                player_name = (p.get("name") or {}).get("default", "") or ""
                rows.append(
                    {
                        "game_id": game_id,
                        "game_date": game_date,
                        "player_id": int(pid),
                        "player_name": player_name,
                        "team_name": team_name,
                        "opponent_team_name": opp_name,
                        "actual_shots": int(sog),
                    }
                )
    return rows


def extract_team_totals(
    boxscore: dict[str, Any], *, game_id: int, game_date: date
) -> Optional[dict[str, Any]]:
    """Single row per game: home_score + away_score + total."""
    if not boxscore:
        return None
    away = boxscore.get("awayTeam") or {}
    home = boxscore.get("homeTeam") or {}
    away_score = away.get("score")
    home_score = home.get("score")
    if away_score is None or home_score is None:
        return None
    return {
        "game_id": game_id,
        "game_date": game_date,
        "home_team_id": _team_id(home),
        "home_team_name": _team_name(home),
        "away_team_id": _team_id(away),
        "away_team_name": _team_name(away),
        "actual_home_goals": int(home_score),
        "actual_away_goals": int(away_score),
        "actual_total_goals": int(home_score) + int(away_score),
    }


# ---------------------------------------------------------------------------
# Pick parsing helpers (shared with the accuracy service).
# ---------------------------------------------------------------------------


def parse_ou_pick(recommendation: Optional[str]) -> Optional[str]:
    """Return 'over'/'under' from values like 'OVER 28.5' or 'PASS' → None."""
    if not recommendation:
        return None
    head = recommendation.strip().split(" ", 1)[0].lower()
    if head in ("over", "o"):
        return "over"
    if head in ("under", "u"):
        return "under"
    return None


def grade_ou_pick(
    *,
    actual: Optional[float],
    line: Optional[float],
    recommendation: Optional[str],
) -> Optional[bool]:
    """True/False if the pick won/lost; None if no graded call possible.

    actual == line → push → None.
    Matches the accuracy service's pick grading so the precomputed
    `recommendation_correct` column matches what the live API reports.
    """
    if actual is None or line is None:
        return None
    pick = parse_ou_pick(recommendation)
    if pick is None:
        return None
    if float(actual) == float(line):
        return None
    if pick == "over":
        return float(actual) > float(line)
    return float(actual) < float(line)
