"""Attach Odds API ``player_anytime_td`` lines and market-anchor publish layer."""

from __future__ import annotations

import logging
import os
import statistics
from datetime import datetime
from typing import Any

from app.core.database import SessionLocal
from app.models.predictions_models import NFLAnytimeTDPredictions
from app.services.etl.nfl.anytime_td_market_anchor import (
    ANYTIME_TD_EDGE_THRESHOLD,
    american_ev,
    american_to_implied_prob,
    blend_publish_prob,
    market_anchor_signal_score,
    recommendation_for_market_edge,
    shrink_weight,
    stamp_market_model_version,
    vig_free_fair_prob,
)
from app.services.etl.nfl.nfl_common import get_current_nfl_week, resolve_nfl_season
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

# Re-export threshold for callers/tests that import it from this module.
ODDS_API_KEY_ENV = "ODDS_API_KEY"
ODDS_BASE_URL = "https://api.the-odds-api.com/v4/sports"
SPORT = "americanfootball_nfl"
MARKET = "player_anytime_td"
BOOKMAKER_PRIORITY = ["pinnacle", "fanduel", "draftkings", "betmgm"]
SHARP_BOOK = "pinnacle"
SOFT_BOOKS = ("fanduel", "draftkings", "betmgm")

BETTING_UPDATE_KEYS = [
    "td_probability",
    "confidence_score",
    "features",
    "model_version",
    "market_odds",
    "market_implied_prob",
    "edge",
    "recommendation",
]

_MARKET_FEATURE_KEYS = (
    "p_publish",
    "market_fair_prob",
    "market_fair_src",
    "market_anchor_signal",
    "market_shrink_w",
    "market_ev_yes",
    "market_odds_no",
    "market_book",
    "market_as_of",
    "near_market",
)


def _restore_model_probability(pred: NFLAnytimeTDPredictions) -> dict[str, Any]:
    """Clear betting columns and restore board P from ``features.p_model``."""
    betting = clear_betting_fields()
    feat = dict(pred.features or {})
    for key in _MARKET_FEATURE_KEYS:
        feat.pop(key, None)
    p_model = float(
        feat.get("p_model") if feat.get("p_model") is not None else pred.td_probability
    )
    feat["p_model"] = p_model
    feat.setdefault("p_hier", p_model)
    snap = feat.get("snap_pct")
    confidence = min(1.0, float(snap) * p_model * 1.2) if snap is not None else p_model
    base_version = str(pred.model_version or "hierarchical_v1")
    if base_version.endswith("_mkt"):
        base_version = base_version[: -len("_mkt")]
    betting["td_probability"] = p_model
    betting["features"] = feat
    betting["model_version"] = base_version or "hierarchical_v1"
    betting["confidence_score"] = confidence
    return betting


def compute_edge(td_probability: float, implied_prob: float) -> float:
    """Edge vs the comparison probability (fair market under Option B)."""
    return float(td_probability) - float(implied_prob)


def recommendation_for_edge(
    edge: float,
    *,
    threshold: float = ANYTIME_TD_EDGE_THRESHOLD,
    ev: float | None = None,
) -> str:
    """Backward-compatible wrapper; prefer ``recommendation_for_market_edge``."""
    if ev is None:
        # Legacy callers without EV: OVER on edge only (tests / old paths).
        return "OVER" if edge >= threshold else "NO_PLAY"
    return recommendation_for_market_edge(edge, ev=ev, threshold=threshold)


def clear_betting_fields() -> dict[str, Any]:
    """Null betting columns when Odds attach fails or a row is unmatched."""
    return {
        "market_odds": None,
        "market_implied_prob": None,
        "edge": None,
        "recommendation": None,
    }


def attach_betting_fields(
    *,
    td_probability: float,
    market_odds: int,
    market_odds_no: int | None = None,
    features: dict[str, Any] | None = None,
    model_version: str | None = None,
    book: str | None = None,
    last_update: str | None = None,
) -> dict[str, Any]:
    """Attach fair market, publish anchored P, and Edge/Pick vs fair."""
    feat = dict(features or {})
    p_model = float(
        feat.get("p_model") if feat.get("p_model") is not None else td_probability
    )
    p_fair, fair_src = vig_free_fair_prob(market_odds, market_odds_no)
    signal = market_anchor_signal_score(feat)
    w = shrink_weight(signal)
    p_pub = blend_publish_prob(p_fair, p_model, w)
    edge = compute_edge(p_pub, p_fair)
    ev = american_ev(p_pub, market_odds)
    rec = recommendation_for_market_edge(edge, ev=ev)

    feat["p_model"] = p_model
    feat.setdefault("p_hier", p_model)
    feat["p_publish"] = p_pub
    feat["market_fair_prob"] = p_fair
    feat["market_fair_src"] = fair_src
    feat["market_anchor_signal"] = signal
    feat["market_shrink_w"] = w
    feat["market_ev_yes"] = ev
    feat["market_odds_no"] = market_odds_no
    feat["market_book"] = book
    feat["market_as_of"] = last_update
    feat["near_market"] = abs(edge) < 0.02

    snap = feat.get("snap_pct")
    confidence = min(1.0, float(snap) * p_pub * 1.2) if snap is not None else p_pub

    return {
        "td_probability": p_pub,
        "confidence_score": confidence,
        "features": feat,
        "model_version": stamp_market_model_version(model_version),
        "market_odds": int(market_odds),
        # Column stores vig-free fair P (Edge baseline under Option B).
        "market_implied_prob": p_fair,
        "edge": edge,
        "recommendation": rec,
    }


def normalize_player_name(name: str) -> str:
    cleaned = (
        name.replace(" Jr.", "")
        .replace(" Sr.", "")
        .replace(" III", "")
        .replace(" II", "")
    )
    aliases = {
        "CJ Stroud": "C.J. Stroud",
        "DJ Moore": "D.J. Moore",
        "AJ Brown": "A.J. Brown",
    }
    return aliases.get(cleaned, cleaned)


def _compact_name(name: str) -> str:
    cleaned = normalize_player_name(name).lower()
    return "".join(ch for ch in cleaned if ch.isalnum())


def _name_first_last(name: str) -> tuple[list[str], str]:
    parts = normalize_player_name(name).split()
    if not parts:
        return [], ""
    return parts[:-1], parts[-1].lower()


def parse_player_anytime_td_book_quotes(
    odds_payload: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Extract per-book Yes/No quotes keyed by player description."""
    by_player: dict[str, list[dict[str, Any]]] = {}
    for bookmaker in odds_payload.get("bookmakers", []):
        book_key = str(bookmaker.get("key") or "").lower()
        last_update = bookmaker.get("last_update")
        yes_by_player: dict[str, int] = {}
        no_by_player: dict[str, int] = {}
        for market in bookmaker.get("markets", []):
            if market.get("key") != MARKET:
                continue
            for outcome in market.get("outcomes", []):
                player = outcome.get("description")
                price = outcome.get("price")
                if not player or price is None:
                    continue
                name = str(outcome.get("name", "")).lower()
                price_i = int(price)
                if name == "yes":
                    yes_by_player[player] = price_i
                elif name == "no":
                    no_by_player[player] = price_i
        for player, yes_price in yes_by_player.items():
            by_player.setdefault(player, []).append(
                {
                    "yes": yes_price,
                    "no": no_by_player.get(player),
                    "book": book_key or None,
                    "last_update": last_update,
                }
            )
    return by_player


def consensus_anytime_td_quote(
    quotes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Prefer Pinnacle Yes(+No); else median Yes among soft books (pair No)."""
    if not quotes:
        return None
    for q in quotes:
        if str(q.get("book") or "").lower() == SHARP_BOOK and q.get("yes") is not None:
            return {
                "yes": int(q["yes"]),
                "no": int(q["no"]) if q.get("no") is not None else None,
                "book": SHARP_BOOK,
                "last_update": q.get("last_update"),
            }

    soft = [
        q
        for q in quotes
        if str(q.get("book") or "").lower() in SOFT_BOOKS and q.get("yes") is not None
    ]
    pool = soft or [q for q in quotes if q.get("yes") is not None]
    if not pool:
        return None
    yes_prices = sorted(int(q["yes"]) for q in pool)
    median_yes = int(statistics.median(yes_prices))
    exact = [q for q in pool if int(q["yes"]) == median_yes]
    chosen = (
        exact[0] if exact else min(pool, key=lambda q: abs(int(q["yes"]) - median_yes))
    )
    return {
        "yes": int(chosen["yes"]),
        "no": int(chosen["no"]) if chosen.get("no") is not None else None,
        "book": chosen.get("book"),
        "last_update": chosen.get("last_update"),
    }


def parse_player_anytime_td_outcomes(odds_payload: dict[str, Any]) -> dict[str, int]:
    """Backward-compatible: consensus Yes American per player from one event."""
    out: dict[str, int] = {}
    for player, quotes in parse_player_anytime_td_book_quotes(odds_payload).items():
        cons = consensus_anytime_td_quote(quotes)
        if cons is not None:
            out[player] = int(cons["yes"])
    return out


def match_player_odds(
    prediction_name: str,
    odds_by_player: dict[str, Any],
) -> Any | None:
    """Match prediction name to odds map (exact → compact → last-name).

    Values may be Yes ints (legacy) or quote dicts with a ``yes`` key.
    """
    pred_norm = normalize_player_name(prediction_name).lower()
    pred_compact = _compact_name(prediction_name)
    pred_first_parts, pred_last = _name_first_last(prediction_name)

    entries: list[tuple[str, str, Any]] = []
    for odds_name, value in odds_by_player.items():
        entries.append(
            (
                normalize_player_name(odds_name).lower(),
                _compact_name(odds_name),
                value,
            )
        )

    for odds_norm, _, value in entries:
        if pred_norm == odds_norm:
            return value

    for _, odds_compact, value in entries:
        if pred_compact == odds_compact:
            return value

    if not pred_last:
        return None

    last_matches: list[Any] = []
    for odds_norm, _, value in entries:
        odds_first_parts, odds_last = _name_first_last(odds_norm)
        if odds_last != pred_last:
            continue
        if not pred_first_parts:
            last_matches.append(value)
            continue
        if not odds_first_parts:
            last_matches.append(value)
            continue
        pred_first = pred_first_parts[0].lower()
        odds_first = odds_first_parts[0].lower()
        if pred_first == odds_first:
            last_matches.append(value)
            continue
        if odds_first and pred_first[0] == odds_first[0]:
            last_matches.append(value)

    if len(last_matches) == 1:
        return last_matches[0]
    return None


def _quote_from_match(matched: Any) -> dict[str, Any] | None:
    if matched is None:
        return None
    if isinstance(matched, dict) and matched.get("yes") is not None:
        return {
            "yes": int(matched["yes"]),
            "no": int(matched["no"]) if matched.get("no") is not None else None,
            "book": matched.get("book"),
            "last_update": matched.get("last_update"),
        }
    try:
        return {"yes": int(matched), "no": None, "book": None, "last_update": None}
    except (TypeError, ValueError):
        return None


def _odds_get(path: str, params: dict[str, Any]):
    api_key = os.environ.get(ODDS_API_KEY_ENV)
    if not api_key:
        logger.warning("%s not set; skipping anytime TD odds fetch", ODDS_API_KEY_ENV)
        return None
    from app.services.odds_api_sync import sync_odds_get

    return sync_odds_get(
        f"{ODDS_BASE_URL}/{path}",
        params={"apiKey": api_key, **params},
        caller=f"etl.nfl.anytime_td_betting.{path}",
        timeout=30,
        raise_for_status=False,
    )


def fetch_anytime_td_odds() -> dict[str, dict[str, Any]]:
    """Fetch consensus ``player_anytime_td`` quotes for upcoming NFL events."""
    from app.services.odds_api_service import sport_in_season

    if not sport_in_season(SPORT):
        logger.info("NFL off-season — skipping anytime TD odds fetch")
        return {}

    events_resp = _odds_get(f"{SPORT}/events", {"dateFormat": "iso"})
    if events_resp is None or events_resp.status_code != 200:
        code = events_resp.status_code if events_resp is not None else "blocked"
        logger.warning("Failed to fetch NFL events for anytime TD: %s", code)
        return {}

    merged_quotes: dict[str, list[dict[str, Any]]] = {}
    for game in events_resp.json():
        event_id = game.get("id")
        if not event_id:
            continue
        odds_resp = _odds_get(
            f"{SPORT}/events/{event_id}/odds",
            {
                "regions": "us",
                "markets": MARKET,
                "oddsFormat": "american",
                "bookmakers": ",".join(BOOKMAKER_PRIORITY),
            },
        )
        if odds_resp is None or odds_resp.status_code != 200:
            continue
        for player, quotes in parse_player_anytime_td_book_quotes(
            odds_resp.json()
        ).items():
            merged_quotes.setdefault(player, []).extend(quotes)

    out: dict[str, dict[str, Any]] = {}
    for player, quotes in merged_quotes.items():
        cons = consensus_anytime_td_quote(quotes)
        if cons is not None:
            out[player] = cons
    return out


def _prediction_to_upsert_row(
    pred: NFLAnytimeTDPredictions,
    betting: dict[str, Any],
) -> dict[str, Any]:
    return {
        "season": pred.season,
        "week": pred.week,
        "game_date": pred.game_date,
        "player_id": pred.player_id,
        "player_name": pred.player_name,
        "position": pred.position,
        "team_name": pred.team_name,
        "opponent_team_name": pred.opponent_team_name,
        "expected_tds": pred.expected_tds,
        "td_probability": betting.get("td_probability", pred.td_probability),
        "confidence_score": betting.get("confidence_score", pred.confidence_score),
        "features": betting.get("features", pred.features),
        "model_version": betting.get("model_version", pred.model_version),
        "prediction_date": pred.prediction_date,
        "created_at": pred.created_at or datetime.utcnow(),
        "market_odds": betting.get("market_odds"),
        "market_implied_prob": betting.get("market_implied_prob"),
        "edge": betting.get("edge"),
        "recommendation": betting.get("recommendation"),
    }


def _had_stale_betting(pred: NFLAnytimeTDPredictions) -> bool:
    return (
        pred.market_odds is not None
        or pred.market_implied_prob is not None
        or pred.edge is not None
        or pred.recommendation is not None
    )


def run(*, season: int | None = None, week: int | None = None) -> dict[str, Any]:
    """Load predictions, attach market-anchored odds/edge/pick (or clear stale)."""
    resolved_season = resolve_nfl_season(season)
    resolved_week = week if week is not None else get_current_nfl_week(resolved_season)

    odds_by_player = fetch_anytime_td_odds()
    fetch_empty = not odds_by_player

    db = SessionLocal()
    try:
        predictions = (
            db.query(NFLAnytimeTDPredictions)
            .filter_by(season=resolved_season, week=resolved_week)
            .all()
        )
        upsert_rows: list[dict[str, Any]] = []
        matched = 0
        stale_cleared = 0

        for pred in predictions:
            if fetch_empty:
                betting = _restore_model_probability(pred)
                if _had_stale_betting(pred):
                    stale_cleared += 1
                upsert_rows.append(_prediction_to_upsert_row(pred, betting))
                continue

            quote = _quote_from_match(
                match_player_odds(pred.player_name, odds_by_player)
            )
            if quote is None:
                betting = _restore_model_probability(pred)
                if _had_stale_betting(pred):
                    stale_cleared += 1
                upsert_rows.append(_prediction_to_upsert_row(pred, betting))
                continue

            matched += 1
            betting = attach_betting_fields(
                td_probability=float(pred.td_probability),
                market_odds=int(quote["yes"]),
                market_odds_no=quote.get("no"),
                features=dict(pred.features or {}),
                model_version=pred.model_version,
                book=quote.get("book"),
                last_update=quote.get("last_update"),
            )
            upsert_rows.append(_prediction_to_upsert_row(pred, betting))

        if upsert_rows:
            upsert_many(
                db,
                NFLAnytimeTDPredictions,
                upsert_rows,
                conflict_keys=["season", "week", "player_id"],
                update_keys=BETTING_UPDATE_KEYS,
            )
            db.commit()

        return {
            "status": "ok",
            "season": resolved_season,
            "week": resolved_week,
            "predictions": len(predictions),
            "matched": matched,
            "stale_cleared": stale_cleared,
            "blocked": 1 if fetch_empty else 0,
            "updated": len(upsert_rows),
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
