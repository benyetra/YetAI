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
from app.services.etl.nba._api_sports import (
    api_request,
    get_current_season,
    normalize_player_name,
)
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


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _find_api_player_id(player_name: str) -> int | None:
    """API-Sports player id for a roster name.

    /players?search= matches on last name, so search the last name first and
    only then the first name; compare accent- and suffix-insensitively.
    """
    target = normalize_player_name(player_name)
    tokens = target.split()
    if not tokens:
        return None
    # Raw last name first ("Gilgeous-Alexander" as stored), then the
    # normalized last token, then the first name.
    raw = [t for t in player_name.split() if normalize_player_name(t) not in _SUFFIXES]
    seen: set[str] = set()
    for term in (raw[-1] if raw else "", tokens[-1], tokens[0]):
        if len(term) < 3 or term.lower() in seen:
            continue
        seen.add(term.lower())
        search = api_request("players", params={"search": term})
        candidates = (search or {}).get("response") or []
        names = [
            (
                p["id"],
                normalize_player_name(
                    f"{p.get('firstname', '')} {p.get('lastname', '')}"
                ),
            )
            for p in candidates
        ]
        for pid, full in names:
            if full == target:
                return pid
        padded = f" {target} "
        partial = [
            pid for pid, full in names if f" {full} " in padded or padded in f" {full} "
        ]
        if len(partial) == 1:
            return partial[0]
    return None


def run(
    season: int | None = None, players: list[tuple[int, str]] | None = None
) -> dict:
    """Upsert season totals for every roster player (or just `players`, as
    (nba_player_id, name) pairs — used by the season-rollover repair script)."""
    season = season or get_current_season()
    season_str = _format_season(season)

    db = SessionLocal()
    try:
        roster = (
            players
            if players is not None
            else db.query(TeamRoster.player_id, TeamRoster.player_name).distinct().all()
        )
        logger.info(
            "update_player_career_data: %d roster players to process", len(roster)
        )

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
                    "points": 0.0,
                    "fg_attempts": 0.0,
                    "fg_made": 0.0,
                    "three_pt_attempts": 0.0,
                    "three_pt_made": 0.0,
                    "ft_attempts": 0.0,
                    "ft_made": 0.0,
                    "minutes": 0.0,
                    "steals": 0.0,
                    "turnovers": 0.0,
                    "blocks": 0.0,
                    "personal_fouls": 0.0,
                    "plus_minus": 0.0,
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
                    "fg_percentage": round(
                        pct(totals["fg_made"], totals["fg_attempts"]), 3
                    ),
                    "three_pt_attempts": round(totals["three_pt_attempts"], 1),
                    "three_pt_percentage": round(
                        pct(totals["three_pt_made"], totals["three_pt_attempts"]), 3
                    ),
                    "ft_attempts": round(totals["ft_attempts"], 1),
                    "ft_percentage": round(
                        pct(totals["ft_made"], totals["ft_attempts"]), 3
                    ),
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
                    db.add(
                        PlayerCareerData(
                            player_id=nba_player_id,
                            season=season_str,
                            **career,
                        )
                    )
                db.commit()
                updated += 1
            except Exception:
                logger.exception(
                    "update_player_career_data: failed for %s", player_name
                )
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
