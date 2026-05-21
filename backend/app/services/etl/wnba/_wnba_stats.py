"""WNBA stats.wnba.com client — wraps nba_api with LeagueID="10".

stats.nba.com and stats.wnba.com expose the same endpoint surface; the only
difference is `LeagueID`: "00" for NBA, "10" for WNBA. We pin LeagueID="10" here
and provide thin retry/backoff so each ETL script can ask for a specific
dashboard without re-implementing transport.

If a particular endpoint refuses LeagueID="10", fall back to a direct HTTP call
against stats.wnba.com for that endpoint only. Document such overrides inline.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from nba_api.stats.endpoints import (  # type: ignore
    commonteamroster,
    leaguedashplayerstats,
    leaguedashteamstats,
    playercareerstats,
    playergamelog,
    scoreboardv2,
)

logger = logging.getLogger(__name__)

LEAGUE_ID = "10"  # WNBA. NBA is "00".
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 60.0


def _retry(callable_, label: str):
    """Call `callable_()` with up to MAX_ATTEMPTS retries on any exception."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return callable_()
        except Exception as exc:
            last_exc = exc
            logger.warning("nba_api %s attempt %d failed: %s", label, attempt, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF_SECONDS)
    assert last_exc is not None
    raise last_exc


def fetch_team_dashboard(
    season: str, measure_type: str = "Base", per_mode: str = "PerGame"
) -> list[dict[str, Any]]:
    """League-wide team dashboard. measure_type ∈ {Base, Advanced, Defense, ...}."""
    def call():
        return leaguedashteamstats.LeagueDashTeamStats(
            league_id_nullable=LEAGUE_ID,
            season=season,
            season_type_all_star="Regular Season",
            measure_type_detailed_defense=measure_type,
            per_mode_detailed=per_mode,
        )

    obj = _retry(call, f"LeagueDashTeamStats({measure_type})")
    return obj.get_normalized_dict()["LeagueDashTeamStats"]


def fetch_team_roster(team_id: int, season: str) -> list[dict[str, Any]]:
    """Player list for a single team."""
    def call():
        return commonteamroster.CommonTeamRoster(
            league_id_nullable=LEAGUE_ID,
            team_id=team_id,
            season=season,
        )

    obj = _retry(call, f"CommonTeamRoster(team={team_id})")
    return obj.get_normalized_dict()["CommonTeamRoster"]


def fetch_player_game_log(player_id: int, season: str) -> list[dict[str, Any]]:
    """Per-game stats for one player across a season."""
    def call():
        return playergamelog.PlayerGameLog(
            league_id_nullable=LEAGUE_ID,
            player_id=player_id,
            season=season,
            season_type_all_star="Regular Season",
        )

    obj = _retry(call, f"PlayerGameLog({player_id})")
    return obj.get_normalized_dict()["PlayerGameLog"]


def fetch_player_career(player_id: int) -> dict[str, list[dict[str, Any]]]:
    """All career sections for one player."""
    def call():
        return playercareerstats.PlayerCareerStats(
            league_id_nullable=LEAGUE_ID,
            player_id=player_id,
        )

    obj = _retry(call, f"PlayerCareerStats({player_id})")
    return obj.get_normalized_dict()


def fetch_scoreboard(game_date_yyyymmdd: str) -> dict[str, list[dict[str, Any]]]:
    """Daily scoreboard. Use ESPN scoreboard as the primary source — this is here for cross-checking."""
    def call():
        return scoreboardv2.ScoreboardV2(
            league_id=LEAGUE_ID,
            game_date=game_date_yyyymmdd,
            day_offset=0,
        )

    obj = _retry(call, "ScoreboardV2")
    return obj.get_normalized_dict()


def fetch_league_player_stats(
    season: str, measure_type: str = "Base"
) -> list[dict[str, Any]]:
    """League-wide per-player season stats."""
    def call():
        return leaguedashplayerstats.LeagueDashPlayerStats(
            league_id_nullable=LEAGUE_ID,
            season=season,
            season_type_all_star="Regular Season",
            measure_type_detailed_defense=measure_type,
            per_mode_detailed="PerGame",
        )

    obj = _retry(call, f"LeagueDashPlayerStats({measure_type})")
    return obj.get_normalized_dict()["LeagueDashPlayerStats"]
