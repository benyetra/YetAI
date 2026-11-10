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


def _team_label(raw: Any) -> str | None:
    """Expand nflverse abbrs when possible; keep full names as-is."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        from app.services.etl.nfl.anytime_td_features import _abbr_to_name

        return _abbr_to_name(text)
    except Exception:
        return text


def _row_name_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("player_display_name", "player_name"):
        val = str(row.get(field) or "").strip()
        if val:
            keys.add(_name_key(val))
    return keys


def _row_display_name(row: dict[str, Any]) -> str:
    # nflverse weekly uses abbreviated player_name (S.Diggs); Odds uses full names.
    return str(row.get("player_display_name") or row.get("player_name") or "").strip()


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
    best_by_player: dict[str, tuple[int, dict[str, Any]]] = {}
    for row in weekly_rows:
        pos = str(row.get("position") or "").upper()
        if pos not in SKILL_POSITIONS:
            continue
        if not _row_name_keys(row).intersection(wanted):
            continue
        pname = _row_display_name(row)
        if not pname:
            continue
        share = row.get("target_share")
        attempts = row.get("team_pass_attempts")
        if (
            attempts is None
            and share not in (None, 0, 0.0)
            and row.get("targets") is not None
        ):
            try:
                attempts = float(row["targets"]) / float(share)
            except (TypeError, ValueError, ZeroDivisionError):
                attempts = None
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
        team_raw = row.get("team_name") or row.get("recent_team") or row.get("team")
        team = _team_label(team_raw)
        sched = {}
        if team is not None:
            sched = schedule_by_team.get(str(team), {}) or schedule_by_team.get(
                str(team_raw), {}
            )
        opponent = _team_label(
            sched.get("opponent_team_name")
            or row.get("opponent_team_name")
            or row.get("opponent_team")
        )
        if not team or not opponent:
            continue
        player_id = str(row.get("player_id") or row.get("gsis_id") or pname)
        row_week = int(row.get("week") or 0)
        # Prefer the most recent weekly sample for usage; slate week stays ``week``.
        if row_week > week:
            continue
        payload = {
            "player_id": player_id,
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
            "game_env": game_env_by_team.get(str(team))
            or game_env_by_team.get(str(team_raw)),
            "opponent_defense": defense_by_team.get(str(opponent)),
        }
        prev = best_by_player.get(player_id)
        if prev is None or row_week >= prev[0]:
            best_by_player[player_id] = (row_week, payload)
    return [item[1] for item in best_by_player.values()]


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
