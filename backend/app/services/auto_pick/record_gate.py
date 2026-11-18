"""
Record gate: withhold (league, market, stat) keys whose record at real prices is losing,
and keep unproven keys out until they have a record.

A key's record blends two sources, both over the last WINDOW_DAYS and both valued only at
real stored prices (nothing is ever valued at an assumed -110):
- projection record: the SHADOW record of the selector. For NBA props it is every stored
  row of the current model version that is priced (best line, best price, consensus fair
  probability) and that the selector's own EV rule (``ev.prop_ev`` / ``ev.gate_reason``)
  would have considered, graded at that best line and price. Withheld candidates that pass
  the hard gates are exactly these rows, graded by the normal actuals ETL; nothing is
  written anywhere for them, so nothing can reach a user. Loaders whose rows carry no
  stored price (NFL, NHL shots, NBA totals and spread) cannot be valued: their graded calls
  are kept as ``unpriced_n`` for display and count toward nothing. NHL saves and totals
  are valued at the stored odds of the picked side where the row has them.
- bet record: graded AUTO YetAIBet rows of the current ``ev.SELECTION_VERSION`` (a new
  selection version starts a new record), units at the stored odds. Added only for keys
  with no projection loader result: where a shadow record exists the bets are a subset of
  it and adding them would count them twice.

The sum is shrunk toward zero ROI by SHRINK_PICKS pseudo-picks, so a thin sample reads
near breakeven. A key is withheld as losing when it has at least MIN_PICKS (30) effective
calls and its shrunk ROI is below ``losing_threshold``: MIN_ROI (-2%, a dead band so a key
parked at breakeven does not flip daily) below LARGE_SAMPLE (300) calls, plain 0 from there.
Records are recomputed every run from data that keeps being graded while a key is
withheld, so re-admission is automatic.

Proving in: a key must show PROVE_IN_MIN_PICKS (100) effective priced calls over at least
PROVE_IN_MIN_DATES (10) slate dates at or above breakeven before it opens when AUTO_PICK_REQUIRE_PROVEN_RECORD is on (the default) or the
key is a prove-in key (AUTO_PICK_PROVE_IN_KEYS). Until then it is withheld as
``unproven_record`` and runs in shadow (its ETL keeps writing projections, so the record
builds). The board applies the same rule to its pick labels (``withheld_keys``).
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
    ou_call_graded_record,
    ou_row_result,
)
from app.services.auto_pick import ev
from app.services.auto_pick.candidate import BetCandidate, MarketType, utc_to_eastern
from app.services.mlb_strikeout_pick import signed_edge_for_side
from app.services.auto_pick.context_builder import (
    _normalize_market_type,
    _normalize_sport,
)

log = logging.getLogger(__name__)

# (league, market, stat): stat is None for game markets.
RecordKey = tuple[str, str, Optional[str]]

DEFAULT_MIN_PICKS = 30
DEFAULT_WINDOW_DAYS = 90
DEFAULT_MIN_ROI = -0.02
DEFAULT_SHRINK_PICKS = 20
# 30 = the smallest sample a key can be judged losing on.
# 100 = the sample a key needs to open: at 30 calls a no-edge market at real prices shows
# ROI >= 0 about 40% of the time (one 1u bet at -125 has sd ~0.95, so the standard error of
# ROI at n=30 is ~17 points); at 100 it is about a third. Proving in is a floor, not proof.
PROVE_IN_MIN_PICKS = 100
# Rows of one night share games, pace and blowouts, so the 100 calls must also span this
# many slate dates before a key opens.
PROVE_IN_MIN_DATES = 10
# 300 = the sample the review's F8 and the fair-price shadow decision use: from here a
# key is withheld on any negative ROI, with no dead band.
LARGE_SAMPLE = 300
# Key labels (or label prefixes) that must prove in; "" turns prove-in off. NBA moneyline,
# MLB and WNBA have no projection record at all, NBA PRA has never been measured.
DEFAULT_PROVE_IN_KEYS = (
    "NHL,NBA/player_prop/steals,NBA/player_prop/blocks,NBA/player_prop/pra,"
    "NBA/moneyline,MLB,WNBA"
)
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
    """On by default: a key without PROVE_IN_MIN_PICKS priced calls at breakeven is withheld."""
    return (
        os.getenv("AUTO_PICK_REQUIRE_PROVEN_RECORD", "true").strip().lower() == "true"
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


def losing_threshold(n_eff: float) -> float:
    """Shrunk ROI below which a key is losing: the dead band, then plain 0 at scale."""
    return min_roi() if n_eff < LARGE_SAMPLE else 0.0


def shrink_picks() -> int:
    return _env_number("AUTO_PICK_RECORD_SHRINK_PICKS", DEFAULT_SHRINK_PICKS, int)


@dataclass(frozen=True)
class KeyRecord:
    key: RecordKey
    bet_n: int
    bet_units: float
    proj_n: int
    proj_hits: int
    proj_units: float  # at stored prices; priced calls only
    n_eff: float  # priced calls: proj_n + bet_n
    shrunk_roi: float
    withheld: bool
    unpriced_n: int = 0  # graded calls with no stored price: display only
    version: Optional[str] = None  # model version the projection record used
    bet_hits: int = 0
    dates: int = 0  # distinct slate dates with a graded priced call


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
    key = rec.key if rec is not None else key
    if require_proven_record() or (key is not None and prove_in_required(key)):
        if (
            rec is None
            or rec.n_eff < PROVE_IN_MIN_PICKS
            or rec.dates < PROVE_IN_MIN_DATES
            or rec.shrunk_roi < 0
        ):
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
    bet_hits: int = 0,
    proj_n: int = 0,
    proj_hits: int = 0,
    proj_units: Optional[float] = None,
    unpriced_n: int = 0,
    version: Optional[str] = None,
    dates: int = 0,
) -> KeyRecord:
    """Sum the priced bet + projection records and shrink toward zero ROI (pure).

    ``proj_n`` / ``proj_units`` are priced calls only; there is no cap on the projection
    record, a large sample counts in full.
    """
    units = proj_units or 0.0
    n_eff = proj_n + bet_n
    shrunk_roi = (units + bet_units) / (n_eff + shrink_picks())
    return KeyRecord(
        key=key,
        bet_n=bet_n,
        bet_units=bet_units,
        proj_n=proj_n,
        proj_hits=proj_hits,
        proj_units=units,
        n_eff=n_eff,
        shrunk_roi=shrunk_roi,
        withheld=(
            gate_enabled()
            and n_eff >= min_picks()
            and shrunk_roi < losing_threshold(n_eff)
        ),
        unpriced_n=unpriced_n,
        version=version,
        bet_hits=bet_hits,
        dates=dates,
    )


# ---------- loaders ----------


def load_bet_records(
    db: Session, now: datetime
) -> dict[RecordKey, tuple[int, float, int, int]]:
    """{key: (graded bets, units, wins, distinct settle dates)} for AUTO straight bets of the
    current selection version settled in [now - window, now)."""
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
    out: dict[RecordKey, list] = defaultdict(lambda: [0, 0.0, 0, set()])
    for b in rows:
        pf = b.prediction_factors if isinstance(b.prediction_factors, dict) else {}
        if pf.get("selection_version") != ev.SELECTION_VERSION:
            continue
        g = pf.get("grading") or {}
        md = pf.get("projection_metadata") or {}
        bt = b.bet_type.value if hasattr(b.bet_type, "value") else str(b.bet_type)
        market = g.get("market") or _normalize_market_type(bt)
        league = g.get("league") or _normalize_sport(str(b.sport or "unknown"))
        stat = (g.get("stat") or md.get("stat")) if market == "player_prop" else None
        acc = out[(league, market, stat)]
        acc[0] += 1
        acc[1] += stake_units(b.odds, b.status == "won")
        acc[2] += b.status == "won"
        acc[3].add(utc_to_eastern(b.settled_at).date())
    return {k: (n, u, w, len(d)) for k, (n, u, w, d) in out.items()}


# Which stored rows each projection record grades:
# - NBA props: the shadow record of the selector (see the module docstring), priced.
# - NBA total and spread: the would-be calls of the CURRENT model version (the anchored
#   projectors' own version_pick_record), graded against the stored line, not the stored
#   recommendation, which is NO_PLAY while the version's record is unproven. No stored
#   price: unpriced.
# - NFL spread, NFL total, NFL passing/receiving, NHL saves/shots/total: rows are the
#   stored recommendation/pick (NO_PLAY and pushes excluded), current model version only.
#   NFL rows and NHL shots carry no price: unpriced. NHL saves and totals rows carry the
#   stored over/under odds of the picked side (``pick_price``): those calls are priced,
#   the ones without odds are unpriced. NHL still cannot be picked (no consensus price).
# Projection loaders: name -> fn(db, start, end) -> {key: (hits, graded, units, version)};
# dates inclusive. ``units`` (at stored prices) is None when the rows carry no price: those
# calls are unpriced and count toward nothing. Optional 5th/6th elements: distinct graded
# slate dates and graded calls left unpriced. A bare (hits, graded) is also accepted.
ProjectionLoader = Callable[[Session, date, date], dict[RecordKey, tuple]]

# part -> (stat, actual field, projected field)
_NBA_PROP_STATS = {
    "points_ou": ("points", "actual_points", "projected_points"),
    "three_pt_ou": ("threes", "actual_three_pt_made", "projected_three_pt_made"),
    "steals_ou": ("steals", "actual_steals", "projected_steals"),
    "assists_ou": ("assists", "actual_assists", "projected_assists"),
    "rebounds_ou": ("rebounds", "actual_rebounds", "projected_rebounds"),
    "pra_ou": ("pra", "actual_pra", "projected_pra"),
}


def _field(row, name):
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def _as_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else date.min


def current_version_rows(rows, date_field: str):
    """(version, rows of that version): the model_version most rows on the latest
    ``date_field`` carry (ties: the version of the newest row by ``projected_at``, then
    ``id``), so one stray backfilled row cannot switch the record. None is a version too:
    the unversioned legacy model. Rows are dicts or objects."""
    rows = list(rows)
    if not rows:
        return None, []
    last = max(_as_date(_field(r, date_field)) for r in rows)
    latest = [r for r in rows if _as_date(_field(r, date_field)) == last]
    counts: dict = defaultdict(int)
    for r in latest:
        counts[_field(r, "model_version")] += 1

    def rank(r):
        return (
            counts[_field(r, "model_version")],
            _field(r, "projected_at") or datetime.min,
            _field(r, "id") or 0,
        )

    version = _field(max(latest, key=rank), "model_version")
    return version, [r for r in rows if _field(r, "model_version") == version]


def _priced_shadow_rows(stat: str, proj_field: str, rows):
    """Rows the selector would have considered: priced, not low-sample, with a side, a
    positive edge at the best line, inside the default odds bounds, passing the EV gates.
    Not applied: one pick per game, the daily caps and freshness (the row is its last
    write of the day)."""
    from app.services.auto_pick.selector import SelectorConfig

    bounds = SelectorConfig()
    out = []
    for r in rows:
        if r.get("low_sample") is True:  # prop_rows never offers these as candidates
            continue
        line, price, fair = (
            r.get("best_line"),
            r.get("best_price"),
            r.get("best_fair_prob"),
        )
        proj = r.get(proj_field)
        side = str(r.get("fanduel_over_under") or "").strip().lower()[:1]
        if None in (line, price, fair, proj) or side not in ("o", "u"):
            continue
        if not bounds.odds_min <= price <= bounds.odds_max:
            continue
        # hard_gate_reason's non_positive_edge, at the shopped line we would publish
        if signed_edge_for_side(proj, line, "over" if side == "o" else "under") <= 0:
            continue
        e = ev.prop_ev(stat, side, proj, line, price, fair)
        if ev.gate_reason(e) is None:
            out.append(r)
    return out


def _nba_props(db, start, end):
    from app.services.nba_accuracy_service import _nba_season_window_rows

    out = {}
    for part, _label, rows, _merge in _nba_season_window_rows(db, start=start, end=end):
        if part not in _NBA_PROP_STATS:
            continue
        stat, actual_field, proj_field = _NBA_PROP_STATS[part]
        version, rows = current_version_rows(rows, "date")
        shadow = _priced_shadow_rows(stat, proj_field, rows)
        fields = dict(
            line_field="best_line",
            pick_field="fanduel_over_under",
            actual_field=actual_field,
        )
        hits, n, units, _priced = ou_call_graded_record(
            shadow, price_field="best_price", **fields
        )
        dates = {
            r.get("date")
            for r in shadow
            if ou_row_result(
                line=r.get("best_line"),
                pick=(r.get("fanduel_over_under") or "").strip().lower(),
                actual=r.get(actual_field),
            )
            in ("hit", "miss")
        }
        out[("NBA", "player_prop", stat)] = (hits, n, units, version, len(dates))
    return out


def _nba_totals(db, start, end):
    from app.services.etl.nba import totals_projector

    hits, n = totals_projector.version_pick_record(db, start, end + timedelta(days=1))
    return {("NBA", "total", None): (hits, n, None, totals_projector.MODEL_VERSION)}


def _nba_spread(db, start, end):
    from app.services.etl.nba import spread_projector

    hits, n = spread_projector.version_pick_record(db, start, end + timedelta(days=1))
    return {
        ("NBA", "spread", None): (hits, n, None, spread_projector.SPREAD_MODEL_VERSION)
    }


# NHL rows written before the 2026-11-14 input repair (YetAI-5p8) came from stale
# inputs and the old formulas: they say nothing about the repaired model, so the
# record (and the prove-in) starts from the repaired rows only.
NHL_PRE_REPAIR_MODEL_VERSIONS = (None, "", "heuristic-v1")


def _unpriced(rows, version, **fields):
    hits, n = ou_call_graded_counts(rows, **fields)
    return (hits, n, None, version)


def _graded_dates(rows, *, date_field, line_field, pick_field, actual_field) -> int:
    return len(
        {
            r.get(date_field)
            for r in rows
            if ou_row_result(
                line=r.get(line_field),
                pick=(r.get(pick_field) or "").strip().lower(),
                actual=r.get(actual_field),
            )
            in ("hit", "miss")
        }
    )


def _priced_calls(rows, version, *, price_field, date_field, **fields):
    """Record of the rows with a stored price for their side, valued at that price; the
    rest are counted as unpriced (6th element) and never valued at an assumed price."""
    priced = [r for r in rows if r.get(price_field) is not None]
    if not priced:
        return _unpriced(rows, version, **fields)
    hits, n, units, _ = ou_call_graded_record(priced, price_field=price_field, **fields)
    _, unpriced_n = ou_call_graded_counts(
        [r for r in rows if r.get(price_field) is None], **fields
    )
    dates = _graded_dates(priced, date_field=date_field, **fields)
    return (hits, n, units, version, dates, unpriced_n)


def _nhl(db, start, end):
    from app.services.nhl_accuracy_service import _nhl_rows

    sets, versions = {}, {}
    for part, rows in _nhl_rows(db, start=start, end=end).items():
        rows = [
            r
            for r in rows
            if r.get("model_version") not in NHL_PRE_REPAIR_MODEL_VERSIONS
        ]
        versions[part], sets[part] = current_version_rows(rows, "game_date")
    return {
        ("NHL", "player_prop", "saves"): _priced_calls(
            sets["goalie"],
            versions["goalie"],
            price_field="pick_price",
            date_field="game_date",
            line_field="saves_line",
            pick_field="betting_pick",
            actual_field="actual_saves",
        ),
        ("NHL", "player_prop", "shots"): _unpriced(
            sets["player_shots"],
            versions["player_shots"],
            line_field="shots_line",
            pick_field="betting_pick",
            actual_field="actual_shots",
        ),
        ("NHL", "total", None): _priced_calls(
            sets["team_totals"],
            versions["team_totals"],
            price_field="pick_price",
            date_field="game_date",
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

    qb_version, qb_preds = current_version_rows(q(QBPredictions), "game_date")
    qb_rows = _merge_actuals_qb_range(qb_preds, q(QBActuals))
    recv_act = {(a.player_id, a.game_date): a for a in q(RecvYdsActuals)}
    recv_version, recv_preds = current_version_rows(q(RecvYdsPredictions), "game_date")
    recv_rows = []
    for p in recv_preds:
        a = recv_act.get((p.player_id, p.game_date))
        recv_rows.append(
            {
                "ou_line": p.ou_line,
                "betting_recommendation": p.betting_recommendation,
                "actual_receiving_yards": a.actual_receiving_yards if a else None,
            }
        )
    spread_version, spread_preds = current_version_rows(
        q(NFLSpreadProjections), "game_date"
    )
    spread_rows = _merge_actuals_spread(spread_preds, q(NFLSpreadActuals))
    totals_version, totals_preds = current_version_rows(
        q(NFLTotalsProjections), "game_date"
    )
    totals_rows = _merge_actuals_totals(totals_preds, q(NFLTotalsActuals))
    spread_hits, spread_n = edge_play_graded_counts(
        spread_rows, pick_field="recommendation", correct_field="spread_correct"
    )
    return {
        ("NFL", "player_prop", "passing_yards"): _unpriced(
            qb_rows,
            qb_version,
            line_field="ou_line",
            pick_field="betting_recommendation",
            actual_field="actual_passing_yards",
        ),
        ("NFL", "player_prop", "receiving_yards"): _unpriced(
            recv_rows,
            recv_version,
            line_field="ou_line",
            pick_field="betting_recommendation",
            actual_field="actual_receiving_yards",
        ),
        ("NFL", "spread", None): (spread_hits, spread_n, None, spread_version),
        ("NFL", "total", None): _unpriced(
            totals_rows,
            totals_version,
            line_field="market_total",
            pick_field="recommendation",
            actual_field="actual_total",
        ),
    }


# Keys without a projection record (bet record only): NBA moneyline, WNBA and MLB, and
# any key a new source adds.
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
) -> dict[RecordKey, tuple]:
    """{key: (hits, graded[, units[, version]])} over [today - window, today): today's results never leak in.

    ``loaders`` limits the run to those PROJECTION_LOADERS names (default all).
    """
    today = utc_to_eastern(now).date()  # slate dates are US Eastern
    start, end = today - timedelta(days=window_days()), today - timedelta(days=1)
    out: dict[RecordKey, tuple] = {}
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
    out = {}
    for key, (hits, n, *rest) in projs.items():
        units, version, dates, more_unpriced = (*rest, *(None, None, 0, 0)[len(rest) :])
        priced = units is not None
        out[key] = combine(
            key,
            proj_hits=hits if priced else 0,
            proj_n=n if priced else 0,
            proj_units=units,
            unpriced_n=more_unpriced if priced else n,
            version=version,
            dates=dates if priced else 0,
        )
    # Bets only for keys with no projection record: otherwise they are a subset of it.
    for key in set(bets) - set(projs):
        bet_n, bet_units, bet_hits, bet_dates = bets[key]
        out[key] = combine(
            key, bet_n=bet_n, bet_units=bet_units, bet_hits=bet_hits, dates=bet_dates
        )
    return out


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


def all_key_rows(db: Session, now: datetime) -> list[dict]:
    """One row per key the gate knows (every emitted key plus every key a loader or the bet
    record returned), sorted by label. Read-only: only the loaders run."""
    records = load_records(db, now)
    for keys in emitted_keys().values():
        for key in keys:
            records.setdefault(key, combine(key))
    rows = []
    for key, r in sorted(records.items(), key=lambda kv: key_label(kv[0])):
        reason = drop_reason(r)
        rows.append(
            {
                "key": key_label(key),
                "n": r.proj_n + r.bet_n,
                "hits": r.proj_hits + r.bet_hits,
                "units": round(r.proj_units + r.bet_units, 2),
                "n_eff": round(r.n_eff, 1),
                "shrunk_roi": round(r.shrunk_roi, 4),
                "version": r.version,
                "selection_version": ev.SELECTION_VERSION,
                "unpriced_n": r.unpriced_n,
                "bet_n": r.bet_n,
                "dates": r.dates,
                "state": (
                    "open"
                    if reason is None
                    else (
                        "withheld-losing"
                        if reason == "losing_record"
                        else "withheld-unproven"
                    )
                ),
                "reason": reason,
            }
        )
    return rows


gate_report = all_key_rows  # the CLI's old name
