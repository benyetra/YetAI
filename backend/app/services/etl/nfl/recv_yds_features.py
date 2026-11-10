"""Receiving-yards feature rows for lined RB/WR/TE (ATD-adjacent usage priors)."""

from __future__ import annotations

from typing import Any

from app.services.etl.nfl.recv_yds_model import (
    expected_targets,
    model_receiving_yards,
)

SKILL_POSITIONS = frozenset({"RB", "WR", "TE"})
MODEL_VERSION = "recv_nonml_v2"

# Catch rate by position, for callers that only know yards per reception.
_CATCH_RATE = {"WR": 0.63, "TE": 0.72, "RB": 0.79}

# Confidence is how much of the player's current role we have actually seen:
# 0.50 with no games this season, rising to 0.725 at five or more. Picks need
# 0.70 (recv_yds_betting.MIN_CONFIDENCE), so a player returning from injury or
# new to a team is shown but not recommended.
BASE_CONFIDENCE = 0.50
CONFIDENCE_PER_GAME = 0.045
CONFIDENCE_GAMES_CAP = 5
LEGACY_THIN_CONFIDENCE = 0.55


def _yards_per_target(player: dict[str, Any], position: str) -> float | None:
    """Yards per target: given directly, or catch rate × yards per reception."""
    for key in ("yards_per_target", "ypt"):
        value = player.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    ypr = player.get("ypr")
    if ypr is None:
        return None
    try:
        catch_rate = player.get("catch_rate")
        rate = float(catch_rate) if catch_rate is not None else _CATCH_RATE[position]
        return float(ypr) * min(1.0, max(0.0, rate))
    except (TypeError, ValueError, KeyError):
        return None


def _confidence(player: dict[str, Any]) -> float:
    games = player.get("current_season_games")
    if games is None:
        return LEGACY_THIN_CONFIDENCE
    try:
        seen = min(float(games), CONFIDENCE_GAMES_CAP)
    except (TypeError, ValueError):
        return LEGACY_THIN_CONFIDENCE
    return round(BASE_CONFIDENCE + CONFIDENCE_PER_GAME * max(0.0, seen), 3)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _depth_adj(adot: float | None, position: str) -> float:
    if adot is None:
        return 1.0
    # Mild lean: deeper aDOT → slightly more yards per target path.
    baseline = {"WR": 10.0, "TE": 7.5, "RB": 4.5}.get(position, 8.0)
    return _clamp(1.0 + 0.02 * ((float(adot) - baseline) / 5.0), 0.9, 1.1)


def _pace_adj(game_env: dict[str, Any] | None) -> float:
    if not game_env:
        return 1.0
    team_pass = game_env.get("implied_team_pass_attempts")
    league_avg = float(game_env.get("league_avg_pass_attempts") or 34.0)
    if team_pass is None or league_avg <= 0:
        return 1.0
    return _clamp(float(team_pass) / league_avg, 0.85, 1.15)


def _matchup_adj(opponent_defense: dict[str, Any] | None, position: str) -> float:
    if not opponent_defense:
        return 1.0
    # Prefer position-allowed YPR / recv yards index when present (1.0 = average).
    key = f"{position.lower()}_recv_yards_index"
    idx = opponent_defense.get(key, opponent_defense.get("recv_yards_index"))
    if idx is None:
        return 1.0
    return _clamp(float(idx), 0.85, 1.15)


def build_recv_feature_row(
    player: dict[str, Any],
    *,
    game_env: dict[str, Any] | None = None,
    opponent_defense: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    pos = str(player.get("position") or "").upper()
    if pos not in SKILL_POSITIONS:
        return None

    share = player.get("target_share")
    attempts = player.get("team_pass_attempts")
    targets = expected_targets(target_share=share, team_pass_attempts=attempts)
    ypt = _yards_per_target(player, pos)
    if targets is None or ypt is None or ypt <= 0:
        return None

    depth = _depth_adj(player.get("adot"), pos)
    pace = _pace_adj(game_env)
    matchup = _matchup_adj(opponent_defense, pos)
    model_yards = model_receiving_yards(
        expected_targets=targets,
        yards_per_target=ypt,
        depth_adj=depth,
        pace_adj=pace,
        matchup_adj=matchup,
    )
    confidence = _confidence(player)

    ypr = player.get("ypr")
    features = {
        "target_share": float(share),
        "team_pass_attempts": float(attempts),
        "expected_targets": targets,
        "yards_per_target": ypt,
        "catch_rate": player.get("catch_rate"),
        "ypr": float(ypr) if ypr is not None else None,
        "games": player.get("games"),
        "current_season_games": player.get("current_season_games"),
        "adot": player.get("adot"),
        "depth_adj": depth,
        "pace_adj": pace,
        "matchup_adj": matchup,
        "snap_pct": player.get("snap_pct"),
        "targets_from_line": False,
        "ou_line_ignored_for_features": player.get("ou_line"),
    }

    return {
        "player_id": str(player["player_id"]),
        "player_name": player["player_name"],
        "position": pos,
        "team_name": player["team_name"],
        "opponent_team_name": player["opponent_team_name"],
        "game_date": player["game_date"],
        "season": int(player["season"]),
        "week": int(player["week"]),
        "expected_targets": targets,
        "yards_per_target": ypt,
        "ypr": float(ypr) if ypr is not None else None,
        "depth_adj": depth,
        "pace_adj": pace,
        "matchup_adj": matchup,
        "model_yards": model_yards,
        "confidence_score": confidence,
        "features": features,
        "model_version": MODEL_VERSION,
    }
