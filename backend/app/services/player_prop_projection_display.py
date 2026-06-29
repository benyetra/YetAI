"""Shared display fields for player-prop projection API rows.

Adds edge, pick, confidence (0–100), and value_tier (strong/lean) so every
sport with prop projections surfaces bet-worthy rows consistently.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy.orm import Session

from app.services.etl.yetiwatch.news import attach_news_to_rows

ValueTier = Literal["strong", "lean"]

# Minimum |projected - line| to emit a directional pick (stat-specific).
EDGE_THRESHOLDS: dict[str, float] = {
    "points": 1.0,
    "assists": 0.5,
    "rebounds": 0.5,
    "three_pt_made": 0.5,
    "steals": 0.3,
    "blocks": 0.3,
    "pra": 1.5,
    "strikeouts": 0.75,
    "saves": 2.0,
    "shots": 0.5,
    "passing_yards": 15.0,
}

# |edge| at or above this maps confidence to 100%.
FULL_CONFIDENCE_EDGE: dict[str, float] = {
    "points": 3.0,
    "assists": 1.5,
    "rebounds": 1.5,
    "three_pt_made": 1.5,
    "steals": 1.0,
    "blocks": 1.0,
    "pra": 4.0,
    "strikeouts": 3.0,
    "saves": 5.0,
    "shots": 1.5,
    "passing_yards": 40.0,
}

_NO_PLAY = frozenset({"", "NO_PLAY", "PASS", "N", "NONE", "NO PLAY"})


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_pick(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper in _NO_PLAY:
        return None
    if upper in {"O", "OVER"}:
        return "OVER"
    if upper in {"U", "UNDER"}:
        return "UNDER"
    if "OVER" in upper:
        return "OVER"
    if "UNDER" in upper:
        return "UNDER"
    return upper


def _recommendation_from_edge(edge: float, threshold: float) -> str:
    if abs(edge) < threshold:
        return "NO_PLAY"
    return "OVER" if edge > 0 else "UNDER"


def prop_confidence_pct(abs_edge: float, stat: str) -> float:
    """Map edge magnitude to 0–100 confidence."""
    full = FULL_CONFIDENCE_EDGE.get(stat, 2.0)
    if full <= 0:
        return 0.0
    return round(min(100.0, (abs_edge / full) * 100.0), 1)


def value_tier_for_play(
    pick: str | None,
    abs_edge: float,
    threshold: float,
    *,
    edge_category: str | None = None,
    confidence_pct: float | None = None,
) -> ValueTier | None:
    """strong = high edge; lean = actionable but smaller edge."""
    if not pick:
        return None
    cat = (edge_category or "").strip().upper()
    if cat == "HIGH":
        return "strong"
    if cat == "MEDIUM":
        return "lean"
    if confidence_pct is not None and confidence_pct >= 80 and abs_edge >= threshold:
        return "strong"
    if abs_edge >= threshold * 2:
        return "strong"
    if abs_edge >= threshold:
        return "lean"
    if confidence_pct is not None and confidence_pct >= 65:
        return "lean"
    return None


def enrich_projection_vs_line(
    row: dict[str, Any],
    *,
    projected_key: str,
    line_key: str,
    stat: str,
    pick_key: str | None = None,
    recommendation_key: str = "recommendation",
    edge_key: str = "edge",
    confidence_key: str = "confidence_score",
) -> dict[str, Any]:
    """Enrich a row with edge, recommendation, confidence, value_tier."""
    out = dict(row)
    projected = _as_float(out.get(projected_key))
    line = _as_float(out.get(line_key))
    threshold = EDGE_THRESHOLDS.get(stat, 1.0)

    if projected is None or line is None or line <= 0:
        out.setdefault(edge_key, None)
        out.setdefault(recommendation_key, "NO_PLAY")
        out.setdefault(confidence_key, None)
        out["value_tier"] = None
        return out

    edge = round(projected - line, 2)
    out[edge_key] = edge

    pick = _normalize_pick(out.get(pick_key)) if pick_key else None
    if pick is None:
        pick = _normalize_pick(out.get(recommendation_key))
    if pick is None:
        rec = _recommendation_from_edge(edge, threshold)
        out[recommendation_key] = rec
        pick = _normalize_pick(rec)
    else:
        out[recommendation_key] = pick

    conf = _as_float(out.get(confidence_key))
    if conf is None or conf <= 1.0:
        conf = prop_confidence_pct(abs(edge), stat)
        out[confidence_key] = conf
    elif conf <= 1.0:
        out[confidence_key] = round(conf * 100.0, 1)
        conf = out[confidence_key]

    out["value_tier"] = value_tier_for_play(
        pick,
        abs(edge),
        threshold,
        confidence_pct=conf,
    )
    return out


def enrich_nba_prop_row(row: dict[str, Any], stat: str) -> dict[str, Any]:
    """NBA/WNBA-style rows: fanduel_line + fanduel_over_under."""
    projected_key = {
        "points": "projected_points",
        "assists": "projected_assists",
        "rebounds": "projected_rebounds",
        "three_pt_made": "projected_three_pt_made",
        "steals": "projected_steals",
        "blocks": "projected_blocks",
        "pra": "projected_pra",
    }.get(stat, f"projected_{stat}")

    out = enrich_projection_vs_line(
        row,
        projected_key=projected_key,
        line_key="fanduel_line",
        stat=stat,
        pick_key="fanduel_over_under",
        recommendation_key="recommendation",
        edge_key="edge",
        confidence_key="pick_confidence",
    )
    if out.get("pick_confidence") is not None:
        out["confidence_score"] = out["pick_confidence"]
    return out


def enrich_wnba_prop_row(row: dict[str, Any], stat: str) -> dict[str, Any]:
    """WNBA rows use market_line and recommendation."""
    projected_key = f"projected_{stat}"
    return enrich_projection_vs_line(
        row,
        projected_key=projected_key,
        line_key="market_line",
        stat=stat,
        recommendation_key="recommendation",
        edge_key="edge",
        confidence_key="confidence_score",
    )


def enrich_nhl_prop_row(row: dict[str, Any], stat: str) -> dict[str, Any]:
    """NHL goalie saves / player shots rows."""
    if stat == "saves":
        projected_key = "predicted_saves"
        line_key = "saves_line"
    else:
        projected_key = "predicted_shots"
        line_key = "shots_line"

    out = enrich_projection_vs_line(
        row,
        projected_key=projected_key,
        line_key=line_key,
        stat=stat,
        pick_key="betting_recommendation",
        recommendation_key="recommendation",
        edge_key="edge",
        confidence_key="confidence",
    )
    edge = _as_float(out.get("edge"))
    edge_saves = _as_float(out.get("edge_saves"))
    abs_edge = abs(edge if edge is not None else (edge_saves or 0.0))
    pick = _normalize_pick(out.get("recommendation"))
    conf = _as_float(out.get("confidence"))
    out["value_tier"] = value_tier_for_play(
        pick,
        abs_edge,
        EDGE_THRESHOLDS.get(stat, 1.0),
        edge_category=out.get("edge_category"),
        confidence_pct=conf,
    )
    return out


def enrich_strikeout_display_row(row: dict[str, Any]) -> dict[str, Any]:
    """Add value_tier to MLB strikeout rows (pick_confidence already set)."""
    out = dict(row)
    edge = _as_float(out.get("k_edge"))
    conf = _as_float(out.get("pick_confidence"))
    pick = _normalize_pick(out.get("yetai_pick") or out.get("fanduel_over_under"))
    threshold = EDGE_THRESHOLDS["strikeouts"]
    abs_edge = abs(edge) if edge is not None else 0.0
    out["value_tier"] = value_tier_for_play(
        pick,
        abs_edge,
        threshold,
        confidence_pct=conf,
    )
    if conf is not None:
        out["confidence_score"] = conf
    return out


def enrich_nfl_qb_row(row: dict[str, Any]) -> dict[str, Any]:
    """NFL QB passing-yard O/U rows."""
    out = enrich_projection_vs_line(
        row,
        projected_key="predicted_passing_yards",
        line_key="ou_line",
        stat="passing_yards",
        pick_key="betting_recommendation",
        recommendation_key="recommendation",
        edge_key="edge",
        confidence_key="pick_confidence",
    )
    model_conf = _as_float(out.get("model_confidence"))
    if model_conf is not None and model_conf > 1.0:
        out["pick_confidence"] = round(
            0.6 * (out.get("pick_confidence") or 0) + 0.4 * model_conf, 1
        )
    edge_pct = _as_float(out.get("edge_percentage"))
    if edge_pct and edge_pct > 0 and out.get("pick_confidence"):
        out["pick_confidence"] = round(
            min(100.0, out["pick_confidence"] + min(10.0, edge_pct * 0.25)), 1
        )
    out["confidence_score"] = out.get("pick_confidence")
    return out


_NEWS_ENTITY_KEYS: dict[tuple[str, str], tuple[str, str]] = {
    ("nba", "points"): ("player_id", "date"),
    ("nba", "assists"): ("player_id", "date"),
    ("nba", "rebounds"): ("player_id", "date"),
    ("nba", "three_pt_made"): ("player_id", "date"),
    ("nba", "steals"): ("player_id", "date"),
    ("nba", "blocks"): ("player_id", "date"),
    ("nba", "pra"): ("player_id", "date"),
    ("wnba", "points"): ("player_id", "date"),
    ("wnba", "assists"): ("player_id", "date"),
    ("wnba", "rebounds"): ("player_id", "date"),
    ("mlb", "strikeouts"): ("pitcher_id", "date"),
    ("nfl", "passing_yards"): ("qb_player_id", "game_date"),
    ("nhl", "saves"): ("goalie_id", "game_date"),
    ("nhl", "shots"): ("player_id", "game_date"),
}


def enrich_prop_rows(
    rows: list[dict[str, Any]],
    *,
    sport: str,
    stat: str,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    """Batch enrich for predictions API responses."""
    if sport == "nba":
        enriched = [enrich_nba_prop_row(r, stat) for r in rows]
    elif sport == "wnba":
        enriched = [enrich_wnba_prop_row(r, stat) for r in rows]
    elif sport == "nhl":
        enriched = [enrich_nhl_prop_row(r, stat) for r in rows]
    elif sport == "mlb" and stat == "strikeouts":
        enriched = [enrich_strikeout_display_row(r) for r in rows]
    elif sport == "nfl" and stat == "passing_yards":
        enriched = [enrich_nfl_qb_row(r) for r in rows]
    else:
        enriched = rows

    keys = _NEWS_ENTITY_KEYS.get((sport, stat))
    if db and keys:
        entity_key, date_key = keys
        return attach_news_to_rows(
            db,
            enriched,
            sport=sport,
            entity_key=entity_key,
            date_key=date_key,
        )
    return enriched
