"""Refresh pred_player_career_data from API-Sports per-player season totals.

Port of YetiBets/scripts/nba/update_player_career_data_api_sports.py.

For each player in pred_team_roster: search api-sports by first name to find
their api-sports player_id, then fetch /players/statistics for the current
season and aggregate the game-by-game lines into season totals. Stored keyed
by (player_id, season).

This is the most API-call-heavy port so far: roster ~404 players × 2 calls
(search + stats) ≈ 800 requests. At 0.15s sleep that's ~2 min wall time, well
under api-sports's 7500/day quota.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import PlayerCareerData, TeamRoster
from app.services.etl.nba._api_sports import api_request, get_current_season
from app.services.etl.nba._espn import EASTERN

logger = logging.getLogger(__name__)


def _safe_int(val, default=0):
    """API-Sports returns ints, floats, plus-minus strings like '+5' or None."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return val
    try:
        return int(str(val).replace("+", ""))
    except (ValueError, TypeError):
        return default


def _parse_minutes(min_str) -> float:
    """API-Sports returns '32:15' or a plain number."""
    if not min_str:
        return 0.0
    s = str(min_str)
    if ":" in s:
        try:
            parts = s.split(":")
            return int(parts[0]) + int(parts[1]) / 60
        except (ValueError, IndexError):
            return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _format_season(year: int) -> str:
    return f"{year}-{str(year + 1)[-2:]}"


def _find_api_player_id(player_name: str) -> int | None:
    parts = player_name.split()
    if not parts:
        return None
    # Search by first name first (api-sports's /players?search= matches by lastname).
    search = api_request("players", params={"search": parts[0]})
    if not search or not search.get("response"):
        # Fallback: try last name.
        if len(parts) > 1:
            search = api_request("players", params={"search": parts[-1]})
            if not search or not search.get("response"):
                return None
        else:
            return None
    name_lower = player_name.lower()
    candidates = search["response"]
    for p in candidates:
        full = f"{p.get('firstname', '')} {p.get('lastname', '')}".strip().lower()
        if full == name_lower:
            return p["id"]
    for p in candidates:
        full = f"{p.get('firstname', '')} {p.get('lastname', '')}".strip().lower()
        if name_lower in full or full in name_lower:
            return p["id"]
    return None


def run() -> dict:
    season = get_current_season()
    season_str = _format_season(season)

    db = SessionLocal()
    try:
        roster = (
            db.query(TeamRoster.player_id, TeamRoster.player_name)
            .distinct()
            .all()
        )
        logger.info("update_player_career_data: %d roster players to process", len(roster))

        updated = 0
        skipped_no_api_id = 0
        skipped_no_stats = 0

        for nba_player_id, player_name in roster:
            if not nba_player_id or not player_name:
                continue
            try:
                api_player_id = _find_api_player_id(player_name)
                if not api_player_id:
                    skipped_no_api_id += 1
                    continue

                stats_data = api_request(
                    "players/statistics",
                    params={"id": api_player_id, "season": season},
                )
                if not stats_data or not stats_data.get("response"):
                    skipped_no_stats += 1
                    continue

                games = stats_data["response"]
                if not games:
                    skipped_no_stats += 1
                    continue

                totals = {
                    "points": 0.0, "fg_attempts": 0.0, "fg_made": 0.0,
                    "three_pt_attempts": 0.0, "three_pt_made": 0.0,
                    "ft_attempts": 0.0, "ft_made": 0.0,
                    "minutes": 0.0, "steals": 0.0, "turnovers": 0.0,
                    "blocks": 0.0, "personal_fouls": 0.0, "plus_minus": 0.0,
                }
                for g in games:
                    totals["points"] += _safe_int(g.get("points"))
                    totals["fg_attempts"] += _safe_int(g.get("fga"))
                    totals["fg_made"] += _safe_int(g.get("fgm"))
                    totals["three_pt_attempts"] += _safe_int(g.get("tpa"))
                    totals["three_pt_made"] += _safe_int(g.get("tpm"))
                    totals["ft_attempts"] += _safe_int(g.get("fta"))
                    totals["ft_made"] += _safe_int(g.get("ftm"))
                    totals["minutes"] += _parse_minutes(g.get("min"))
                    totals["steals"] += _safe_int(g.get("steals"))
                    totals["turnovers"] += _safe_int(g.get("turnovers"))
                    totals["blocks"] += _safe_int(g.get("blocks"))
                    totals["personal_fouls"] += _safe_int(g.get("pFouls"))
                    totals["plus_minus"] += _safe_int(g.get("plusMinus"))

                def pct(num, den):
                    return num / den if den > 0 else 0

                career = {
                    "points": round(totals["points"], 1),
                    "fg_attempts": round(totals["fg_attempts"], 1),
                    "fg_percentage": round(pct(totals["fg_made"], totals["fg_attempts"]), 3),
                    "three_pt_attempts": round(totals["three_pt_attempts"], 1),
                    "three_pt_percentage": round(pct(totals["three_pt_made"], totals["three_pt_attempts"]), 3),
                    "ft_attempts": round(totals["ft_attempts"], 1),
                    "ft_percentage": round(pct(totals["ft_made"], totals["ft_attempts"]), 3),
                    "minutes": round(totals["minutes"], 1),
                    "steals": round(totals["steals"], 1),
                    "turnovers": round(totals["turnovers"], 1),
                    "blocks": round(totals["blocks"], 1),
                    "personal_fouls": round(totals["personal_fouls"], 1),
                    "plus_minus": round(totals["plus_minus"], 1),
                    "last_updated": datetime.now(EASTERN),
                }

                existing = (
                    db.query(PlayerCareerData)
                    .filter_by(player_id=nba_player_id, season=season_str)
                    .first()
                )
                if existing:
                    for k, v in career.items():
                        setattr(existing, k, v)
                else:
                    db.add(PlayerCareerData(
                        player_id=nba_player_id,
                        season=season_str,
                        **career,
                    ))
                db.commit()
                updated += 1
            except Exception:
                logger.exception("update_player_career_data: failed for %s", player_name)
                db.rollback()

            time.sleep(0.15)

        return {
            "status": "ok",
            "season": season_str,
            "roster_size": len(roster),
            "updated": updated,
            "skipped_no_api_id": skipped_no_api_id,
            "skipped_no_stats": skipped_no_stats,
        }
    finally:
        db.close()
