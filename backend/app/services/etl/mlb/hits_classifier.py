"""Offline MLB hits-board ML prototype (no S3 / pickle dependency).

Shadow mode: ``predict_p_one_plus_hit`` is a calibrated logistic-style score used
in backtest A/B against ``combined_score_heuristic`` from ``hits.py``.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


def _sigmoid(z: float) -> float:
    z = max(-20.0, min(20.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def predict_p_one_plus_hit(features_dict: Mapping[str, Any]) -> float:
    """P(team records >= 1 hit) from rolling BA, pitcher WHIP/K9, park, home/away.

    Args:
        features_dict: keys ``rolling_ba`` (or ``lineup_avg``), ``pitcher_whip``,
            ``pitcher_k9``, ``park_factor``, ``is_home`` (0/1).

    Returns:
        Probability in [0, 1], rounded to 4 decimals.
    """
    ba = float(
        features_dict.get("rolling_ba", features_dict.get("lineup_avg", 0.25)) or 0.25
    )
    whip = float(features_dict.get("pitcher_whip", 1.35) or 1.35)
    k9 = float(features_dict.get("pitcher_k9", 8.0) or 8.0)
    park = float(features_dict.get("park_factor", 1.0) or 1.0)
    is_home = float(features_dict.get("is_home", 0.0) or 0.0)

    z = (
        2.8 * (ba - 0.250)
        - 0.85 * (whip - 1.200)
        - 0.04 * (k9 - 8.0)
        + 0.35 * (park - 1.0)
        + 0.18 * is_home
        - 0.15
    )
    return round(_sigmoid(z), 4)


def build_lineup_hit_features(
    side: str,
    lineup_data: Mapping[str, Any],
    pitcher_stats: Mapping[str, Any],
    features: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Feature dict for ``predict_p_one_plus_hit`` at team/lineup granularity."""
    features = features or {}
    opp = "away" if side == "home" else "home"
    p_stats = pitcher_stats.get(f"{opp}_pitcher_stats", {}) or {}

    ops = float(features.get(f"{side}_lineup_ops", 0.72) or 0.72)
    batters = lineup_data.get(f"{side}_batters") or []
    if batters:
        avgs = [
            float(
                b.get("season_avg_vs_handed", b.get("batting_average_vs_handedness"))
                or 0
            )
            for b in batters
            if b.get("season_avg_vs_handed") or b.get("batting_average_vs_handedness")
        ]
        if avgs:
            ops = sum(avgs) / len(avgs)

    return {
        "rolling_ba": ops,
        "lineup_avg": ops,
        "pitcher_whip": float(p_stats.get("whip", 1.35) or 1.35),
        "pitcher_k9": float(p_stats.get("k9", 8.0) or 8.0),
        "park_factor": float(features.get("park_factor", 1.0) or 1.0),
        "is_home": 1.0 if side == "home" else 0.0,
    }
