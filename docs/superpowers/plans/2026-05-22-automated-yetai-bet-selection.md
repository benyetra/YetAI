# Automated YetAI Bet Selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated selector that picks 1–4 daily YetAI bets across all leagues and markets (ML, spread, totals, player props) based on projections vs market lines plus a unified confidence score, lands them in a `PENDING_APPROVAL` queue, and exposes an admin portal flow to approve/edit/reject them with tier-gated visibility (FREE/PRO/ELITE).

**Architecture:** Five-module pipeline. `CandidateProvider` adapters wrap existing prediction services and emit normalized `BetCandidate` structs. A pure `ConfidenceScorer` composes six sub-scores into 0–100 + breakdown + reasoning. `BetSelector` ranks, applies correlation/odds guards, and assigns tier by rank. `AutoPickOrchestrator` is a Celery task that coordinates the run and persists to `yetai_bets`. Admin portal adds a Pending Picks view backed by new FastAPI endpoints. A backtest CLI replays historical data for tuning.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, Celery + Redis, pytest, Next.js 14 (App Router), TypeScript, Tailwind.

**Spec reference:** `docs/superpowers/specs/2026-05-22-automated-yetai-bet-selection-design.md`

---

## Task 1: Schema Migrations

**Files:**
- Create: `backend/alembic/versions/<rev>_auto_yetai_picks.py`
- Modify: `backend/app/models/database_models.py` (extend `YetAIBet`, add new enums/tables)

- [ ] **Step 1: Generate migration skeleton**

Run from `backend/`:
```bash
alembic revision -m "auto_yetai_picks: pending status, scoring fields, runs+config tables"
```

- [ ] **Step 2: Add new status values to `YetAIBet.status` enum**

In `backend/app/models/database_models.py`, find `class BetStatus` (or wherever `YetAIBet.status` enum lives) and add:

```python
PENDING_APPROVAL = "pending_approval"
REJECTED = "rejected"
EXPIRED = "expired"
```

- [ ] **Step 3: Add new columns to `YetAIBet` model**

In the `YetAIBet` SQLAlchemy class:

```python
from sqlalchemy import Column, Float, Text, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
import enum

class BetSource(str, enum.Enum):
    MANUAL = "manual"
    AUTO = "auto"

# inside YetAIBet:
confidence_score = Column(Float, nullable=True)
score_breakdown = Column(JSONB, nullable=True)
reasoning = Column(Text, nullable=True)
source = Column(Enum(BetSource), default=BetSource.MANUAL, nullable=False)
auto_pick_run_id = Column(ForeignKey("auto_pick_runs.id"), nullable=True, index=True)
```

- [ ] **Step 4: Add `AutoPickRun` model**

In the same file:

```python
class AutoPickRunStatus(str, enum.Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    NO_PICKS = "no_picks"

class AutoPickRun(Base):
    __tablename__ = "auto_pick_runs"
    id = Column(Integer, primary_key=True)
    run_at = Column(DateTime, nullable=False, index=True)
    status = Column(Enum(AutoPickRunStatus), nullable=False)
    candidates_considered = Column(Integer, default=0, nullable=False)
    candidates_selected = Column(Integer, default=0, nullable=False)
    dropped_reasons = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    picks = relationship("YetAIBet", backref="auto_pick_run")
```

- [ ] **Step 5: Add `ScoringConfig` model (single-row config)**

```python
class ScoringConfig(Base):
    __tablename__ = "scoring_config"
    id = Column(Integer, primary_key=True)
    weight_edge = Column(Float, nullable=False, default=0.40)
    weight_historical = Column(Float, nullable=False, default=0.20)
    weight_freshness = Column(Float, nullable=False, default=0.15)
    weight_line_movement = Column(Float, nullable=False, default=0.10)
    weight_odds_sanity = Column(Float, nullable=False, default=0.10)
    weight_model_conf = Column(Float, nullable=False, default=0.05)
    score_threshold = Column(Float, nullable=False, default=65.0)
    odds_min = Column(Integer, nullable=False, default=-300)
    odds_max = Column(Integer, nullable=False, default=400)
    max_picks_per_day = Column(Integer, nullable=False, default=4)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

- [ ] **Step 6: Fill in the migration upgrade/downgrade**

In the generated `<rev>_auto_yetai_picks.py`, write `upgrade()` that creates the two new tables, alters the `bet_status` enum (Postgres: `ALTER TYPE ... ADD VALUE`), adds the new columns to `yetai_bets`, and seeds one `scoring_config` row with defaults. `downgrade()` drops the new tables and columns (enum value removal is best-effort: skip with a comment that downgrade does not remove enum values).

Use existing migrations in `backend/alembic/versions/` as a style reference.

- [ ] **Step 7: Apply locally and verify**

```bash
alembic upgrade head
psql $DATABASE_URL -c "\d yetai_bets" | grep -E "confidence_score|reasoning|source|auto_pick_run_id"
psql $DATABASE_URL -c "\d auto_pick_runs"
psql $DATABASE_URL -c "SELECT * FROM scoring_config;"
```

Expected: new columns present, two new tables exist, one config row with default weights.

- [ ] **Step 8: Commit**

```bash
git add backend/alembic/versions/ backend/app/models/database_models.py
git commit -m "feat(yetai-picks): add schema for auto-pick runs, scoring config, and pending bet status"
```

---

## Task 2: `BetCandidate` and `CandidateProvider` Protocol

**Files:**
- Create: `backend/app/services/auto_pick/__init__.py`
- Create: `backend/app/services/auto_pick/candidate.py`
- Create: `backend/tests/auto_pick/__init__.py`
- Create: `backend/tests/auto_pick/test_candidate.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/auto_pick/test_candidate.py`:

```python
from datetime import datetime
from app.services.auto_pick.candidate import (
    BetCandidate, MarketType, CandidateProvider,
)

def test_bet_candidate_required_fields():
    c = BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="MLB",
        event_id="mlb-2026-05-22-bos-nyy",
        selection="Spencer Strider OVER 5.5 Ks",
        market_line=5.5,
        market_odds=-115,
        our_projection=9.0,
        projection_metadata={"sample_size": 7, "model_id": "mlb_k_v2", "generated_at": datetime.utcnow().isoformat()},
    )
    assert c.market_type == MarketType.PLAYER_PROP
    assert c.our_projection == 9.0

def test_candidate_provider_is_protocol():
    # Concrete classes should implement get_candidates; protocol itself isn't instantiated.
    class FakeProvider:
        async def get_candidates(self, date_range):
            return []
    assert hasattr(FakeProvider(), "get_candidates")
```

- [ ] **Step 2: Run test, confirm fail**

```bash
cd backend && pytest tests/auto_pick/test_candidate.py -v
```

Expected: ImportError / ModuleNotFoundError.

- [ ] **Step 3: Implement `candidate.py`**

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class MarketType(str, Enum):
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"
    PLAYER_PROP = "player_prop"


@dataclass
class BetCandidate:
    market_type: MarketType
    league: str
    event_id: str
    selection: str
    market_line: float
    market_odds: int
    our_projection: float
    projection_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DateRange:
    start: datetime
    end: datetime


@runtime_checkable
class CandidateProvider(Protocol):
    async def get_candidates(self, date_range: DateRange) -> list[BetCandidate]:
        ...
```

- [ ] **Step 4: Run test, confirm pass**

```bash
pytest tests/auto_pick/test_candidate.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/auto_pick/ backend/tests/auto_pick/
git commit -m "feat(yetai-picks): add BetCandidate dataclass and CandidateProvider protocol"
```

---

## Task 3: `ScoringContext` and `ConfidenceScore`

**Files:**
- Create: `backend/app/services/auto_pick/scoring_context.py`
- Create: `backend/app/services/auto_pick/confidence_score.py`
- Create: `backend/tests/auto_pick/test_scoring_context.py`

- [ ] **Step 1: Write the failing test**

```python
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
from app.services.auto_pick.confidence_score import ConfidenceScore

def test_scoring_weights_defaults_sum_to_one():
    w = ScoringWeights()
    total = (w.edge + w.historical + w.freshness +
             w.line_movement + w.odds_sanity + w.model_conf)
    assert abs(total - 1.0) < 1e-6

def test_scoring_context_holds_lookup_tables():
    ctx = ScoringContext(
        weights=ScoringWeights(),
        score_threshold=65.0,
        historical_hit_rates={("player_prop", "MLB"): 0.61},
        line_movement={"event-1": {"opened": -110, "current": -125}},
        now=None,
    )
    assert ctx.historical_hit_rates[("player_prop", "MLB")] == 0.61

def test_confidence_score_dataclass():
    s = ConfidenceScore(total=72.5, breakdown={"edge": 38.0}, reasoning="strong edge")
    assert s.total == 72.5
    assert s.breakdown["edge"] == 38.0
```

- [ ] **Step 2: Run test, expect fail**

```bash
pytest tests/auto_pick/test_scoring_context.py -v
```

- [ ] **Step 3: Implement `scoring_context.py`**

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ScoringWeights:
    edge: float = 0.40
    historical: float = 0.20
    freshness: float = 0.15
    line_movement: float = 0.10
    odds_sanity: float = 0.10
    model_conf: float = 0.05


@dataclass
class ScoringContext:
    weights: ScoringWeights
    score_threshold: float
    historical_hit_rates: dict[tuple[str, str], float] = field(default_factory=dict)
    line_movement: dict[str, dict] = field(default_factory=dict)
    now: Optional[datetime] = None
```

- [ ] **Step 4: Implement `confidence_score.py`**

```python
from dataclasses import dataclass, field


@dataclass
class ConfidenceScore:
    total: float
    breakdown: dict[str, float] = field(default_factory=dict)
    reasoning: str = ""
```

- [ ] **Step 5: Run test, pass; commit**

```bash
pytest tests/auto_pick/test_scoring_context.py -v
git add backend/app/services/auto_pick/ backend/tests/auto_pick/
git commit -m "feat(yetai-picks): add ScoringContext, ScoringWeights, ConfidenceScore"
```

---

## Task 4: Edge Sub-Score

**Files:**
- Create: `backend/app/services/auto_pick/sub_scores.py`
- Create: `backend/tests/auto_pick/test_sub_scores_edge.py`

- [ ] **Step 1: Write failing tests for edge sub-score**

```python
import pytest
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.sub_scores import edge_sub_score


def _cand(market_type, line, projection, odds=-110):
    return BetCandidate(
        market_type=market_type, league="MLB", event_id="e",
        selection="s", market_line=line, market_odds=odds,
        our_projection=projection, projection_metadata={},
    )

def test_edge_zero_when_projection_equals_line():
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 5.5))
    assert s == 0.0

def test_edge_negative_when_projection_worse_than_line():
    # Over bet but projection is below line
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 4.0))
    assert s < 0

def test_edge_strider_example_high():
    # 9.0 K projection vs 5.5 line -> strong over
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 9.0))
    assert 70 <= s <= 100

def test_edge_caps_at_100():
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 1.0, 100.0))
    assert s == 100.0

def test_edge_normalized_per_market_type():
    # A 3-point edge on a spread vs a 3-strikeout edge on a prop should NOT
    # produce the same raw score — they're on different scales.
    prop = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 8.5))
    spread = edge_sub_score(_cand(MarketType.SPREAD, -3.5, -6.5))
    assert prop != spread
```

- [ ] **Step 2: Run, expect fail**

```bash
pytest tests/auto_pick/test_sub_scores_edge.py -v
```

- [ ] **Step 3: Implement `edge_sub_score`**

`backend/app/services/auto_pick/sub_scores.py`:

```python
from app.services.auto_pick.candidate import BetCandidate, MarketType

# Per-market normalization: what raw delta corresponds to a "max" edge (100)?
# These are starting points; tune via backtest.
EDGE_NORMALIZERS = {
    MarketType.MONEYLINE: 0.20,    # 20% implied-prob delta -> max
    MarketType.SPREAD: 7.0,        # 7 point delta -> max
    MarketType.TOTAL: 7.0,         # 7 point delta -> max
    MarketType.PLAYER_PROP: 4.0,   # market-line-units delta -> max
}


def edge_sub_score(candidate: BetCandidate) -> float:
    delta = candidate.our_projection - candidate.market_line
    norm = EDGE_NORMALIZERS[candidate.market_type]
    raw = (delta / norm) * 100.0
    if raw > 100.0:
        return 100.0
    if raw < -100.0:
        return -100.0
    return raw
```

- [ ] **Step 4: Pass tests; commit**

```bash
pytest tests/auto_pick/test_sub_scores_edge.py -v
git add backend/app/services/auto_pick/sub_scores.py backend/tests/auto_pick/test_sub_scores_edge.py
git commit -m "feat(yetai-picks): edge sub-score with per-market normalization"
```

---

## Task 5: Historical Accuracy Sub-Score

**Files:**
- Modify: `backend/app/services/auto_pick/sub_scores.py`
- Create: `backend/tests/auto_pick/test_sub_scores_historical.py`

- [ ] **Step 1: Write failing tests**

```python
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
from app.services.auto_pick.sub_scores import historical_sub_score


def _ctx(rates):
    return ScoringContext(weights=ScoringWeights(), score_threshold=65.0, historical_hit_rates=rates)

def _cand(mt, league):
    return BetCandidate(market_type=mt, league=league, event_id="e", selection="s",
                        market_line=0, market_odds=-110, our_projection=0, projection_metadata={})

def test_historical_baseline_when_missing():
    # No data for this market+league: return neutral 50
    s = historical_sub_score(_cand(MarketType.PLAYER_PROP, "MLB"), _ctx({}))
    assert s == 50.0

def test_historical_breakeven_maps_to_50():
    # 52.4% is breakeven at -110; mapping below
    s = historical_sub_score(_cand(MarketType.PLAYER_PROP, "MLB"),
                              _ctx({("player_prop", "MLB"): 0.524}))
    assert abs(s - 50.0) < 5.0

def test_historical_strong_hit_rate_high_score():
    s = historical_sub_score(_cand(MarketType.PLAYER_PROP, "MLB"),
                              _ctx({("player_prop", "MLB"): 0.65}))
    assert s >= 75

def test_historical_poor_hit_rate_low_score():
    s = historical_sub_score(_cand(MarketType.PLAYER_PROP, "MLB"),
                              _ctx({("player_prop", "MLB"): 0.40}))
    assert s <= 25
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Add `historical_sub_score` to `sub_scores.py`**

```python
def historical_sub_score(candidate: BetCandidate, context: ScoringContext) -> float:
    rate = context.historical_hit_rates.get((candidate.market_type.value, candidate.league))
    if rate is None:
        return 50.0
    # Map 0.40 -> 0, 0.524 -> 50, 0.65 -> 100, clamp.
    if rate <= 0.40:
        return 0.0
    if rate >= 0.65:
        return 100.0
    # piecewise linear: 0.40-0.524 maps to 0-50, 0.524-0.65 maps to 50-100
    if rate < 0.524:
        return (rate - 0.40) / (0.524 - 0.40) * 50.0
    return 50.0 + (rate - 0.524) / (0.65 - 0.524) * 50.0
```

Add the import at top:
```python
from app.services.auto_pick.scoring_context import ScoringContext
```

- [ ] **Step 4: Pass; commit**

```bash
pytest tests/auto_pick/test_sub_scores_historical.py -v
git add backend/app/services/auto_pick/sub_scores.py backend/tests/auto_pick/test_sub_scores_historical.py
git commit -m "feat(yetai-picks): historical accuracy sub-score"
```

---

## Task 6: Freshness Sub-Score

**Files:**
- Modify: `backend/app/services/auto_pick/sub_scores.py`
- Create: `backend/tests/auto_pick/test_sub_scores_freshness.py`

- [ ] **Step 1: Write failing tests**

```python
from datetime import datetime, timedelta
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
from app.services.auto_pick.sub_scores import freshness_sub_score


NOW = datetime(2026, 5, 22, 9, 0, 0)


def _ctx():
    return ScoringContext(weights=ScoringWeights(), score_threshold=65.0, now=NOW)

def _cand(metadata):
    return BetCandidate(market_type=MarketType.PLAYER_PROP, league="MLB",
                        event_id="e", selection="s", market_line=0, market_odds=-110,
                        our_projection=0, projection_metadata=metadata)

def test_freshness_full_when_recent_large_sample_no_flags():
    md = {"sample_size": 30, "generated_at": (NOW - timedelta(hours=1)).isoformat(), "injury_flag": False}
    assert freshness_sub_score(_cand(md), _ctx()) >= 90

def test_freshness_penalty_for_small_sample():
    md = {"sample_size": 3, "generated_at": NOW.isoformat()}
    assert freshness_sub_score(_cand(md), _ctx()) < 60

def test_freshness_penalty_for_stale_projection():
    md = {"sample_size": 30, "generated_at": (NOW - timedelta(hours=48)).isoformat()}
    assert freshness_sub_score(_cand(md), _ctx()) < 50

def test_freshness_hard_penalty_on_injury_flag():
    md = {"sample_size": 30, "generated_at": NOW.isoformat(), "injury_flag": True}
    assert freshness_sub_score(_cand(md), _ctx()) < 30
```

- [ ] **Step 2: Implement**

```python
from datetime import datetime, timedelta

def freshness_sub_score(candidate: BetCandidate, context: ScoringContext) -> float:
    score = 100.0
    md = candidate.projection_metadata
    sample = md.get("sample_size", 10)
    if sample < 5:
        score -= 40
    elif sample < 10:
        score -= 20

    gen_at = md.get("generated_at")
    if gen_at and context.now:
        try:
            gen_dt = datetime.fromisoformat(gen_at)
            age_h = (context.now - gen_dt).total_seconds() / 3600.0
            if age_h > 24:
                score -= 40
            elif age_h > 12:
                score -= 15
        except ValueError:
            pass

    if md.get("injury_flag"):
        score -= 60

    return max(0.0, min(100.0, score))
```

- [ ] **Step 3: Pass; commit**

```bash
pytest tests/auto_pick/test_sub_scores_freshness.py -v
git add backend/app/services/auto_pick/sub_scores.py backend/tests/auto_pick/test_sub_scores_freshness.py
git commit -m "feat(yetai-picks): freshness sub-score (sample/age/injury)"
```

---

## Task 7: Line Movement + Odds Sanity + Model Confidence Sub-Scores

**Files:**
- Modify: `backend/app/services/auto_pick/sub_scores.py`
- Create: `backend/tests/auto_pick/test_sub_scores_remaining.py`

- [ ] **Step 1: Failing tests**

```python
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
from app.services.auto_pick.sub_scores import (
    line_movement_sub_score, odds_sanity_sub_score, model_confidence_sub_score,
)


def _cand(odds=-110, event_id="e", md=None):
    return BetCandidate(market_type=MarketType.PLAYER_PROP, league="MLB",
                        event_id=event_id, selection="OVER", market_line=5.5,
                        market_odds=odds, our_projection=9.0, projection_metadata=md or {})

# Line movement
def test_line_movement_neutral_when_no_data():
    ctx = ScoringContext(weights=ScoringWeights(), score_threshold=65.0)
    assert line_movement_sub_score(_cand(), ctx) == 50.0

def test_line_movement_bonus_when_market_moves_toward_us():
    # We're on OVER 5.5; line moved up to 6.0 -> market agrees with us
    ctx = ScoringContext(weights=ScoringWeights(), score_threshold=65.0,
                         line_movement={"e": {"opened_line": 5.5, "current_line": 6.0, "side": "over"}})
    assert line_movement_sub_score(_cand(event_id="e"), ctx) > 50

def test_line_movement_penalty_when_market_moves_against_us():
    ctx = ScoringContext(weights=ScoringWeights(), score_threshold=65.0,
                         line_movement={"e": {"opened_line": 5.5, "current_line": 5.0, "side": "over"}})
    assert line_movement_sub_score(_cand(event_id="e"), ctx) < 50

# Odds sanity
def test_odds_sanity_peaks_in_typical_range():
    ctx = ScoringContext(weights=ScoringWeights(), score_threshold=65.0)
    assert odds_sanity_sub_score(_cand(odds=-110), ctx) >= 90
    assert odds_sanity_sub_score(_cand(odds=+105), ctx) >= 90

def test_odds_sanity_penalty_for_heavy_favorite():
    ctx = ScoringContext(weights=ScoringWeights(), score_threshold=65.0)
    assert odds_sanity_sub_score(_cand(odds=-280), ctx) < 50

def test_odds_sanity_penalty_for_longshot():
    ctx = ScoringContext(weights=ScoringWeights(), score_threshold=65.0)
    assert odds_sanity_sub_score(_cand(odds=+380), ctx) < 50

# Model confidence
def test_model_conf_neutral_when_missing():
    assert model_confidence_sub_score(_cand(md={})) == 50.0

def test_model_conf_uses_provided_value():
    assert model_confidence_sub_score(_cand(md={"model_confidence": 0.85})) == 85.0
```

- [ ] **Step 2: Implement**

Append to `sub_scores.py`:

```python
def line_movement_sub_score(candidate: BetCandidate, context: ScoringContext) -> float:
    mv = context.line_movement.get(candidate.event_id)
    if not mv:
        return 50.0
    opened = mv.get("opened_line")
    current = mv.get("current_line")
    side = mv.get("side", "").lower()
    if opened is None or current is None:
        return 50.0
    delta = current - opened
    # For OVER: positive delta (line went up) is movement toward our side.
    # For UNDER: negative delta is toward us. Same for spread/ml (encoded by side).
    if side in ("over", "home", "favorite"):
        signed = delta
    else:
        signed = -delta
    # Map +/- 1.0 line units to a +/- 30 score swing.
    bonus = max(-30.0, min(30.0, signed * 30.0))
    return 50.0 + bonus


def odds_sanity_sub_score(candidate: BetCandidate, context: ScoringContext) -> float:
    o = candidate.market_odds
    # Bell-curve-ish: peak in [-150, +150], soft falloff to [-300, +400].
    if -150 <= o <= 150:
        return 100.0
    if o < -150:
        # -150 -> 100, -300 -> 0
        return max(0.0, 100.0 - (abs(o) - 150) * (100.0 / 150.0))
    # o > 150
    # +150 -> 100, +400 -> 0
    return max(0.0, 100.0 - (o - 150) * (100.0 / 250.0))


def model_confidence_sub_score(candidate: BetCandidate) -> float:
    mc = candidate.projection_metadata.get("model_confidence")
    if mc is None:
        return 50.0
    return max(0.0, min(100.0, float(mc) * 100.0))
```

- [ ] **Step 3: Pass; commit**

```bash
pytest tests/auto_pick/test_sub_scores_remaining.py -v
git add backend/app/services/auto_pick/sub_scores.py backend/tests/auto_pick/test_sub_scores_remaining.py
git commit -m "feat(yetai-picks): line movement, odds sanity, model confidence sub-scores"
```

---

## Task 8: `ConfidenceScorer` Composition + Reasoning

**Files:**
- Create: `backend/app/services/auto_pick/scorer.py`
- Create: `backend/tests/auto_pick/test_scorer.py`

- [ ] **Step 1: Failing tests**

```python
from datetime import datetime
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
from app.services.auto_pick.scorer import ConfidenceScorer


def _strider():
    return BetCandidate(
        market_type=MarketType.PLAYER_PROP, league="MLB",
        event_id="mlb-bos-nyy", selection="Strider OVER 5.5 K",
        market_line=5.5, market_odds=-115, our_projection=9.0,
        projection_metadata={"sample_size": 7, "generated_at": "2026-05-22T08:00:00",
                             "model_confidence": 0.78},
    )

def _ctx():
    return ScoringContext(
        weights=ScoringWeights(), score_threshold=65.0,
        historical_hit_rates={("player_prop", "MLB"): 0.61},
        line_movement={}, now=datetime(2026, 5, 22, 9, 0, 0),
    )

def test_scorer_returns_total_breakdown_reasoning():
    s = ConfidenceScorer().score(_strider(), _ctx())
    assert 0 <= s.total <= 100
    assert set(s.breakdown.keys()) == {
        "edge", "historical", "freshness", "line_movement", "odds_sanity", "model_conf"
    }
    assert "Strider" in s.reasoning or "5.5" in s.reasoning

def test_scorer_strider_above_threshold():
    s = ConfidenceScorer().score(_strider(), _ctx())
    assert s.total >= 65

def test_scorer_weights_applied_correctly():
    s = ConfidenceScorer().score(_strider(), _ctx())
    w = ScoringWeights()
    expected = (
        s.breakdown["edge"] * w.edge
        + s.breakdown["historical"] * w.historical
        + s.breakdown["freshness"] * w.freshness
        + s.breakdown["line_movement"] * w.line_movement
        + s.breakdown["odds_sanity"] * w.odds_sanity
        + s.breakdown["model_conf"] * w.model_conf
    )
    assert abs(s.total - expected) < 1e-6
```

- [ ] **Step 2: Implement `scorer.py`**

```python
from app.services.auto_pick.candidate import BetCandidate
from app.services.auto_pick.confidence_score import ConfidenceScore
from app.services.auto_pick.scoring_context import ScoringContext
from app.services.auto_pick.sub_scores import (
    edge_sub_score, historical_sub_score, freshness_sub_score,
    line_movement_sub_score, odds_sanity_sub_score, model_confidence_sub_score,
)


class ConfidenceScorer:
    def score(self, candidate: BetCandidate, context: ScoringContext) -> ConfidenceScore:
        breakdown = {
            "edge": edge_sub_score(candidate),
            "historical": historical_sub_score(candidate, context),
            "freshness": freshness_sub_score(candidate, context),
            "line_movement": line_movement_sub_score(candidate, context),
            "odds_sanity": odds_sanity_sub_score(candidate, context),
            "model_conf": model_confidence_sub_score(candidate),
        }
        w = context.weights
        total = (
            breakdown["edge"] * w.edge
            + breakdown["historical"] * w.historical
            + breakdown["freshness"] * w.freshness
            + breakdown["line_movement"] * w.line_movement
            + breakdown["odds_sanity"] * w.odds_sanity
            + breakdown["model_conf"] * w.model_conf
        )
        reasoning = self._build_reasoning(candidate, breakdown, context)
        return ConfidenceScore(total=round(total, 2), breakdown=breakdown, reasoning=reasoning)

    def _build_reasoning(self, c: BetCandidate, b: dict, ctx: ScoringContext) -> str:
        delta = c.our_projection - c.market_line
        sign = "+" if delta >= 0 else ""
        parts = [
            f"{c.selection}: projection {c.our_projection} vs line {c.market_line} ({sign}{delta:.2f}).",
            f"Edge {b['edge']:.0f}, historical {b['historical']:.0f}, freshness {b['freshness']:.0f}.",
        ]
        hist = ctx.historical_hit_rates.get((c.market_type.value, c.league))
        if hist is not None:
            parts.append(f"{c.market_type.value} {c.league} L90d hit rate {hist*100:.0f}%.")
        if b["line_movement"] != 50.0:
            parts.append(f"Line movement: {'with us' if b['line_movement'] > 50 else 'against us'}.")
        return " ".join(parts)
```

- [ ] **Step 3: Pass; commit**

```bash
pytest tests/auto_pick/test_scorer.py -v
git add backend/app/services/auto_pick/scorer.py backend/tests/auto_pick/test_scorer.py
git commit -m "feat(yetai-picks): ConfidenceScorer composition with reasoning"
```

---

## Task 9: `BetSelector` (Filter, Rank, Correlation Guard, Tier Assignment)

**Files:**
- Create: `backend/app/services/auto_pick/selector.py`
- Create: `backend/tests/auto_pick/test_selector.py`

- [ ] **Step 1: Failing tests**

```python
from app.models.database_models import SubscriptionTier
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.confidence_score import ConfidenceScore
from app.services.auto_pick.selector import BetSelector, SelectorConfig, ScoredCandidate


def _sc(event_id, total, market_type=MarketType.PLAYER_PROP, odds=-110, league="MLB", selection="s"):
    c = BetCandidate(market_type=market_type, league=league, event_id=event_id,
                     selection=selection, market_line=0, market_odds=odds,
                     our_projection=0, projection_metadata={})
    return ScoredCandidate(candidate=c, score=ConfidenceScore(total=total, breakdown={}, reasoning=""))


def test_drops_below_threshold():
    sel = BetSelector(SelectorConfig(threshold=65.0))
    picks = sel.select([_sc("e1", 50), _sc("e2", 64.9)])
    assert picks == []

def test_picks_top_n_by_score():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=4))
    picks = sel.select([
        _sc("e1", 70), _sc("e2", 90), _sc("e3", 80), _sc("e4", 66), _sc("e5", 95),
    ])
    assert [p.candidate.event_id for p in picks] == ["e5", "e2", "e3", "e1"]

def test_correlation_guard_skips_same_event():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=4))
    picks = sel.select([_sc("e1", 90), _sc("e1", 88), _sc("e2", 70)])
    assert [p.candidate.event_id for p in picks] == ["e1", "e2"]

def test_hard_odds_cutoff_drops_extremes():
    sel = BetSelector(SelectorConfig(threshold=65.0, odds_min=-300, odds_max=400))
    picks = sel.select([_sc("e1", 90, odds=-350), _sc("e2", 85, odds=450), _sc("e3", 80, odds=-150)])
    assert [p.candidate.event_id for p in picks] == ["e3"]

def test_tier_assignment_by_rank():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=4))
    picks = sel.select([_sc("e1", 95), _sc("e2", 90), _sc("e3", 85), _sc("e4", 70)])
    assert picks[0].tier == SubscriptionTier.FREE
    assert picks[1].tier == SubscriptionTier.PRO
    assert picks[2].tier == SubscriptionTier.PRO
    assert picks[3].tier == SubscriptionTier.ELITE

def test_fewer_than_max_when_few_eligible():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=4))
    picks = sel.select([_sc("e1", 80)])
    assert len(picks) == 1
    assert picks[0].tier == SubscriptionTier.FREE
```

- [ ] **Step 2: Implement `selector.py`**

```python
from dataclasses import dataclass, field
from typing import Optional
from app.models.database_models import SubscriptionTier
from app.services.auto_pick.candidate import BetCandidate
from app.services.auto_pick.confidence_score import ConfidenceScore


@dataclass
class ScoredCandidate:
    candidate: BetCandidate
    score: ConfidenceScore
    tier: Optional[SubscriptionTier] = None
    drop_reason: Optional[str] = None


@dataclass
class SelectorConfig:
    threshold: float = 65.0
    odds_min: int = -300
    odds_max: int = 400
    max_picks: int = 4


# Rank -> tier mapping. Rank is 0-indexed.
_TIER_BY_RANK = [
    SubscriptionTier.FREE,
    SubscriptionTier.PRO,
    SubscriptionTier.PRO,
    SubscriptionTier.ELITE,
]


class BetSelector:
    def __init__(self, config: SelectorConfig):
        self.config = config

    def select(self, scored: list[ScoredCandidate]) -> list[ScoredCandidate]:
        eligible = []
        for sc in scored:
            if sc.score.total < self.config.threshold:
                sc.drop_reason = f"below_threshold:{sc.score.total:.1f}"
                continue
            o = sc.candidate.market_odds
            if o < self.config.odds_min or o > self.config.odds_max:
                sc.drop_reason = f"odds_out_of_bounds:{o}"
                continue
            eligible.append(sc)

        eligible.sort(key=lambda s: s.score.total, reverse=True)

        picks: list[ScoredCandidate] = []
        used_events: set[str] = set()
        for sc in eligible:
            if sc.candidate.event_id in used_events:
                sc.drop_reason = "correlation_same_event"
                continue
            picks.append(sc)
            used_events.add(sc.candidate.event_id)
            if len(picks) >= self.config.max_picks:
                break

        for i, p in enumerate(picks):
            p.tier = _TIER_BY_RANK[min(i, len(_TIER_BY_RANK) - 1)]
        return picks
```

- [ ] **Step 3: Pass; commit**

```bash
pytest tests/auto_pick/test_selector.py -v
git add backend/app/services/auto_pick/selector.py backend/tests/auto_pick/test_selector.py
git commit -m "feat(yetai-picks): BetSelector with correlation guard and tier-by-rank"
```

---

## Task 10: `CandidateProvider` Implementations (ML, Spread, Totals, Props)

These are thin adapters. Each wraps one existing prediction service, queries today's slate, and emits `BetCandidate` objects. If a service has no projections for a league or market, the provider returns `[]`.

**Files:**
- Create: `backend/app/services/auto_pick/providers/__init__.py`
- Create: `backend/app/services/auto_pick/providers/player_prop_provider.py`
- Create: `backend/app/services/auto_pick/providers/spread_provider.py`
- Create: `backend/app/services/auto_pick/providers/totals_provider.py`
- Create: `backend/app/services/auto_pick/providers/moneyline_provider.py`
- Create: `backend/tests/auto_pick/test_providers.py`

> **Sub-task: Audit existing prediction services first.** Before writing the providers, read `backend/app/services/player_props_service.py`, `backend/app/services/data_pipeline.py`, and any `*_projector` or `*_predict*` services. Find each one's "give me today's projections" entry point. If the entry point doesn't exist in a clean form, add a small read-only accessor on that service (do not refactor its internals). Record the entry point per market in a short comment block at the top of each provider file.

- [ ] **Step 1: Failing test for `PlayerPropCandidateProvider`**

`backend/tests/auto_pick/test_providers.py`:

```python
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from app.services.auto_pick.candidate import DateRange, MarketType
from app.services.auto_pick.providers.player_prop_provider import PlayerPropCandidateProvider


@pytest.mark.asyncio
async def test_player_prop_provider_returns_candidates():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(return_value=[
        {
            "league": "MLB", "event_id": "mlb-e1",
            "player": "Strider", "stat": "Ks",
            "line": 5.5, "side": "over",
            "odds": -115, "projection": 9.0,
            "sample_size": 7, "generated_at": "2026-05-22T08:00:00",
            "model_confidence": 0.78,
        },
    ])
    p = PlayerPropCandidateProvider(source=fake_source)
    result = await p.get_candidates(DateRange(datetime.utcnow(), datetime.utcnow() + timedelta(days=1)))
    assert len(result) == 1
    assert result[0].market_type == MarketType.PLAYER_PROP
    assert result[0].our_projection == 9.0
    assert result[0].market_line == 5.5
    assert "Strider" in result[0].selection

@pytest.mark.asyncio
async def test_player_prop_provider_returns_empty_when_no_projections():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(return_value=[])
    p = PlayerPropCandidateProvider(source=fake_source)
    result = await p.get_candidates(DateRange(datetime.utcnow(), datetime.utcnow() + timedelta(days=1)))
    assert result == []

@pytest.mark.asyncio
async def test_player_prop_provider_swallows_source_errors():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(side_effect=RuntimeError("upstream down"))
    p = PlayerPropCandidateProvider(source=fake_source)
    result = await p.get_candidates(DateRange(datetime.utcnow(), datetime.utcnow() + timedelta(days=1)))
    assert result == []
```

- [ ] **Step 2: Implement `PlayerPropCandidateProvider`**

```python
# backend/app/services/auto_pick/providers/player_prop_provider.py
"""
Adapter from existing player_props_service to BetCandidate.
Source entry point: source.get_todays_projections(date_range) -> list[dict].
If the source raises or returns nothing, returns [].
"""
import logging
from app.services.auto_pick.candidate import BetCandidate, DateRange, MarketType

log = logging.getLogger(__name__)


class PlayerPropCandidateProvider:
    def __init__(self, source):
        self.source = source

    async def get_candidates(self, date_range: DateRange) -> list[BetCandidate]:
        try:
            rows = await self.source.get_todays_projections(date_range)
        except Exception as e:
            log.exception("PlayerPropCandidateProvider source failed: %s", e)
            return []
        out: list[BetCandidate] = []
        for r in rows:
            selection = f"{r['player']} {r['side'].upper()} {r['line']} {r['stat']}"
            out.append(BetCandidate(
                market_type=MarketType.PLAYER_PROP,
                league=r["league"],
                event_id=r["event_id"],
                selection=selection,
                market_line=float(r["line"]),
                market_odds=int(r["odds"]),
                our_projection=float(r["projection"]),
                projection_metadata={
                    "sample_size": r.get("sample_size"),
                    "generated_at": r.get("generated_at"),
                    "model_confidence": r.get("model_confidence"),
                    "injury_flag": r.get("injury_flag", False),
                    "stat": r["stat"],
                    "side": r["side"],
                },
            ))
        return out
```

- [ ] **Step 3: Repeat the pattern for the other three providers**

Create `spread_provider.py`, `totals_provider.py`, `moneyline_provider.py` using the same shape. Each has its own row schema (spread point line, totals over/under, moneyline implied prob). The signature, error swallowing, and empty-list-on-missing behavior are identical.

Add one test per provider mirroring the three above (returns candidates, returns empty, swallows errors). If a market currently has no prediction service for a league, the provider still exists — it just returns `[]` (matches the "partial coverage" requirement from the spec).

- [ ] **Step 4: Pass; commit**

```bash
pytest tests/auto_pick/test_providers.py -v
git add backend/app/services/auto_pick/providers/ backend/tests/auto_pick/test_providers.py
git commit -m "feat(yetai-picks): candidate providers for ML, spread, totals, props"
```

---

## Task 11: Scoring Config Loader

**Files:**
- Create: `backend/app/services/auto_pick/config_loader.py`
- Create: `backend/tests/auto_pick/test_config_loader.py`

- [ ] **Step 1: Failing test**

```python
from app.services.auto_pick.config_loader import load_scoring_config
from app.services.auto_pick.scoring_context import ScoringWeights


def test_load_scoring_config_returns_weights_and_threshold(db_session_with_default_config):
    cfg = load_scoring_config(db_session_with_default_config)
    assert isinstance(cfg.weights, ScoringWeights)
    assert cfg.score_threshold == 65.0
    assert cfg.max_picks == 4
    assert cfg.odds_min == -300
    assert cfg.odds_max == 400
```

> `db_session_with_default_config` is a fixture that creates an in-memory or test DB with the seeded `scoring_config` row from the migration. Add it to `backend/tests/auto_pick/conftest.py` if not present.

- [ ] **Step 2: Implement**

```python
# backend/app/services/auto_pick/config_loader.py
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models.database_models import ScoringConfig
from app.services.auto_pick.scoring_context import ScoringWeights


@dataclass
class LoadedScoringConfig:
    weights: ScoringWeights
    score_threshold: float
    odds_min: int
    odds_max: int
    max_picks: int


def load_scoring_config(db: Session) -> LoadedScoringConfig:
    row = db.query(ScoringConfig).order_by(ScoringConfig.id.asc()).first()
    if row is None:
        return LoadedScoringConfig(
            weights=ScoringWeights(), score_threshold=65.0,
            odds_min=-300, odds_max=400, max_picks=4,
        )
    return LoadedScoringConfig(
        weights=ScoringWeights(
            edge=row.weight_edge, historical=row.weight_historical,
            freshness=row.weight_freshness, line_movement=row.weight_line_movement,
            odds_sanity=row.weight_odds_sanity, model_conf=row.weight_model_conf,
        ),
        score_threshold=row.score_threshold,
        odds_min=row.odds_min, odds_max=row.odds_max,
        max_picks=row.max_picks_per_day,
    )
```

- [ ] **Step 3: Pass; commit**

```bash
pytest tests/auto_pick/test_config_loader.py -v
git add backend/app/services/auto_pick/config_loader.py backend/tests/auto_pick/test_config_loader.py
git commit -m "feat(yetai-picks): scoring config loader from DB"
```

---

## Task 12: Context Builders (Historical Hit Rates + Line Movement)

**Files:**
- Create: `backend/app/services/auto_pick/context_builder.py`
- Create: `backend/tests/auto_pick/test_context_builder.py`

> **Sub-task: Confirm dependencies from spec.** The design's "Dependencies to Confirm" section lists three items: notification routing, historical hit rates from `performance_tracker`, and line movement snapshots. Before writing this task:
>
> 1. Read `backend/app/services/performance_tracker.py` — find the function returning hit rate per `(market_type, league)`. If it doesn't exist, add one that aggregates from existing data. Don't over-engineer; a 90-day rolling SQL query is enough.
> 2. Search for any existing line-movement snapshot table. If none exists, create a minimal one: `line_movement_snapshots(event_id, selection_key, opened_line, current_line, side, last_updated)`. Add a new migration just for this. Populate it lazily from existing odds ingestion (out of scope here — leave a `# TODO: wire into odds ingest` comment, AND create a beads issue tracking that follow-up).
>
> Don't write speculative code. If hit rates don't exist anywhere, build the minimum query; if line movement truly cannot be sourced, return empty dict — the sub-score handles missing data as neutral.

- [ ] **Step 1: Failing test**

```python
from datetime import datetime
from app.services.auto_pick.context_builder import build_scoring_context
from app.services.auto_pick.scoring_context import ScoringContext


def test_build_scoring_context_assembles_all_inputs(db_with_history_and_lines, scoring_config):
    ctx = build_scoring_context(db_with_history_and_lines, scoring_config, now=datetime(2026, 5, 22, 9))
    assert isinstance(ctx, ScoringContext)
    assert ctx.weights == scoring_config.weights
    assert ctx.score_threshold == scoring_config.score_threshold
    assert ("player_prop", "MLB") in ctx.historical_hit_rates
    assert ctx.now == datetime(2026, 5, 22, 9)
```

- [ ] **Step 2: Implement**

```python
# backend/app/services/auto_pick/context_builder.py
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.services.auto_pick.config_loader import LoadedScoringConfig
from app.services.auto_pick.scoring_context import ScoringContext


def build_scoring_context(db: Session, cfg: LoadedScoringConfig, now: datetime) -> ScoringContext:
    historical = _load_historical_hit_rates(db, now)
    line_movement = _load_line_movement(db, now)
    return ScoringContext(
        weights=cfg.weights, score_threshold=cfg.score_threshold,
        historical_hit_rates=historical, line_movement=line_movement, now=now,
    )


def _load_historical_hit_rates(db: Session, now: datetime) -> dict[tuple[str, str], float]:
    # 90-day rolling hit rate, grouped by (market_type, league), from settled YetAIBet
    # entries with status WON/LOST. Concrete SQL filled in based on actual model fields
    # discovered during the dependency audit sub-task.
    cutoff = now - timedelta(days=90)
    # ... implementation per audited performance_tracker entry point
    return {}


def _load_line_movement(db: Session, now: datetime) -> dict[str, dict]:
    # Pull from line_movement_snapshots if it exists; else {}.
    return {}
```

The two private functions should be filled in once the dependency audit finishes. Their SQL is local to this file — do not spread it across the codebase.

- [ ] **Step 3: Pass; commit**

```bash
pytest tests/auto_pick/test_context_builder.py -v
git add backend/app/services/auto_pick/context_builder.py backend/tests/auto_pick/test_context_builder.py
git commit -m "feat(yetai-picks): scoring context builder (historical + line movement)"
```

---

## Task 13: `AutoPickOrchestrator`

**Files:**
- Create: `backend/app/services/auto_pick/orchestrator.py`
- Create: `backend/tests/auto_pick/test_orchestrator.py`

- [ ] **Step 1: Failing tests**

```python
import pytest
from datetime import datetime
from unittest.mock import AsyncMock
from app.models.database_models import YetAIBet, AutoPickRun, AutoPickRunStatus, BetSource
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.orchestrator import AutoPickOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_persists_picks_as_pending_approval(test_db):
    strider = BetCandidate(market_type=MarketType.PLAYER_PROP, league="MLB",
                           event_id="e1", selection="Strider OVER 5.5 K",
                           market_line=5.5, market_odds=-115, our_projection=9.0,
                           projection_metadata={"sample_size": 7, "generated_at": "2026-05-22T08:00:00", "model_confidence": 0.78})
    prov = AsyncMock(); prov.get_candidates = AsyncMock(return_value=[strider])
    orch = AutoPickOrchestrator(db=test_db, providers=[prov], now=datetime(2026,5,22,9))

    result = await orch.run()

    assert result.status == AutoPickRunStatus.SUCCESS
    bets = test_db.query(YetAIBet).filter_by(auto_pick_run_id=result.id).all()
    assert len(bets) == 1
    assert bets[0].status.value == "pending_approval"
    assert bets[0].source == BetSource.AUTO
    assert bets[0].confidence_score >= 65

@pytest.mark.asyncio
async def test_orchestrator_partial_when_one_provider_fails(test_db):
    good = AsyncMock(); good.get_candidates = AsyncMock(return_value=[])
    bad = AsyncMock(); bad.get_candidates = AsyncMock(side_effect=RuntimeError("boom"))
    orch = AutoPickOrchestrator(db=test_db, providers=[good, bad], now=datetime(2026,5,22,9))
    result = await orch.run()
    assert result.status == AutoPickRunStatus.PARTIAL

@pytest.mark.asyncio
async def test_orchestrator_no_picks_when_nothing_clears_threshold(test_db):
    weak = BetCandidate(market_type=MarketType.PLAYER_PROP, league="MLB",
                        event_id="e", selection="weak", market_line=5.5, market_odds=-110,
                        our_projection=5.6, projection_metadata={"sample_size": 2})
    prov = AsyncMock(); prov.get_candidates = AsyncMock(return_value=[weak])
    orch = AutoPickOrchestrator(db=test_db, providers=[prov], now=datetime(2026,5,22,9))
    result = await orch.run()
    assert result.status == AutoPickRunStatus.NO_PICKS
    assert test_db.query(YetAIBet).filter_by(auto_pick_run_id=result.id).count() == 0

@pytest.mark.asyncio
async def test_orchestrator_idempotent_on_rerun(test_db):
    # Same providers + same date should not double-insert picks.
    ...
```

- [ ] **Step 2: Implement**

```python
# backend/app/services/auto_pick/orchestrator.py
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable
from sqlalchemy.orm import Session
from app.models.database_models import (
    YetAIBet, AutoPickRun, AutoPickRunStatus, BetSource, BetStatus,
)
from app.services.auto_pick.candidate import CandidateProvider, DateRange
from app.services.auto_pick.config_loader import load_scoring_config
from app.services.auto_pick.context_builder import build_scoring_context
from app.services.auto_pick.scorer import ConfidenceScorer
from app.services.auto_pick.selector import BetSelector, SelectorConfig, ScoredCandidate

log = logging.getLogger(__name__)


@dataclass
class OrchestratorResult:
    id: int
    status: AutoPickRunStatus
    pick_count: int


class AutoPickOrchestrator:
    def __init__(self, db: Session, providers: list[CandidateProvider],
                 now: datetime, scorer: ConfidenceScorer | None = None):
        self.db = db
        self.providers = providers
        self.now = now
        self.scorer = scorer or ConfidenceScorer()

    async def run(self) -> OrchestratorResult:
        cfg = load_scoring_config(self.db)
        ctx = build_scoring_context(self.db, cfg, self.now)
        selector = BetSelector(SelectorConfig(
            threshold=cfg.score_threshold, odds_min=cfg.odds_min,
            odds_max=cfg.odds_max, max_picks=cfg.max_picks,
        ))

        date_range = DateRange(start=self.now, end=self.now + timedelta(days=1))
        provider_failures = 0
        all_candidates = []
        results = await asyncio.gather(
            *[self._safe_get(p, date_range) for p in self.providers],
            return_exceptions=False,
        )
        for r in results:
            if r is None:
                provider_failures += 1
            else:
                all_candidates.extend(r)

        scored = [ScoredCandidate(candidate=c, score=self.scorer.score(c, ctx))
                  for c in all_candidates]
        picks = selector.select(scored)

        run = AutoPickRun(
            run_at=self.now,
            status=self._compute_status(len(picks), provider_failures, len(self.providers)),
            candidates_considered=len(all_candidates),
            candidates_selected=len(picks),
            dropped_reasons={sc.candidate.event_id: sc.drop_reason for sc in scored if sc.drop_reason},
            error=None,
        )
        self.db.add(run)
        self.db.flush()

        for p in picks:
            self.db.add(self._build_bet(p, run.id))

        self.db.commit()
        log.info("auto_pick run %s: %s picks, status=%s", run.id, len(picks), run.status)
        return OrchestratorResult(id=run.id, status=run.status, pick_count=len(picks))

    async def _safe_get(self, p, date_range):
        try:
            return await p.get_candidates(date_range)
        except Exception:
            log.exception("provider %s failed", type(p).__name__)
            return None

    def _compute_status(self, n_picks, fails, n_providers) -> AutoPickRunStatus:
        if fails == n_providers:
            return AutoPickRunStatus.FAILED
        if fails > 0:
            return AutoPickRunStatus.PARTIAL
        if n_picks == 0:
            return AutoPickRunStatus.NO_PICKS
        return AutoPickRunStatus.SUCCESS

    def _build_bet(self, p: ScoredCandidate, run_id: int) -> YetAIBet:
        c, s = p.candidate, p.score
        return YetAIBet(
            # adapt to existing YetAIBet constructor fields
            status=BetStatus.PENDING_APPROVAL,
            source=BetSource.AUTO,
            auto_pick_run_id=run_id,
            tier_requirement=p.tier,
            confidence_score=s.total,
            score_breakdown=s.breakdown,
            reasoning=s.reasoning,
            # market_type, league, selection, line, odds — map per existing columns
        )
```

> The `_build_bet` mapping to the existing `YetAIBet` columns must match the actual model. Read the model class first; the placeholder fields above are the new ones from Task 1 — the existing ones (e.g., `bet_type`, `selection`, `odds`, `sport`) get filled in from the candidate.

- [ ] **Step 3: Pass; commit**

```bash
pytest tests/auto_pick/test_orchestrator.py -v
git add backend/app/services/auto_pick/orchestrator.py backend/tests/auto_pick/test_orchestrator.py
git commit -m "feat(yetai-picks): AutoPickOrchestrator with audit log"
```

---

## Task 14: Celery Task + Beat Schedule + Admin Notification

**Files:**
- Modify: `backend/app/celery_app.py`
- Create: `backend/app/tasks/auto_pick.py`
- Create: `backend/tests/auto_pick/test_auto_pick_task.py`

- [ ] **Step 1: Failing test**

```python
import pytest
from unittest.mock import patch, AsyncMock
from app.tasks.auto_pick import auto_pick_yetai_bets


def test_celery_task_invokes_orchestrator_with_correct_now():
    with patch("app.tasks.auto_pick.AutoPickOrchestrator") as Orch:
        instance = Orch.return_value
        instance.run = AsyncMock(return_value=type("R", (), {"id": 1, "pick_count": 2, "status": "success"})())
        auto_pick_yetai_bets.run()
        assert Orch.called
```

- [ ] **Step 2: Implement task**

```python
# backend/app/tasks/auto_pick.py
import asyncio
import logging
from datetime import datetime
from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.services.auto_pick.providers.player_prop_provider import PlayerPropCandidateProvider
from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
from app.services.auto_pick.providers.totals_provider import TotalsCandidateProvider
from app.services.auto_pick.providers.moneyline_provider import MoneylineCandidateProvider
from app.services.notification_router import notify_admin

log = logging.getLogger(__name__)


def _build_providers():
    # Wire each provider to its underlying source service. Sources are imported
    # lazily inside their respective constructors to avoid import-time cycles.
    return [
        PlayerPropCandidateProvider(source=_load("player_props")),
        SpreadCandidateProvider(source=_load("spread")),
        TotalsCandidateProvider(source=_load("totals")),
        MoneylineCandidateProvider(source=_load("moneyline")),
    ]


def _load(name: str):
    # Map to concrete service modules; concrete imports filled in during Task 10's
    # dependency audit. Each source must expose async get_todays_projections(date_range).
    raise NotImplementedError(f"wire source for {name}")


@celery_app.task(name="auto_pick.yetai_bets")
def auto_pick_yetai_bets():
    db = SessionLocal()
    try:
        orch = AutoPickOrchestrator(db=db, providers=_build_providers(), now=datetime.utcnow())
        result = asyncio.run(orch.run())
        notify_admin(
            subject=f"YetAI auto-picks: {result.pick_count} pending approval",
            body=f"Run {result.id} completed with status {result.status}.",
        )
        return {"run_id": result.id, "picks": result.pick_count, "status": str(result.status)}
    finally:
        db.close()
```

- [ ] **Step 3: Wire Celery beat**

In `backend/app/celery_app.py`, add `"app.tasks.auto_pick"` to `include=[...]`. Then append to `beat_schedule`:

```python
celery_app.conf.beat_schedule = {
    # ... existing entries ...
    "auto_pick_yetai_bets_daily": {
        "task": "auto_pick.yetai_bets",
        "schedule": crontab(hour=13, minute=0),  # 9:00 AM ET == 13:00 UTC
    },
}
```

- [ ] **Step 4: Pass; commit**

```bash
pytest tests/auto_pick/test_auto_pick_task.py -v
git add backend/app/tasks/auto_pick.py backend/app/celery_app.py backend/tests/auto_pick/test_auto_pick_task.py
git commit -m "feat(yetai-picks): celery task + 9AM ET beat schedule + admin notification"
```

---

## Task 15: Admin API — List/Approve/Edit/Reject Pending Picks

**Files:**
- Create: `backend/app/api/admin_yetai_picks.py`
- Modify: `backend/app/main.py` (register router)
- Create: `backend/tests/auto_pick/test_admin_api.py`

- [ ] **Step 1: Failing tests**

```python
def test_list_pending_picks_returns_today(admin_client, seeded_pending_picks):
    r = admin_client.get("/api/admin/yetai-picks/pending")
    assert r.status_code == 200
    body = r.json()
    assert len(body["picks"]) == 3
    assert all(p["status"] == "pending_approval" for p in body["picks"])
    assert body["picks"][0]["score_breakdown"] is not None

def test_approve_flips_to_live(admin_client, seeded_pending_picks):
    pid = seeded_pending_picks[0].id
    r = admin_client.post(f"/api/admin/yetai-picks/{pid}/approve")
    assert r.status_code == 200
    assert r.json()["status"] in ("active", "live", "open")

def test_reject_marks_rejected(admin_client, seeded_pending_picks):
    pid = seeded_pending_picks[0].id
    r = admin_client.post(f"/api/admin/yetai-picks/{pid}/reject")
    assert r.json()["status"] == "rejected"

def test_edit_updates_fields(admin_client, seeded_pending_picks):
    pid = seeded_pending_picks[0].id
    r = admin_client.patch(f"/api/admin/yetai-picks/{pid}",
                            json={"tier_requirement": "pro", "reasoning": "Manual override"})
    assert r.json()["tier_requirement"] == "pro"
    assert r.json()["reasoning"] == "Manual override"

def test_non_admin_blocked(client, seeded_pending_picks):
    r = client.get("/api/admin/yetai-picks/pending")
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Implement router**

```python
# backend/app/api/admin_yetai_picks.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.auth import require_admin  # use existing admin dep
from app.models.database_models import YetAIBet, BetStatus, SubscriptionTier

router = APIRouter(prefix="/api/admin/yetai-picks", tags=["admin-yetai-picks"])


class EditPickRequest(BaseModel):
    tier_requirement: SubscriptionTier | None = None
    reasoning: str | None = None
    selection: str | None = None
    market_line: float | None = None
    market_odds: int | None = None


def _serialize(bet: YetAIBet) -> dict:
    return {
        "id": bet.id,
        "status": bet.status.value if hasattr(bet.status, "value") else bet.status,
        "tier_requirement": bet.tier_requirement.value if bet.tier_requirement else None,
        "confidence_score": bet.confidence_score,
        "score_breakdown": bet.score_breakdown,
        "reasoning": bet.reasoning,
        "source": bet.source.value if hasattr(bet.source, "value") else bet.source,
        # plus existing YetAIBet fields (selection, odds, sport, etc.)
    }


@router.get("/pending")
def list_pending(_=Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(YetAIBet).filter(YetAIBet.status == BetStatus.PENDING_APPROVAL).all()
    return {"picks": [_serialize(b) for b in rows]}


@router.post("/{pick_id}/approve")
def approve(pick_id: int, _=Depends(require_admin), db: Session = Depends(get_db)):
    bet = db.query(YetAIBet).get(pick_id)
    if not bet:
        raise HTTPException(404)
    bet.status = BetStatus.ACTIVE  # use whatever the existing "live" status enum value is
    db.commit()
    return _serialize(bet)


@router.post("/{pick_id}/reject")
def reject(pick_id: int, _=Depends(require_admin), db: Session = Depends(get_db)):
    bet = db.query(YetAIBet).get(pick_id)
    if not bet:
        raise HTTPException(404)
    bet.status = BetStatus.REJECTED
    db.commit()
    return _serialize(bet)


@router.patch("/{pick_id}")
def edit(pick_id: int, payload: EditPickRequest,
         _=Depends(require_admin), db: Session = Depends(get_db)):
    bet = db.query(YetAIBet).get(pick_id)
    if not bet:
        raise HTTPException(404)
    for field, val in payload.dict(exclude_unset=True).items():
        setattr(bet, field, val)
    db.commit()
    return _serialize(bet)


@router.post("/approve-all")
def approve_all(_=Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(YetAIBet).filter(YetAIBet.status == BetStatus.PENDING_APPROVAL).all()
    for bet in rows:
        bet.status = BetStatus.ACTIVE
    db.commit()
    return {"approved": [b.id for b in rows]}
```

Add a matching test:

```python
def test_approve_all_flips_every_pending(admin_client, seeded_pending_picks):
    r = admin_client.post("/api/admin/yetai-picks/approve-all")
    assert r.status_code == 200
    assert len(r.json()["approved"]) == len(seeded_pending_picks)
```

In `backend/app/main.py`, register the router alongside other admin routers.

- [ ] **Step 3: Pass; commit**

```bash
pytest tests/auto_pick/test_admin_api.py -v
git add backend/app/api/admin_yetai_picks.py backend/app/main.py backend/tests/auto_pick/test_admin_api.py
git commit -m "feat(yetai-picks): admin API for pending pick approval/edit/reject"
```

---

## Task 16: Tier-Gated Visibility (subscriber side)

Approved bets must only be visible to subscribers at the assigned tier *or higher*. The existing YetAI bets list endpoint may already filter by `tier_requirement` — verify and extend if not. Auto-picks must also exclude `PENDING_APPROVAL` and `REJECTED` and `EXPIRED` from the public list.

**Files:**
- Modify: existing YetAI bets list endpoint (likely in `backend/app/api/` — find via `grep -r "yetai.*bets" backend/app/api`)
- Modify or extend: `backend/app/services/yetai_bets_service_db.py`
- Create: `backend/tests/auto_pick/test_tier_visibility.py`

- [ ] **Step 1: Failing tests**

```python
def test_free_user_sees_only_free_tier_picks(free_client, mixed_tier_bets):
    r = free_client.get("/api/yetai-bets")
    tiers = [b["tier_requirement"] for b in r.json()["bets"]]
    assert set(tiers) <= {"free"}

def test_pro_user_sees_free_and_pro(pro_client, mixed_tier_bets):
    r = pro_client.get("/api/yetai-bets")
    tiers = {b["tier_requirement"] for b in r.json()["bets"]}
    assert tiers <= {"free", "pro"}

def test_elite_user_sees_all_tiers(elite_client, mixed_tier_bets):
    r = elite_client.get("/api/yetai-bets")
    tiers = {b["tier_requirement"] for b in r.json()["bets"]}
    assert tiers == {"free", "pro", "elite"}

def test_pending_picks_never_visible_to_subscribers(pro_client, pending_pick):
    r = pro_client.get("/api/yetai-bets")
    assert pending_pick.id not in [b["id"] for b in r.json()["bets"]]
```

- [ ] **Step 2: Implement filter changes**

In the list endpoint:

```python
TIER_RANK = {SubscriptionTier.FREE: 0, SubscriptionTier.PRO: 1, SubscriptionTier.ELITE: 2}

def visible_bets_for(user, db):
    user_rank = TIER_RANK[user.subscription_tier]
    return (
        db.query(YetAIBet)
        .filter(YetAIBet.status == BetStatus.ACTIVE)
        .filter(YetAIBet.tier_requirement.in_(
            [t for t, r in TIER_RANK.items() if r <= user_rank]
        ))
        .all()
    )
```

- [ ] **Step 3: Pass; commit**

```bash
pytest tests/auto_pick/test_tier_visibility.py -v
git add backend/app/api backend/app/services/yetai_bets_service_db.py backend/tests/auto_pick/test_tier_visibility.py
git commit -m "feat(yetai-picks): enforce tier-gated visibility, hide non-active statuses"
```

---

## Task 17: Auto-Expire Pending Picks at Game Start

**Files:**
- Create: `backend/app/tasks/expire_pending_picks.py`
- Modify: `backend/app/celery_app.py`
- Create: `backend/tests/auto_pick/test_expire_pending.py`

- [ ] **Step 1: Failing test**

```python
from datetime import datetime, timedelta
from app.tasks.expire_pending_picks import expire_pending_picks


def test_expires_pending_picks_with_started_games(test_db, pending_pick_with_game_at):
    pending_pick_with_game_at(datetime.utcnow() - timedelta(minutes=5))  # started
    pending_pick_with_game_at(datetime.utcnow() + timedelta(hours=2))    # future
    expired = expire_pending_picks.run()
    assert expired == 1
```

- [ ] **Step 2: Implement**

```python
# backend/app/tasks/expire_pending_picks.py
from datetime import datetime
from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.database_models import YetAIBet, BetStatus


@celery_app.task(name="auto_pick.expire_pending")
def expire_pending_picks():
    db = SessionLocal()
    try:
        count = 0
        now = datetime.utcnow()
        rows = db.query(YetAIBet).filter(
            YetAIBet.status == BetStatus.PENDING_APPROVAL,
            YetAIBet.game_start_at <= now,  # whatever the existing event-start column is
        ).all()
        for r in rows:
            r.status = BetStatus.EXPIRED
            count += 1
        db.commit()
        return count
    finally:
        db.close()
```

Add to beat schedule, every 5 minutes:

```python
"expire_pending_yetai_picks": {
    "task": "auto_pick.expire_pending",
    "schedule": crontab(minute="*/5"),
},
```

- [ ] **Step 3: Pass; commit**

```bash
pytest tests/auto_pick/test_expire_pending.py -v
git add backend/app/tasks/expire_pending_picks.py backend/app/celery_app.py backend/tests/auto_pick/test_expire_pending.py
git commit -m "feat(yetai-picks): auto-expire pending picks at game start"
```

---

## Task 18: Backtest CLI

**Files:**
- Create: `backend/app/services/auto_pick/backtest.py`
- Create: `backend/app/services/auto_pick/__main__.py` (so `python -m` works)
- Create: `backend/tests/auto_pick/test_backtest.py`

- [ ] **Step 1: Failing test**

```python
from datetime import date
from app.services.auto_pick.backtest import run_backtest


def test_backtest_returns_summary_with_hit_rate(historical_db):
    result = run_backtest(start=date(2026,2,1), end=date(2026,2,15), db=historical_db)
    assert "by_tier" in result
    assert "overall_hit_rate" in result
    assert "calibration" in result
```

- [ ] **Step 2: Implement**

```python
# backend/app/services/auto_pick/backtest.py
"""
Replay historical odds + projections through the scorer + selector and report
hit rates, ROI, and score-vs-outcome calibration. Used for tuning weights and
threshold without flying blind.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from app.services.auto_pick.config_loader import load_scoring_config
from app.services.auto_pick.context_builder import build_scoring_context
from app.services.auto_pick.scorer import ConfidenceScorer
from app.services.auto_pick.selector import BetSelector, SelectorConfig, ScoredCandidate


def run_backtest(start: date, end: date, db: Session) -> dict:
    cfg = load_scoring_config(db)
    scorer = ConfidenceScorer()
    selector = BetSelector(SelectorConfig(threshold=cfg.score_threshold,
                                           odds_min=cfg.odds_min, odds_max=cfg.odds_max,
                                           max_picks=cfg.max_picks))
    by_tier = {"free": [0, 0], "pro": [0, 0], "elite": [0, 0]}  # [wins, total]
    calibration = {bucket: [0, 0] for bucket in (65, 70, 75, 80, 85, 90, 95)}

    cur = start
    while cur <= end:
        now = datetime.combine(cur, datetime.min.time())
        ctx = build_scoring_context(db, cfg, now)
        historical_candidates = _load_historical_candidates_for(db, cur)
        scored = [ScoredCandidate(candidate=c, score=scorer.score(c, ctx)) for c in historical_candidates]
        picks = selector.select(scored)
        for p in picks:
            won = _did_win(db, p.candidate)
            by_tier[p.tier.value][1] += 1
            by_tier[p.tier.value][0] += int(won)
            bucket = min(95, 5 * (int(p.score.total) // 5))
            if bucket in calibration:
                calibration[bucket][1] += 1
                calibration[bucket][0] += int(won)
        cur += timedelta(days=1)

    return {
        "by_tier": {k: {"wins": v[0], "total": v[1],
                         "hit_rate": (v[0]/v[1]) if v[1] else None}
                     for k, v in by_tier.items()},
        "overall_hit_rate": _ratio([by_tier[t][0] for t in by_tier],
                                    [by_tier[t][1] for t in by_tier]),
        "calibration": calibration,
    }


def _ratio(wins, totals):
    w, t = sum(wins), sum(totals)
    return (w/t) if t else None


def _load_historical_candidates_for(db: Session, d: date) -> list:
    """
    Return BetCandidate-shaped objects from settled history on date `d`.
    Source: existing settled YetAIBet rows + the projection that was used at
    pick time (must be persisted in score_breakdown or a sibling table; if
    historical projections aren't stored, this function returns [] and the
    backtest only covers forward-looking runs).
    """
    raise NotImplementedError("fill in based on settled YetAIBet + stored projections")


def _did_win(db: Session, candidate) -> bool:
    """
    Look up the actual outcome for `candidate.event_id` + `candidate.selection`
    in settled YetAIBet rows. Returns True if status == WON, False if LOST.
    """
    raise NotImplementedError("fill in based on settled YetAIBet status enum")
```

> These two stubs are deliberately left as `NotImplementedError` because the exact SQL depends on what historical projection data is actually persisted (audit during Task 10 will surface this). If historical projections aren't currently stored alongside settled bets, the backtest's value is limited — file a follow-up beads issue to start persisting `score_breakdown` snapshots on every pick going forward, so the backtest gets richer over time.

`_load_historical_candidates_for` and `_did_win` pull from your existing settled `YetAIBet` history + projection logs. Concrete SQL filled in based on what exists.

- [ ] **Step 3: Implement CLI entry point**

```python
# backend/app/services/auto_pick/__main__.py
import argparse
import json
from datetime import date
from app.core.database import SessionLocal
from app.services.auto_pick.backtest import run_backtest


def main():
    p = argparse.ArgumentParser(prog="python -m app.services.auto_pick")
    sub = p.add_subparsers(dest="cmd", required=True)
    bt = sub.add_parser("backtest")
    bt.add_argument("--start", required=True, type=lambda s: date.fromisoformat(s))
    bt.add_argument("--end", required=True, type=lambda s: date.fromisoformat(s))
    args = p.parse_args()
    db = SessionLocal()
    try:
        print(json.dumps(run_backtest(args.start, args.end, db), indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Pass; commit**

```bash
pytest tests/auto_pick/test_backtest.py -v
python -m app.services.auto_pick backtest --start 2026-02-01 --end 2026-02-07  # smoke test
git add backend/app/services/auto_pick/backtest.py backend/app/services/auto_pick/__main__.py backend/tests/auto_pick/test_backtest.py
git commit -m "feat(yetai-picks): backtest CLI for tuning weights and threshold"
```

---

## Task 19: Admin Portal Frontend — Pending Picks View

**Files:**
- Create: `frontend/src/app/admin/yetai-picks/page.tsx`
- Create: `frontend/src/app/admin/yetai-picks/PendingPickCard.tsx`
- Create: `frontend/src/lib/api/yetai-picks.ts`

- [ ] **Step 1: Add API client**

```typescript
// frontend/src/lib/api/yetai-picks.ts
import { apiFetch } from "@/lib/api/client"; // existing helper

export type PendingPick = {
  id: number;
  status: string;
  tier_requirement: "free" | "pro" | "elite";
  confidence_score: number;
  score_breakdown: Record<string, number>;
  reasoning: string;
  source: "manual" | "auto";
  selection?: string;
  market_line?: number;
  market_odds?: number;
  sport?: string;
};

export async function listPendingPicks(): Promise<{ picks: PendingPick[] }> {
  return apiFetch("/api/admin/yetai-picks/pending");
}
export async function approvePick(id: number) {
  return apiFetch(`/api/admin/yetai-picks/${id}/approve`, { method: "POST" });
}
export async function rejectPick(id: number) {
  return apiFetch(`/api/admin/yetai-picks/${id}/reject`, { method: "POST" });
}
export async function editPick(id: number, patch: Partial<PendingPick>) {
  return apiFetch(`/api/admin/yetai-picks/${id}`, {
    method: "PATCH", body: JSON.stringify(patch),
  });
}
```

- [ ] **Step 2: Build the page**

```tsx
// frontend/src/app/admin/yetai-picks/page.tsx
"use client";
import { useEffect, useState } from "react";
import { listPendingPicks, type PendingPick } from "@/lib/api/yetai-picks";
import { PendingPickCard } from "./PendingPickCard";

export default function PendingPicksPage() {
  const [picks, setPicks] = useState<PendingPick[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = () => {
    setLoading(true);
    listPendingPicks().then(r => setPicks(r.picks)).finally(() => setLoading(false));
  };
  useEffect(refresh, []);

  if (loading) return <div className="p-6">Loading…</div>;
  if (picks.length === 0) return <div className="p-6">No pending YetAI picks today.</div>;

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold">Pending YetAI Picks</h1>
      <div className="grid gap-4">
        {picks.map(p => <PendingPickCard key={p.id} pick={p} onChanged={refresh} />)}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Build the card**

```tsx
// frontend/src/app/admin/yetai-picks/PendingPickCard.tsx
"use client";
import { approvePick, rejectPick, editPick, type PendingPick } from "@/lib/api/yetai-picks";
import { useState } from "react";

export function PendingPickCard({ pick, onChanged }: { pick: PendingPick; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const handle = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); onChanged(); } finally { setBusy(false); }
  };

  return (
    <div className="rounded-lg border p-4 bg-white shadow-sm">
      <div className="flex justify-between items-start">
        <div>
          <div className="text-sm uppercase text-gray-500">{pick.sport} · {pick.tier_requirement.toUpperCase()}</div>
          <div className="font-semibold text-lg">{pick.selection}</div>
          <div className="text-sm text-gray-600">Odds: {pick.market_odds} · Line: {pick.market_line}</div>
        </div>
        <div className="text-right">
          <div className="text-3xl font-mono">{pick.confidence_score.toFixed(1)}</div>
          <div className="text-xs text-gray-500">confidence</div>
        </div>
      </div>
      <p className="mt-2 text-sm text-gray-700">{pick.reasoning}</p>
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer text-gray-500">Score breakdown</summary>
        <pre className="bg-gray-50 p-2 mt-1 rounded">{JSON.stringify(pick.score_breakdown, null, 2)}</pre>
      </details>
      <div className="mt-4 flex gap-2">
        <button disabled={busy} onClick={() => handle(() => approvePick(pick.id))}
                className="px-3 py-1 bg-green-600 text-white rounded">Approve</button>
        <button disabled={busy} onClick={() => handle(() => rejectPick(pick.id))}
                className="px-3 py-1 bg-red-600 text-white rounded">Reject</button>
        <button disabled={busy}
                onClick={() => {
                  const reasoning = prompt("New reasoning:", pick.reasoning);
                  if (reasoning !== null) handle(() => editPick(pick.id, { reasoning }));
                }}
                className="px-3 py-1 bg-gray-200 rounded">Edit reasoning</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Smoke test in browser**

```bash
cd frontend && npm run dev
# In separate terminal: ensure backend is up and you have a few PENDING_APPROVAL rows
# Visit http://localhost:3000/admin/yetai-picks as an admin user
# Confirm: cards render, score breakdown expands, approve/reject buttons work
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/admin/yetai-picks/ frontend/src/lib/api/yetai-picks.ts
git commit -m "feat(yetai-picks): admin frontend for pending pick approval"
```

---

## Task 20: Feature Flag + Rollout

**Files:**
- Modify: `backend/app/celery_app.py` (gate the beat entry)
- Modify: `frontend/src/app/admin/yetai-picks/page.tsx` (gate the route)
- Modify: env config

- [ ] **Step 1: Add env flag**

In backend env config: `AUTO_YETAI_PICKS_ENABLED` (default `false`).
In frontend env: `NEXT_PUBLIC_AUTO_YETAI_PICKS_ENABLED` (default `false`).

- [ ] **Step 2: Gate Celery beat entry**

```python
import os
if os.getenv("AUTO_YETAI_PICKS_ENABLED", "false").lower() == "true":
    celery_app.conf.beat_schedule["auto_pick_yetai_bets_daily"] = {
        "task": "auto_pick.yetai_bets",
        "schedule": crontab(hour=13, minute=0),
    }
```

- [ ] **Step 3: Gate frontend route**

In `page.tsx`, if `process.env.NEXT_PUBLIC_AUTO_YETAI_PICKS_ENABLED !== "true"`, render a placeholder or 404. (Or use Next.js middleware. Match existing patterns in the codebase.)

- [ ] **Step 4: Add rollout instructions to README**

In `backend/README.md` (or a new `docs/runbooks/auto-yetai-picks.md`), document:
1. Run migrations.
2. Set `AUTO_YETAI_PICKS_ENABLED=true` in backend env, restart Celery beat + worker.
3. Observe `auto_pick_runs` table for ~1 week in shadow mode (frontend flag off).
4. Flip frontend flag on; admin starts approving real picks.
5. After 2–3 weeks of live data, tune `scoring_config` row.

- [ ] **Step 5: Commit**

```bash
git add backend/app/celery_app.py frontend/src/app/admin/yetai-picks/page.tsx backend/README.md
git commit -m "feat(yetai-picks): feature flag gating + rollout runbook"
```

---

## Final verification

- [ ] Run full backend test suite: `cd backend && pytest tests/auto_pick -v`
- [ ] Run frontend lint: `cd frontend && npm run lint`
- [ ] Manual smoke: trigger Celery task locally (`celery -A app.celery_app call auto_pick.yetai_bets`), confirm rows appear in `auto_pick_runs` and `yetai_bets`, visit admin page, approve one, confirm visibility per tier.
- [ ] Run backtest on 30 days of history, eyeball calibration.
- [ ] Confirm spec dependencies were handled in Task 12 (notification, hit rates, line movement).
