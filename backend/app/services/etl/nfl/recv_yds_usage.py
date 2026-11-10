"""Join Odds-lined receiver names to nflverse / ATD-adjacent usage priors."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.etl.nfl.nfl_common import get_current_nfl_week, get_nfl_season
from app.services.etl.nfl.recv_yds_betting import normalize_player_name
from app.services.etl.nfl.recv_yds_features import SKILL_POSITIONS


def _name_key(name: str) -> str:
    return normalize_player_name(name).strip().lower()


def _ypr(receiving_yards: float, receptions: float) -> float | None:
    if receptions is None or float(receptions) <= 0:
        return None
    return float(receiving_yards) / float(receptions)


def select_usage_priors_for_names(
    player_names: list[str],
    weekly_rows: list[dict[str, Any]],
    *,
    season: int,
    week: int,
    game_date: date | str,
    schedule_by_team: dict[str, dict[str, Any]] | None = None,
    game_env_by_team: dict[str, dict[str, Any]] | None = None,
    defense_by_team: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Pure join used by unit tests — never invents ``target_share`` from a line."""
    wanted = {_name_key(n) for n in player_names}
    schedule_by_team = schedule_by_team or {}
    game_env_by_team = game_env_by_team or {}
    defense_by_team = defense_by_team or {}
    out: list[dict[str, Any]] = []
    for row in weekly_rows:
        pos = str(row.get("position") or "").upper()
        if pos not in SKILL_POSITIONS:
            continue
        pname = str(row.get("player_name") or row.get("player_display_name") or "")
        if _name_key(pname) not in wanted:
            continue
        share = row.get("target_share")
        attempts = row.get("team_pass_attempts")
        if share is None and row.get("targets") is not None and attempts:
            try:
                share = float(row["targets"]) / float(attempts)
            except (TypeError, ValueError, ZeroDivisionError):
                share = None
        ypr = row.get("ypr")
        if ypr is None:
            ypr = _ypr(row.get("receiving_yards") or 0.0, row.get("receptions") or 0.0)
        if share is None or attempts is None or ypr is None:
            continue
        team = row.get("team_name") or row.get("recent_team") or row.get("team")
        sched = schedule_by_team.get(str(team), {})
        opponent = sched.get("opponent_team_name") or row.get("opponent_team_name")
        if not team or not opponent:
            continue
        out.append(
            {
                "player_id": str(row.get("player_id") or row.get("gsis_id")),
                "player_name": pname,
                "position": pos,
                "team_name": team,
                "opponent_team_name": opponent,
                "game_date": sched.get("game_date", game_date),
                "season": season,
                "week": week,
                "target_share": float(share),
                "team_pass_attempts": float(attempts),
                "ypr": float(ypr),
                "adot": row.get("adot") or row.get("avg_air_yards"),
                "snap_pct": row.get("snap_pct") or row.get("offense_pct"),
                "game_env": game_env_by_team.get(str(team)),
                "opponent_defense": defense_by_team.get(str(opponent)),
            }
        )
    return out


def load_weekly_receiver_rows(season: int) -> list[dict[str, Any]]:
    """Load nflverse weekly rows; prefer ATD weekly loader when available."""
    try:
        from app.services.etl.nfl.anytime_td_features import (
            load_weekly_records_for_season,
        )

        return load_weekly_records_for_season(int(season))
    except Exception:
        import nfl_data_py as nfl

        frame = nfl.import_weekly_data([int(season)])
        return frame.to_dict(orient="records")


def load_usage_priors_for_names(player_names: list[str]) -> list[dict[str, Any]]:
    """Return skill-position usage dicts for soft-name matches in ``player_names``."""
    season = int(get_nfl_season())
    week = int(get_current_nfl_week())
    weekly = load_weekly_receiver_rows(season)
    return select_usage_priors_for_names(
        player_names,
        weekly,
        season=season,
        week=week,
        game_date=date.today().isoformat(),
    )
