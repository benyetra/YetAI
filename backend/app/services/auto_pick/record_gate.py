"""
Record gate: withhold (league, market, stat) keys whose record at real prices is losing,
and keep unproven keys out until they have a record.

A key's record blends two sources, both over the last WINDOW_DAYS and both valued only at
real stored prices (nothing is ever valued at an assumed -110):
- projection record: the SHADOW record of the selector. For NBA props it is every stored
  row of the current model version that is priced (best line, best price, consensus fair
  probability) and that the selector's own EV rule (``ev.prop_ev`` / ``ev.gate_reason``)
  would have considered, graded at that best line and price. The game-line keys (NBA and
  NFL spread, total, moneyline) and the NFL passing / receiving yards and NHL saves / total
  keys do the same through the consensus shadow loaders below: the rows become candidates
  by the sources' own functions and providers and pass the selector's clock-free hard
  gates and the EV gates. Withheld candidates that pass the gates are exactly these rows,
  graded by the normal actuals ETL; nothing is written anywhere for them, so nothing can
  reach a user. NHL shots (no stored price) cannot be valued: their graded calls are kept
  as ``unpriced_n`` for display and count toward nothing, as do the rows of the other keys
  that have no best quote.
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
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database_models import BetSource, BetType, YetAIBet
from app.services.accuracy_shared import (
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
# - NBA / NFL spread, total, moneyline, NFL passing / receiving yards, NHL saves / total:
#   the consensus shadow below (``_shadow``), priced at the best quote; rows with no best
#   quote are ``unpriced_n``. Current model version only.
# - NHL shots: rows are the stored pick (NO_PLAY and pushes excluded), current version
#   only, no price: unpriced.
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


# The selector's odds bounds as the run reads them (the admin scoring-config row), set for the
# duration of one record load so every shadow record and the board use the same numbers as
# the selector. Outside a load: the defaults.
_BOUNDS: ContextVar = ContextVar("record_gate_odds_bounds", default=None)


def odds_bounds(db):
    """(odds_min, odds_max) the selector's hard gate uses: the loaded scoring config, the
    defaults when it cannot be read (orchestrator.run reads cfg.odds_min / cfg.odds_max).
    """
    from app.services.auto_pick.config_loader import load_scoring_config
    from app.services.auto_pick.selector import SelectorConfig

    try:
        with db.begin_nested():
            cfg = load_scoring_config(db)
        return cfg.odds_min, cfg.odds_max
    except Exception:
        log.exception("record_gate: scoring config unreadable; default odds bounds")
        d = SelectorConfig()
        return d.odds_min, d.odds_max


def current_odds_bounds():
    from app.services.auto_pick.selector import SelectorConfig

    return _BOUNDS.get() or (SelectorConfig().odds_min, SelectorConfig().odds_max)


def _priced_shadow_rows(stat: str, proj_field: str, rows):
    """Rows the selector would have considered: priced, not low-sample, with a side, a
    positive edge at the best line, inside the default odds bounds, passing the EV gates.
    Not applied: one pick per game, the daily caps and freshness (the row is its last
    write of the day)."""
    odds_min, odds_max = current_odds_bounds()
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
        if not odds_min <= price <= odds_max:
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


# NHL rows written before the 2026-11-14 input repair (YetAI-5p8) came from stale
# inputs and the old formulas: they say nothing about the repaired model, so the
# record (and the prove-in) starts from the repaired rows only.
NHL_PRE_REPAIR_MODEL_VERSIONS = (None, "", "heuristic-v1")


def _unpriced(rows, version, **fields):
    hits, n = ou_call_graded_counts(rows, **fields)
    return (hits, n, None, version)


# ---------- consensus shadow record: game lines, NFL and NHL props ----------
#
# The record of these keys is built like the NBA props one: every stored row of the CURRENT
# model version becomes a candidate through the same code the selector's sources use (their
# pure row functions, then the unchanged providers) and is kept only when it passes the
# selector's own hard gates that do not depend on the clock (valid side, raw_edge > 0, the
# default odds bounds, not odds_assumed / injury_flag, ``ev.candidate_ev`` with no reason).
# It is graded at the best line and price (``best_line`` / ``best_price``; ``ml_best_price``
# for moneylines) on the side ``best_side`` names, with the one grading definition
# (``yetai_grading.game_result``, ``_compare``); a push counts for nothing.
# Rows with no best quote that would still have a side are counted as ``unpriced_n``:
# display only, never valued. Not applied: freshness, start time, one pick per game, caps.

_CLOCKLESS_NOW = datetime(
    2000, 1, 1, 5
)  # midnight Eastern: no start-time gate can fire


class _Rows:
    """Source shim: hands a provider rows that are already built."""

    def __init__(self, rows):
        self.rows = rows

    async def get_todays_projections(self, _date_range):
        return self.rows


def _candidates(provider_cls, rows) -> list:
    """The provider's BetCandidates for ``rows``. The provider's coroutine never suspends
    (its source just returns the rows), so it is driven by hand: no event loop is needed
    and it is safe inside a request."""
    if not rows:
        return []
    coro = provider_cls(_Rows(rows)).get_candidates(None)
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    coro.close()
    raise RuntimeError("candidate provider suspended")


def _passes_gates(c, now=None):
    """The selector's hard gates and the EV gates on a BetCandidate: the EV when it passes,
    else None. The record passes no ``now``: the clock-free gates only (no freshness, no
    start time). The live board passes the real clock and gets every gate the selector
    applies (stale_line, started_or_starting, start_time_unknown too). Odds bounds are the
    loaded scoring config's (see ``odds_bounds``)."""
    from types import SimpleNamespace

    from app.services.auto_pick.selector import hard_gate_reason

    odds_min, odds_max = current_odds_bounds()
    scored = SimpleNamespace(candidate=c)  # hard_gate_reason reads only .candidate
    if hard_gate_reason(
        scored,
        _CLOCKLESS_NOW if now is None else now,
        odds_min,
        odds_max,
        fresh=now is not None,
    ):
        return None
    e, reason = ev.candidate_ev(c)
    return None if reason else e


def _shadow(rows, version, *, date_field, build, provider_cls, actual_of, grade):
    """(hits, n, units, version, dates, unpriced_n) over the current-version ``rows``.

    ``build(row, day)`` -> candidate rows (the sources' pure functions on this one row);
    ``actual_of(row)`` -> the row's actual or None (not graded); ``grade(c, actual)`` ->
    won | lost | pushed."""
    from app.services import odds_math

    hits = n = unpriced_n = 0
    units = 0.0
    dates = set()
    for r in rows:
        actual = actual_of(r)
        if actual is None:
            continue
        day = _as_date(_field(r, date_field))
        for c in _candidates(provider_cls, build(r, day)):
            result = grade(c, actual)
            if result == "pushed":
                continue
            if c.projection_metadata.get("fair_prob") is None:  # no best quote
                unpriced_n += 1
            elif _passes_gates(c) is not None:
                n += 1
                hits += result == "won"
                units += odds_math.units_for_result(
                    "hit" if result == "won" else "miss", c.market_odds
                )
                dates.add(day)
    return hits, n, units, version, len(dates), unpriced_n


def _game_grade(c, scores):
    from app.services.yetai_grading import game_result

    side = c.projection_metadata["side"]
    return game_result(c.market_type.value, side, c.market_line, *scores)


def _prop_grade(c, actual):
    from app.services.yetai_grading import _compare

    return _compare(actual, c.market_line, c.projection_metadata["side"])


def _between(db, model, start, end):
    return (
        db.query(model)
        .filter(func.date(model.game_date) >= start, func.date(model.game_date) <= end)
        .all()
    )


def _scores(actuals) -> dict:
    """{(date, home, away): (home score, away score)} from game-result rows."""
    out = {}
    for a in actuals:
        h, w = getattr(a, "home_score", None), getattr(a, "away_score", None)
        if h is None:
            h = getattr(a, "home_actual_score", None)
            w = getattr(a, "away_actual_score", None)
        if h is not None and w is not None:
            out[(a.game_date, a.home_team_name, a.away_team_name)] = (h, w)
    return out


def _game_records(db, start, end, league, lines_model, actual_models, specs):
    """{(league, market, None): record} for game-line markets.

    ``specs``: (market, projection model, build(row, {(home, away): game line}, day),
    provider class)."""
    gkey = lambda x: (_as_date(x.game_date), x.home_team_name, x.away_team_name)
    lines = {gkey(g): g for g in _between(db, lines_model, start, end)}
    scores = {}
    for m in actual_models:
        scores.update(_scores(_between(db, m, start, end)))

    out = {}
    for market, model, build, provider_cls in specs:
        version, rows = current_version_rows(
            _between(db, model, start, end), "game_date"
        )

        def build_row(r, day, build=build):
            gl = lines.get(gkey(r))
            return (
                build(r, {(r.home_team_name, r.away_team_name): gl}, day) if gl else []
            )

        out[(league, market, None)] = _shadow(
            rows,
            version,
            date_field="game_date",
            build=build_row,
            provider_cls=provider_cls,
            actual_of=lambda r: scores.get(gkey(r)),
            grade=_game_grade,
        )
    return out


def _nba_games(db, start, end):
    from app.models.predictions_models import (
        NBAGameLines,
        NBASpreadActuals,
        NBASpreadProjections,
        NBATotalsProjections,
    )
    from app.services.auto_pick.providers.moneyline_provider import (
        MoneylineCandidateProvider,
    )
    from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
    from app.services.auto_pick.providers.totals_provider import (
        TotalsCandidateProvider,
    )
    from app.services.auto_pick.sources import _basketball, nba_moneyline_source

    return _game_records(
        db,
        start,
        end,
        "NBA",
        NBAGameLines,
        (NBASpreadActuals,),
        (
            (
                "spread",
                NBASpreadProjections,
                lambda r, gls, _d: _basketball.spread_rows_from([r], gls, "NBA"),
                SpreadCandidateProvider,
            ),
            (
                "moneyline",
                NBASpreadProjections,
                lambda r, gls, _d: nba_moneyline_source.moneyline_rows_from([r], gls),
                MoneylineCandidateProvider,
            ),
            (
                "total",
                NBATotalsProjections,
                lambda r, gls, _d: _basketball.totals_rows_from([r], gls, "NBA"),
                TotalsCandidateProvider,
            ),
        ),
    )


# NHL rows written before the 2026-11-14 input repair (YetAI-5p8) came from stale
# inputs and the old formulas: they say nothing about the repaired model, so the
# record (and the prove-in) starts from the repaired rows only.
NHL_PRE_REPAIR_MODEL_VERSIONS = (None, "", "heuristic-v1")


def _unpriced(rows, version, **fields):
    hits, n = ou_call_graded_counts(rows, **fields)
    return (hits, n, None, version)


def _nhl(db, start, end):
    from app.models.predictions_models import (
        NHLGoalieActuals,
        NHLGoaliePredictions,
        NHLTeamTotalsActuals,
        NHLTeamTotalsPredictions,
    )
    from app.services.auto_pick.providers.player_prop_provider import (
        PlayerPropCandidateProvider,
    )
    from app.services.auto_pick.providers.totals_provider import (
        TotalsCandidateProvider,
    )
    from app.services.auto_pick.sources.nhl_goalie_saves_source import goalie_rows_from
    from app.services.auto_pick.sources.nhl_totals_source import nhl_totals_rows_from
    from app.services.nhl_accuracy_service import (
        _fetch,
        _latest_by_key,
        _nhl_rows,
        _preseason,
    )

    def current(model, key_fn):
        rows = _latest_by_key(_fetch(db, model, start, end), key_fn)
        rows = [
            r
            for r in rows
            if getattr(r, "model_version", None) not in NHL_PRE_REPAIR_MODEL_VERSIONS
        ]
        return current_version_rows(rows, "game_date")

    goalie = {
        (a.goalie_id, a.game_date): a for a in _fetch(db, NHLGoalieActuals, start, end)
    }
    totals = {
        (a.game_date, a.home_team_id, a.away_team_id): a
        for a in _fetch(db, NHLTeamTotalsActuals, start, end)
    }

    def saves_actual(r):
        a = goalie.get((r.goalie_id, r.game_date))
        return None if a is None or _preseason(r, a) else a.actual_saves

    def total_actual(r):
        a = totals.get((r.game_date, r.home_team_id, r.away_team_id))
        return (
            None
            if a is None or _preseason(a)
            else (a.actual_home_goals, a.actual_away_goals)
        )

    saves_v, saves_rows = current(
        NHLGoaliePredictions, lambda p: (p.goalie_id, p.game_date)
    )
    totals_v, totals_rows = current(
        NHLTeamTotalsPredictions,
        lambda p: (p.game_date, p.home_team_id, p.away_team_id),
    )
    shots = {}
    for part, rows in _nhl_rows(db, start=start, end=end).items():
        rows = [
            r
            for r in rows
            if r.get("model_version") not in NHL_PRE_REPAIR_MODEL_VERSIONS
        ]
        shots[part] = current_version_rows(rows, "game_date")
    shots_v, shots_rows = shots["player_shots"]
    return {
        ("NHL", "player_prop", "saves"): _shadow(
            saves_rows,
            saves_v,
            date_field="game_date",
            build=lambda r, day: goalie_rows_from([r], day),
            provider_cls=PlayerPropCandidateProvider,
            actual_of=saves_actual,
            grade=_prop_grade,
        ),
        ("NHL", "player_prop", "shots"): _unpriced(
            shots_rows,
            shots_v,
            line_field="shots_line",
            pick_field="betting_pick",
            actual_field="actual_shots",
        ),
        ("NHL", "total", None): _shadow(
            totals_rows,
            totals_v,
            date_field="game_date",
            build=lambda r, day: nhl_totals_rows_from([r], day),
            provider_cls=TotalsCandidateProvider,
            actual_of=lambda r: (None if (g := total_actual(r)) is None else sum(g)),
            grade=_prop_grade,
        ),
    }


def _nfl(db, start, end):
    from app.models.predictions_models import (
        NFLGameLines,
        NFLSpreadActuals,
        NFLSpreadProjections,
        NFLTotalsActuals,
        NFLTotalsProjections,
        QBActuals,
        QBPredictions,
        RecvYdsActuals,
        RecvYdsPredictions,
    )
    from app.services.auto_pick.providers.moneyline_provider import (
        MoneylineCandidateProvider,
    )
    from app.services.auto_pick.providers.player_prop_provider import (
        PlayerPropCandidateProvider,
    )
    from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
    from app.services.auto_pick.providers.totals_provider import (
        TotalsCandidateProvider,
    )
    from app.services.auto_pick.sources import (
        nfl_moneyline_source,
        nfl_qb_passing_source,
        nfl_receiving_yards_source,
        nfl_spread_source,
        nfl_totals_source,
    )

    out = _game_records(
        db,
        start,
        end,
        "NFL",
        NFLGameLines,
        (NFLTotalsActuals, NFLSpreadActuals),  # the spread table's scores win
        (
            (
                "spread",
                NFLSpreadProjections,
                lambda r, gls, d: nfl_spread_source.spread_rows_from_nfl([r], gls, d),
                SpreadCandidateProvider,
            ),
            (
                "moneyline",
                NFLSpreadProjections,
                lambda r, gls, d: nfl_moneyline_source.moneyline_rows_from_nfl(
                    [r], gls, d
                ),
                MoneylineCandidateProvider,
            ),
            (
                "total",
                NFLTotalsProjections,
                lambda r, gls, d: nfl_totals_source.totals_rows_from_nfl([r], gls, d),
                TotalsCandidateProvider,
            ),
        ),
    )

    lines_by_day = defaultdict(list)
    for g in _between(db, NFLGameLines, start, end):
        lines_by_day[g.game_date].append(g)
    qb = {
        (a.qb_player_id, _as_date(a.game_date)): a
        for a in _between(db, QBActuals, start, end)
    }
    recv = {
        (a.player_id, a.game_date): a for a in _between(db, RecvYdsActuals, start, end)
    }
    qb_v, qb_rows = current_version_rows(
        _between(db, QBPredictions, start, end), "game_date"
    )
    recv_v, recv_rows = current_version_rows(
        _between(db, RecvYdsPredictions, start, end), "game_date"
    )
    out[("NFL", "player_prop", "passing_yards")] = _shadow(
        qb_rows,
        qb_v,
        date_field="game_date",
        build=lambda r, day: nfl_qb_passing_source.qb_rows_from(
            [r], lines_by_day[day], day
        ),
        provider_cls=PlayerPropCandidateProvider,
        actual_of=lambda r: (
            None
            if (a := qb.get((r.qb_player_id, _as_date(r.game_date)))) is None
            else a.actual_passing_yards
        ),
        grade=_prop_grade,
    )
    out[("NFL", "player_prop", "receiving_yards")] = _shadow(
        recv_rows,
        recv_v,
        date_field="game_date",
        build=lambda r, day: nfl_receiving_yards_source.recv_rows_from(
            [r], lines_by_day[day], day
        ),
        provider_cls=PlayerPropCandidateProvider,
        actual_of=lambda r: (
            None
            if (a := recv.get((r.player_id, r.game_date))) is None
            else a.actual_receiving_yards
        ),
        grade=_prop_grade,
    )
    return out


# Keys without a projection record (bet record only): WNBA and MLB, and
# any key a new source adds.
PROJECTION_LOADERS: dict[str, ProjectionLoader] = {
    "nba_props": _nba_props,
    "nba_games": _nba_games,
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
        "NFLMoneylineSource": {("NFL", "moneyline", None)},
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
    token = _BOUNDS.set(odds_bounds(db))
    try:
        for name, loader in PROJECTION_LOADERS.items():
            if loaders is not None and name not in loaders:
                continue
            try:
                # Savepoint: on Postgres a failed statement aborts the whole transaction.
                with db.begin_nested():
                    out.update(loader(db, start, end))
            except Exception:
                log.exception("record_gate: projection loader %s failed", name)
    finally:
        _BOUNDS.reset(token)
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
