"""WNBA stats.wnba.com client — wraps nba_api with LeagueID="10".

stats.nba.com and stats.wnba.com expose the same endpoint surface; the only
difference is `LeagueID`: "00" for NBA, "10" for WNBA. We pin LeagueID="10" here
and provide thin retry/backoff so each ETL script can ask for a specific
dashboard without re-implementing transport.

Fetch profiles:
- ``default``: daily team-stats beat (4 attempts, 90s read) — full refresh.
- ``fast``: hourly pregame path when a quick probe is needed (2 attempts, 45s).

If a particular endpoint refuses LeagueID="10", fall back to a direct HTTP call
against stats.wnba.com for that endpoint only. Document such overrides inline.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

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

T = TypeVar("T")


class StatsNbaUnavailable(Exception):
    """stats.nba.com did not respond successfully after configured retries."""


@dataclass(frozen=True)
class _FetchProfile:
    max_attempts: int
    timeout: tuple[int, int]
    backoff_seconds: float


_PROFILES: dict[str, _FetchProfile] = {
    "default": _FetchProfile(max_attempts=4, timeout=(15, 90), backoff_seconds=20.0),
    "fast": _FetchProfile(max_attempts=2, timeout=(15, 45), backoff_seconds=5.0),
}

# Back-compat for tests and callers that read the default timeout tuple.
STATS_HTTP_TIMEOUT = _PROFILES["default"].timeout


def _resolve_profile(profile: str) -> _FetchProfile:
    return _PROFILES.get(profile, _PROFILES["default"])


def _retry(callable_: Callable[[], T], label: str, *, profile: str = "default") -> T:
    """Call ``callable_()`` with up to profile.max_attempts retries."""
    cfg = _resolve_profile(profile)
    last_exc: Exception | None = None
    for attempt in range(1, cfg.max_attempts + 1):
        try:
            return callable_()
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "nba_api %s attempt %d/%d failed: %s",
                label,
                attempt,
                cfg.max_attempts,
                exc,
            )
            if attempt < cfg.max_attempts:
                time.sleep(cfg.backoff_seconds)
    assert last_exc is not None
    raise StatsNbaUnavailable(
        f"{label} failed after {cfg.max_attempts} attempts: {last_exc}"
    ) from last_exc


def fetch_team_dashboard(
    season: str,
    measure_type: str = "Base",
    per_mode: str = "PerGame",
    *,
    profile: str = "default",
) -> list[dict[str, Any]]:
    """League-wide team dashboard. measure_type ∈ {Base, Advanced, Defense, ...}."""
    cfg = _resolve_profile(profile)

    def call():
        return leaguedashteamstats.LeagueDashTeamStats(
            league_id_nullable=LEAGUE_ID,
            season=season,
            season_type_all_star="Regular Season",
            measure_type_detailed_defense=measure_type,
            per_mode_detailed=per_mode,
            timeout=cfg.timeout,
        )

    obj = _retry(call, f"LeagueDashTeamStats({measure_type})", profile=profile)
    return obj.get_normalized_dict()["LeagueDashTeamStats"]


def fetch_team_roster(
    team_id: int, season: str, *, profile: str = "default"
) -> list[dict[str, Any]]:
    """Player list for a single team."""
    cfg = _resolve_profile(profile)

    def call():
        return commonteamroster.CommonTeamRoster(
            league_id_nullable=LEAGUE_ID,
            team_id=team_id,
            season=season,
            timeout=cfg.timeout,
        )

    obj = _retry(call, f"CommonTeamRoster(team={team_id})", profile=profile)
    return obj.get_normalized_dict()["CommonTeamRoster"]


def fetch_player_game_log(
    player_id: int, season: str, *, profile: str = "default"
) -> list[dict[str, Any]]:
    """Per-game stats for one player across a season."""
    cfg = _resolve_profile(profile)

    def call():
        return playergamelog.PlayerGameLog(
            league_id_nullable=LEAGUE_ID,
            player_id=player_id,
            season=season,
            season_type_all_star="Regular Season",
            timeout=cfg.timeout,
        )

    obj = _retry(call, f"PlayerGameLog({player_id})", profile=profile)
    return obj.get_normalized_dict()["PlayerGameLog"]


def fetch_player_career(
    player_id: int, *, profile: str = "default"
) -> dict[str, list[dict[str, Any]]]:
    """All career sections for one player."""
    cfg = _resolve_profile(profile)

    def call():
        return playercareerstats.PlayerCareerStats(
            league_id_nullable=LEAGUE_ID,
            player_id=player_id,
            timeout=cfg.timeout,
        )

    obj = _retry(call, f"PlayerCareerStats({player_id})", profile=profile)
    return obj.get_normalized_dict()


def fetch_scoreboard(
    game_date_yyyymmdd: str, *, profile: str = "default"
) -> dict[str, list[dict[str, Any]]]:
    """Daily scoreboard. Use ESPN scoreboard as the primary source — cross-check only."""
    cfg = _resolve_profile(profile)

    def call():
        return scoreboardv2.ScoreboardV2(
            league_id=LEAGUE_ID,
            game_date=game_date_yyyymmdd,
            day_offset=0,
            timeout=cfg.timeout,
        )

    obj = _retry(call, "ScoreboardV2", profile=profile)
    return obj.get_normalized_dict()


def fetch_league_player_stats(
    season: str, measure_type: str = "Base", *, profile: str = "default"
) -> list[dict[str, Any]]:
    """League-wide per-player season stats."""
    cfg = _resolve_profile(profile)

    def call():
        return leaguedashplayerstats.LeagueDashPlayerStats(
            league_id_nullable=LEAGUE_ID,
            season=season,
            season_type_all_star="Regular Season",
            measure_type_detailed_defense=measure_type,
            per_mode_detailed="PerGame",
            timeout=cfg.timeout,
        )

    obj = _retry(call, f"LeagueDashPlayerStats({measure_type})", profile=profile)
    return obj.get_normalized_dict()["LeagueDashPlayerStats"]
