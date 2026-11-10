"""Receiving-yards feature rows for lined RB/WR/TE (ATD-adjacent usage priors)."""

from __future__ import annotations

from typing import Any

from app.services.etl.nfl.recv_yds_model import (
    expected_targets,
    model_receiving_yards,
)

SKILL_POSITIONS = frozenset({"RB", "WR", "TE"})
MODEL_VERSION = "recv_nonml_v1"


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
    ypr = player.get("ypr")
    targets = expected_targets(target_share=share, team_pass_attempts=attempts)
    if targets is None or ypr is None:
        return None
    try:
        ypr_f = float(ypr)
    except (TypeError, ValueError):
        return None
    if ypr_f <= 0:
        return None

    depth = _depth_adj(player.get("adot"), pos)
    pace = _pace_adj(game_env)
    matchup = _matchup_adj(opponent_defense, pos)
    model_yards = model_receiving_yards(
        expected_targets=targets,
        ypr=ypr_f,
        depth_adj=depth,
        pace_adj=pace,
        matchup_adj=matchup,
    )

    thin = (
        player.get("adot") is None
        or not game_env
        or not opponent_defense
        or player.get("snap_pct") is None
    )
    confidence = 0.55 if thin else 0.72

    features = {
        "target_share": float(share),
        "team_pass_attempts": float(attempts),
        "expected_targets": targets,
        "ypr": ypr_f,
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
        "ypr": ypr_f,
        "depth_adj": depth,
        "pace_adj": pace,
        "matchup_adj": matchup,
        "model_yards": model_yards,
        "confidence_score": confidence,
        "features": features,
        "model_version": MODEL_VERSION,
    }
