"""
Record gate: withhold (league, market, stat) keys whose recent record is measurably losing.

A key's record blends two sources, both over the last WINDOW_DAYS:
- bet record: graded AUTO YetAIBet rows, units at the stored odds;
- projection record: the model's published over/under calls graded vs the line they
  were published with (high volume prior), valued at -110 because rows store no price.
  Only calls the scorer could publish count: where the stored call is made at any edge
  (NBA props) rows below the fill-floor edge (``fill_floor_edge``) are left out.
The blend is shrunk toward breakeven (zero ROI; 52.38% at -110), so a thin sample never
withholds a key. A key is withheld only when its shrunk ROI is below MIN_ROI, a small
negative dead band under breakeven: the gate keeps no state, and re-deriving "was withheld
yesterday" from yesterday's ROI gives no memory beyond a day (a key parked inside the band
would flip daily), so the plain dead band is the simplest rule that does not flip.

Records are recomputed every run from data that keeps being graded while a key is
withheld, so re-admission is automatic.

Prove-in keys (AUTO_PICK_PROVE_IN_KEYS, default every NHL key) must earn their way in
whatever AUTO_PICK_REQUIRE_PROVEN_RECORD says: until the record has min_picks effective
graded calls at or above breakeven the key is withheld as ``unproven_record`` and runs
in shadow (its ETL keeps writing projections and lines, so the record builds). The
board applies the same rule to its pick labels (``withheld_keys``).
"""

import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database_models import BetSource, BetType, YetAIBet
from app.services.accuracy_shared import (
    edge_play_graded_counts,
    ou_call_graded_counts,
)
from app.services.auto_pick.candidate import BetCandidate, MarketType, utc_to_eastern
from app.services.auto_pick.context_builder import (
    _normalize_market_type,
    _normalize_sport,
)

log = logging.getLogger(__name__)

# (league, market, stat): stat is None for game markets.
RecordKey = tuple[str, str, Optional[str]]

BREAKEVEN_ODDS = -110

DEFAULT_MIN_PICKS = 30
DEFAULT_WINDOW_DAYS = 90
DEFAULT_MIN_ROI = -0.02
DEFAULT_PRIOR_MAX_PICKS = 60
DEFAULT_SHRINK_PICKS = 20
# Key labels (or label prefixes) that must prove in; "" turns prove-in off.
DEFAULT_PROVE_IN_KEYS = "NHL"
# historical_sub_score: 50 at breakeven ROI, +/-25 points per 10% ROI.
ROI_SCORE_SLOPE = 250.0


def _env_number(name: str, default, cast):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return cast(raw)
    except ValueError:
        log.warning("%s=%r is not a number; using %s", name, raw, default)
        return default


def gate_enabled() -> bool:
    return os.getenv("AUTO_PICK_RECORD_GATE_ENABLED", "true").strip().lower() == "true"


def require_proven_record() -> bool:
    """Opt-in: a key with fewer than min_picks effective graded calls is withheld too."""
    return (
        os.getenv("AUTO_PICK_REQUIRE_PROVEN_RECORD", "false").strip().lower() == "true"
    )


def prove_in_keys() -> list[str]:
    raw = os.getenv("AUTO_PICK_PROVE_IN_KEYS", DEFAULT_PROVE_IN_KEYS)
    return [p.strip() for p in raw.split(",") if p.strip()]


def prove_in_required(key: RecordKey) -> bool:
    """True when ``key`` (or a prefix of its label, e.g. "NHL") is a prove-in key."""
    label = key_label(key)
    return any(label == p or label.startswith(p + "/") for p in prove_in_keys())


def min_picks() -> int:
    return _env_number("AUTO_PICK_RECORD_MIN_PICKS", DEFAULT_MIN_PICKS, int)


def window_days() -> int:
    return _env_number("AUTO_PICK_RECORD_WINDOW_DAYS", DEFAULT_WINDOW_DAYS, int)


def min_roi() -> float:
    return _env_number("AUTO_PICK_RECORD_MIN_ROI", DEFAULT_MIN_ROI, float)


def prior_max_picks() -> int:
    return _env_number("AUTO_PICK_RECORD_PRIOR_MAX_PICKS", DEFAULT_PRIOR_MAX_PICKS, int)


def shrink_picks() -> int:
    return _env_number("AUTO_PICK_RECORD_SHRINK_PICKS", DEFAULT_SHRINK_PICKS, int)


@dataclass(frozen=True)
class KeyRecord:
    key: RecordKey
    bet_n: int
    bet_units: float
    proj_n: int
    proj_hits: int
    n_eff: float
    shrunk_roi: float
    withheld: bool


def record_key(c: BetCandidate) -> RecordKey:
    stat = (
        c.projection_metadata.get("stat")
        if c.market_type == MarketType.PLAYER_PROP
        else None
    )
    return (c.league, c.market_type.value, stat)


def key_label(key: RecordKey) -> str:
    return "/".join(p for p in key if p)


def drop_reason(
    rec: Optional[KeyRecord], key: Optional[RecordKey] = None
) -> Optional[str]:
    """Why the gate withholds a key, or None; ``rec`` None = no data for ``key``."""
    if rec is not None and rec.withheld:
        return "losing_record"
    if not gate_enabled():
        return None
    if require_proven_record() and (rec is None or rec.n_eff < min_picks()):
        return "unproven_record"
    key = rec.key if rec is not None else key
    if key is not None and prove_in_required(key):
        # Enough graded calls, at or above breakeven.
        if rec is None or rec.n_eff < min_picks() or rec.shrunk_roi < 0:
            return "unproven_record"
    return None


def stake_units(odds: float, won: bool) -> float:
    """Units per 1u stake at American ``odds``."""
    if not won:
        return -1.0
    return odds / 100 if odds > 0 else 100 / abs(odds)


def combine(
    key: RecordKey,
    *,
    bet_n: int = 0,
    bet_units: float = 0.0,
    proj_n: int = 0,
    proj_hits: int = 0,
) -> KeyRecord:
    """Blend bet + projection records and shrink toward breakeven, zero ROI (pure)."""
    scale = min(1.0, prior_max_picks() / proj_n) if proj_n else 1.0
    # Units at -110, in integers until the one division so breakeven is exactly 0.
    proj_units = (proj_hits * 100 - (proj_n - proj_hits) * 110) / 110
    n_eff = proj_n * scale + bet_n
    shrunk_roi = (proj_units * scale + bet_units) / (n_eff + shrink_picks())
    return KeyRecord(
        key=key,
        bet_n=bet_n,
        bet_units=bet_units,
        proj_n=proj_n,
        proj_hits=proj_hits,
        n_eff=n_eff,
        shrunk_roi=shrunk_roi,
        withheld=gate_enabled() and n_eff >= min_picks() and shrunk_roi < min_roi(),
    )


# ---------- loaders ----------


def load_bet_records(db: Session, now: datetime) -> dict[RecordKey, tuple[int, float]]:
    """{key: (graded bets, units)} for AUTO straight bets settled in [now - window, now)."""
    rows = (
        db.query(YetAIBet)
        .filter(
            YetAIBet.source == BetSource.AUTO,
            YetAIBet.status.in_(["won", "lost"]),
            YetAIBet.bet_type != BetType.PARLAY,
            YetAIBet.settled_at >= now - timedelta(days=window_days()),
            YetAIBet.settled_at < now,
        )
        .all()
    )
    out: dict[RecordKey, list] = defaultdict(lambda: [0, 0.0])
    for b in rows:
        pf = b.prediction_factors if isinstance(b.prediction_factors, dict) else {}
        g = pf.get("grading") or {}
        md = pf.get("projection_metadata") or {}
        bt = b.bet_type.value if hasattr(b.bet_type, "value") else str(b.bet_type)
        market = g.get("market") or _normalize_market_type(bt)
        league = g.get("league") or _normalize_sport(str(b.sport or "unknown"))
        stat = (g.get("stat") or md.get("stat")) if market == "player_prop" else None
        acc = out[(league, market, stat)]
        acc[0] += 1
        acc[1] += stake_units(b.odds, b.status == "won")
    return {k: (n, u) for k, (n, u) in out.items()}


# Which stored rows each prior grades (publishable calls only):
# - NBA props: the stored call is made at any edge, so rows are cut at fill_floor_edge.
# - NBA total and spread: the would-be calls of the CURRENT model version (the anchored
#   projectors' own version_pick_record), graded against the stored line, not the stored
#   recommendation, which is NO_PLAY while the version's record is unproven.
# - NFL spread, NFL total, NFL passing/receiving, NHL saves/total: rows are the
#   stored recommendation/pick (NO_PLAY and pushes excluded); their edge thresholds
#   live in each sport's ETL and were not compared with the fill-floor edge here.
# Projection loaders: name -> fn(db, start, end) -> {key: (hits, graded)}; dates inclusive.
ProjectionLoader = Callable[[Session, date, date], dict[RecordKey, tuple[int, int]]]

# part -> (stat, actual field, projected field)
_NBA_PROP_STATS = {
    "points_ou": ("points", "actual_points", "projected_points"),
    "three_pt_ou": ("threes", "actual_three_pt_made", "projected_three_pt_made"),
    "steals_ou": ("steals", "actual_steals", "projected_steals"),
    "assists_ou": ("assists", "actual_assists", "projected_assists"),
    "rebounds_ou": ("rebounds", "actual_rebounds", "projected_rebounds"),
}


def fill_floor_edge(stat: str) -> float:
    """Smallest raw edge at which a ``stat`` prop reaches the fill floor (pure).

    The other sub-scores are neutral: the scorer's own functions on a no-metadata
    candidate (no record, no movement, -110, fresh). Edge scores linearly in
    edge / edge_normalizer, so solve the weighted total for the edge sub-score.
    """
    from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
    from app.services.auto_pick.selector import SelectorConfig
    from app.services.auto_pick.sub_scores import (
        edge_normalizer,
        freshness_sub_score,
        historical_sub_score,
        line_movement_sub_score,
        model_confidence_sub_score,
        odds_sanity_sub_score,
    )

    c = BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="NBA",
        event_id="neutral",
        selection="neutral",
        market_line=10.0,
        market_odds=BREAKEVEN_ODDS,
        our_projection=10.0,
        projection_metadata={"stat": stat},
    )
    w = ScoringWeights()
    ctx = ScoringContext(weights=w, score_threshold=SelectorConfig().threshold)
    rest = (
        historical_sub_score(c, ctx) * w.historical
        + freshness_sub_score(c, ctx) * w.freshness
        + line_movement_sub_score(c, ctx) * w.line_movement
        + odds_sanity_sub_score(c, ctx) * w.odds_sanity
        + model_confidence_sub_score(c) * w.model_conf
    )
    edge_score = (SelectorConfig().min_score - rest) / w.edge
    return edge_score / 100.0 * edge_normalizer(c)


_NBA_STATS = {v[0] for v in _NBA_PROP_STATS.values()}


def _prop_qualifies(row, projected_field: str, min_edge: float) -> bool:
    """Could this stored call reach the fill floor as a pick?

    The flag on these rows is just the side of projection vs line at any edge; the
    source has no edge threshold, so the score decides: the projection must clear the
    line on the called side by ``min_edge`` (``fill_floor_edge``).
    """
    proj, line = row.get(projected_field), row.get("fanduel_line")
    if proj is None or line is None:
        return False
    over = str(row.get("fanduel_over_under") or "").strip().lower() in ("o", "over")
    return (proj - line if over else line - proj) >= min_edge


def _nba_props(db, start, end):
    from app.services.nba_accuracy_service import _nba_season_window_rows

    out = {}
    for part, _label, rows, _merge in _nba_season_window_rows(db, start=start, end=end):
        if part not in _NBA_PROP_STATS:
            continue
        stat, actual_field, proj_field = _NBA_PROP_STATS[part]
        min_edge = fill_floor_edge(stat)
        rows = [r for r in rows if _prop_qualifies(r, proj_field, min_edge)]
        hits, n = ou_call_graded_counts(
            rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field=actual_field,
        )
        out[("NBA", "player_prop", stat)] = (hits, n)
    return out


def _nba_totals(db, start, end):
    from app.services.etl.nba import totals_projector

    return {
        ("NBA", "total", None): totals_projector.version_pick_record(
            db, start, end + timedelta(days=1)
        )
    }


def _nba_spread(db, start, end):
    from app.services.etl.nba import spread_projector

    return {
        ("NBA", "spread", None): spread_projector.version_pick_record(
            db, start, end + timedelta(days=1)
        )
    }


def _nhl(db, start, end):
    from app.services.nhl_accuracy_service import _nhl_rows

    sets = _nhl_rows(db, start=start, end=end)
    return {
        ("NHL", "player_prop", "saves"): ou_call_graded_counts(
            sets["goalie"],
            line_field="saves_line",
            pick_field="betting_pick",
            actual_field="actual_saves",
        ),
        ("NHL", "player_prop", "shots"): ou_call_graded_counts(
            sets["player_shots"],
            line_field="shots_line",
            pick_field="betting_pick",
            actual_field="actual_shots",
        ),
        ("NHL", "total", None): ou_call_graded_counts(
            sets["team_totals"],
            line_field="draftkings_ou_line",
            pick_field="betting_pick",
            actual_field="actual_total_goals",
        ),
    }


def _nfl(db, start, end):
    from app.models.predictions_models import (
        NFLSpreadActuals,
        NFLSpreadProjections,
        NFLTotalsActuals,
        NFLTotalsProjections,
        QBActuals,
        QBPredictions,
        RecvYdsActuals,
        RecvYdsPredictions,
    )
    from app.services.nfl_accuracy_service import (
        _merge_actuals_qb_range,
        _merge_actuals_spread,
        _merge_actuals_totals,
    )

    def q(model):
        return (
            db.query(model)
            .filter(
                func.date(model.game_date) >= start, func.date(model.game_date) <= end
            )
            .all()
        )

    qb_rows = _merge_actuals_qb_range(q(QBPredictions), q(QBActuals))
    recv_act = {(a.player_id, a.game_date): a for a in q(RecvYdsActuals)}
    recv_rows = []
    for p in q(RecvYdsPredictions):
        a = recv_act.get((p.player_id, p.game_date))
        recv_rows.append(
            {
                "ou_line": p.ou_line,
                "betting_recommendation": p.betting_recommendation,
                "actual_receiving_yards": a.actual_receiving_yards if a else None,
            }
        )
    spread_rows = _merge_actuals_spread(q(NFLSpreadProjections), q(NFLSpreadActuals))
    totals_rows = _merge_actuals_totals(q(NFLTotalsProjections), q(NFLTotalsActuals))
    return {
        ("NFL", "player_prop", "passing_yards"): ou_call_graded_counts(
            qb_rows,
            line_field="ou_line",
            pick_field="betting_recommendation",
            actual_field="actual_passing_yards",
        ),
        ("NFL", "player_prop", "receiving_yards"): ou_call_graded_counts(
            recv_rows,
            line_field="ou_line",
            pick_field="betting_recommendation",
            actual_field="actual_receiving_yards",
        ),
        ("NFL", "spread", None): edge_play_graded_counts(
            spread_rows, pick_field="recommendation", correct_field="spread_correct"
        ),
        ("NFL", "total", None): ou_call_graded_counts(
            totals_rows,
            line_field="market_total",
            pick_field="recommendation",
            actual_field="actual_total",
        ),
    }


# Keys without a projection record (bet record only): NBA moneyline / pra props,
# WNBA and MLB (off-season), and any key a new source adds.
PROJECTION_LOADERS: dict[str, ProjectionLoader] = {
    "nba_props": _nba_props,
    "nba_totals": _nba_totals,
    "nba_spread": _nba_spread,
    "nhl": _nhl,
    "nfl": _nfl,
}


def _prop_keys(league: str, specs) -> set[RecordKey]:
    return {(league, "player_prop", spec[1]) for spec in specs}


def emitted_keys() -> dict[str, set[RecordKey]]:
    """Keys each registered source can emit, by source class name.

    Static: sources do not declare their keys. tests/auto_pick/test_record_gate.py fails
    when a source registered in tasks.auto_pick._build_providers is missing here.
    """
    from app.services.auto_pick.sources.player_prop_source import _NBA_STAT_SPECS
    from app.services.auto_pick.sources.wnba_player_prop_source import (
        _WNBA_STAT_SPECS,
    )

    return {
        "PlayerPropSource": _prop_keys("NBA", _NBA_STAT_SPECS),
        "NBASpreadSource": {("NBA", "spread", None)},
        "NBATotalsSource": {("NBA", "total", None)},
        "NBAMoneylineSource": {("NBA", "moneyline", None)},
        "MLBStrikeoutSource": {("MLB", "player_prop", "strikeouts")},
        "MLBGameMoneylineSource": {("MLB", "moneyline", None)},
        "NHLGoalieSavesSource": {("NHL", "player_prop", "saves")},
        "NHLTotalsSource": {("NHL", "total", None)},
        "NFLQBPassingSource": {("NFL", "player_prop", "passing_yards")},
        "NFLReceivingYardsSource": {("NFL", "player_prop", "receiving_yards")},
        "NFLSpreadSource": {("NFL", "spread", None)},
        "NFLTotalsSource": {("NFL", "total", None)},
        "WNBAPlayerPropSource": _prop_keys("WNBA", _WNBA_STAT_SPECS),
        "WNBASpreadSource": {("WNBA", "spread", None)},
        "WNBATotalsSource": {("WNBA", "total", None)},
    }


def load_projection_records(
    db: Session, now: datetime, loaders: Optional[tuple[str, ...]] = None
) -> dict[RecordKey, tuple[int, int]]:
    """{key: (hits, graded)} over [today - window, today): today's results never leak in.

    ``loaders`` limits the run to those PROJECTION_LOADERS names (default all).
    """
    today = utc_to_eastern(now).date()  # slate dates are US Eastern
    start, end = today - timedelta(days=window_days()), today - timedelta(days=1)
    out: dict[RecordKey, tuple[int, int]] = {}
    for name, loader in PROJECTION_LOADERS.items():
        if loaders is not None and name not in loaders:
            continue
        try:
            # Savepoint: on Postgres a failed statement aborts the whole transaction.
            with db.begin_nested():
                out.update(loader(db, start, end))
        except Exception:
            log.exception("record_gate: projection loader %s failed", name)
    return out


def load_records(
    db: Session, now: datetime, loaders: Optional[tuple[str, ...]] = None
) -> dict[RecordKey, KeyRecord]:
    bets = load_bet_records(db, now)
    projs = load_projection_records(db, now, loaders)
    return {
        key: combine(
            key,
            bet_n=bets.get(key, (0, 0.0))[0],
            bet_units=bets.get(key, (0, 0.0))[1],
            proj_hits=projs.get(key, (0, 0))[0],
            proj_n=projs.get(key, (0, 0))[1],
        )
        for key in set(bets) | set(projs)
    }


def withheld_keys(
    db: Session, now: datetime, keys: set[RecordKey], loaders: tuple[str, ...]
) -> dict[RecordKey, str]:
    """{key: drop reason} for the ``keys`` the gate withholds; the board shows pick
    labels only for the others. ``loaders`` names the projection loaders for ``keys``.
    """
    # ponytail: recomputed per request (one sport's loader, bounded to the window);
    # cache per Eastern date if the board gets slow.
    records = load_records(db, now, loaders)
    reasons = {k: drop_reason(records.get(k), k) for k in keys}
    return {k: r for k, r in reasons.items() if r}


def gate_report(db: Session, now: datetime) -> list[dict]:
    """Per-key gate decision for the dry-run CLI (read-only: only the loaders run)."""
    rows = []
    records = load_records(db, now)
    for keys in emitted_keys().values():
        for key in keys:
            records.setdefault(key, combine(key))
    for key, r in sorted(records.items(), key=lambda kv: key_label(kv[0])):
        rows.append(
            {
                "key": key_label(key),
                "bet_n": r.bet_n,
                "bet_units": round(r.bet_units, 2),
                "proj_n": r.proj_n,
                "proj_hits": r.proj_hits,
                "prior_hit_rate": r.proj_hits / r.proj_n if r.proj_n else None,
                "n_eff": round(r.n_eff, 1),
                "shrunk_roi": round(r.shrunk_roi, 4),
                "withheld": r.withheld,
                "state": (
                    "WITHHELD losing"
                    if r.withheld
                    else (
                        (
                            "WITHHELD unproven (prove-in key)"
                            if prove_in_required(key)
                            else "WITHHELD unproven"
                        )
                        if drop_reason(r) == "unproven_record"
                        else (
                            "unproven (would be withheld with AUTO_PICK_REQUIRE_PROVEN_RECORD)"
                            if r.n_eff < min_picks()
                            else "open"
                        )
                    )
                ),
                "qualifying_edge": (
                    round(fill_floor_edge(key[2]), 3)
                    if key[:2] == ("NBA", "player_prop") and key[2] in _NBA_STATS
                    else None
                ),
            }
        )
    return rows
