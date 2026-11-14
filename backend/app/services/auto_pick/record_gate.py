"""
Record gate: withhold (league, market, stat) keys whose recent record is measurably losing.

A key's record blends two sources, both over the last WINDOW_DAYS:
- bet record: graded AUTO YetAIBet rows, units at the stored odds;
- projection record: the model's published over/under calls graded vs the line they
  were published with (high volume prior), valued at -110 because rows store no price.
The blend is shrunk toward a 50% hit rate at -110 (like the NBA totals record gate in
etl/nba/totals_baseline.py), so a thin sample never withholds a key.

Records are recomputed every run from data that keeps being graded while a key is
withheld, so re-admission is automatic.
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
# Units won per 1u stake at -110.
_WIN_110 = 100 / 110

DEFAULT_MIN_PICKS = 30
DEFAULT_WINDOW_DAYS = 90
DEFAULT_MIN_ROI = 0.0
DEFAULT_PRIOR_MAX_PICKS = 60
DEFAULT_SHRINK_PICKS = 20
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
    """Blend bet + projection records and shrink toward 50% at -110 (pure)."""
    scale = min(1.0, prior_max_picks() / proj_n) if proj_n else 1.0
    proj_units = proj_hits * _WIN_110 - (proj_n - proj_hits)
    shrink = shrink_picks()
    shrink_units = shrink * (0.5 * _WIN_110 - 0.5)
    n_eff = proj_n * scale + bet_n
    shrunk_roi = (proj_units * scale + bet_units + shrink_units) / (n_eff + shrink)
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


# Projection loaders: name -> fn(db, start, end) -> {key: (hits, graded)}; dates inclusive.
ProjectionLoader = Callable[[Session, date, date], dict[RecordKey, tuple[int, int]]]

_NBA_PROP_STATS = {
    "points_ou": ("points", "actual_points"),
    "three_pt_ou": ("threes", "actual_three_pt_made"),
    "steals_ou": ("steals", "actual_steals"),
    "assists_ou": ("assists", "actual_assists"),
    "rebounds_ou": ("rebounds", "actual_rebounds"),
}


def _nba_props(db, start, end):
    from app.services.nba_accuracy_service import _nba_season_window_rows

    out = {}
    for part, _label, rows, _merge in _nba_season_window_rows(db, start=start, end=end):
        if part not in _NBA_PROP_STATS:
            continue
        stat, actual_field = _NBA_PROP_STATS[part]
        hits, n = ou_call_graded_counts(
            rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field=actual_field,
        )
        out[("NBA", "player_prop", stat)] = (hits, n)
    return out


def _nba_totals(db, start, end):
    from app.models.predictions_models import NBATotalsActuals
    from app.services.etl.nba.totals_baseline import CALIBRATION_START, pick_record

    # Rows before calibration came from the old model (same rule as the totals gate).
    start = max(start, CALIBRATION_START)
    rows = (
        db.query(NBATotalsActuals)
        .filter(NBATotalsActuals.game_date >= start, NBATotalsActuals.game_date <= end)
        .all()
    )
    return {("NBA", "total", None): pick_record(rows)}


def _nba_spread(db, start, end):
    from app.models.predictions_models import NBASpreadActuals, NBASpreadProjections
    from app.services.nfl_accuracy_service import _merge_actuals_spread

    def q(model):
        return (
            db.query(model)
            .filter(model.game_date >= start, model.game_date <= end)
            .all()
        )

    rows = _merge_actuals_spread(q(NBASpreadProjections), q(NBASpreadActuals))
    return {
        ("NBA", "spread", None): edge_play_graded_counts(
            rows, pick_field="recommendation", correct_field="spread_correct"
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


def load_projection_records(
    db: Session, now: datetime
) -> dict[RecordKey, tuple[int, int]]:
    """{key: (hits, graded)} over [today - window, today): today's results never leak in."""
    today = utc_to_eastern(now).date()  # slate dates are US Eastern
    start, end = today - timedelta(days=window_days()), today - timedelta(days=1)
    out: dict[RecordKey, tuple[int, int]] = {}
    for name, loader in PROJECTION_LOADERS.items():
        try:
            # Savepoint: on Postgres a failed statement aborts the whole transaction.
            with db.begin_nested():
                out.update(loader(db, start, end))
        except Exception:
            log.exception("record_gate: projection loader %s failed", name)
    return out


def load_records(db: Session, now: datetime) -> dict[RecordKey, KeyRecord]:
    bets = load_bet_records(db, now)
    projs = load_projection_records(db, now)
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
