# NFL Receiving Yards Projections — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a lined-only NFL receiving-yards betting board (RB/WR/TE) with Model / Market / Edge / Pick via non-ML expected yards + soft-anchor against Odds `player_reception_yds`, exposed on `GET /predictions/nfl` and `/predictions/nfl` with a position filter.

**Architecture:** Clone the QB pass-yards vertical end-to-end, but build the universe from the Odds slate first (lined players only). Feature join reuses ATD-adjacent usage (`target_share`, snaps, depth) plus game-line pace; `model_yards = expected_targets × ypr × depth/pace/matchup`; publish `α·model + (1−α)·line` with `NFL_RECV_ANCHOR_ALPHA` (default 0.25); fail-closed Odds attach; one PropGroup table with All/RB/WR/TE filter. No residual ML in v1.

**Tech Stack:** Python 3, SQLAlchemy/Alembic, Celery, nfl-data-py, Odds API (`player_reception_yds`), FastAPI, Next.js/TS, pytest, Black, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-10-nfl-receiving-yards-projections-design.md`  
**Soft-anchor template:** PR #162 / `qb_passing_yards_ml.soft_anchor_qb_yards` on `origin/main`

## Global Constraints

- Odds market: `player_reception_yds` only (not `player_receptions` / `player_rush_yds`).
- Universe: **lined players only** (must have attachable reception-yards O/U); RB/WR/TE product surface.
- Model v1: strong non-ML `targets × YPR` + depth/pace/matchup, then soft-anchor; **no** residual ML, no `NFL_RECV_ML_ENABLED`, no `ml_shadow_yards`.
- Soft-anchor α: `NFL_RECV_ANCHOR_ALPHA` default **0.25**; never publish raw `ou_line` as `predicted_receiving_yards` when a model exists; never invent targets from the line.
- Odds attach: **fail-closed** — no invented lines, no synthetic Market/Edge/Pick; omit unmatched players from the board.
- UI: one PropGroup on `/predictions/nfl` with client position filter All / RB / WR / TE; hub copy must mention receiving yards.
- Unique prediction key: `(season, week, player_id)`.
- Edge/pick thresholds mirror QB yards recommender: min edge **7%**, min confidence **0.70**, strong edge **12%**, strong confidence **0.75** (no O/U classifier in v1).
- Before each Python commit: `cd backend && python3 -m black` on touched files + targeted pytest; stage specific paths only. Frontend commits: lint/type-check/test:ci for touched area.
- Out of scope for this plan: residual ML, rush yards board, receptions board, auto-pick source, accuracy buckets (optional stub only), Monte Carlo yards engine, preseason surface.

## File map

| Path | Responsibility |
|------|----------------|
| `backend/app/services/etl/nfl/recv_yds_model.py` | Pure math: expected targets, model yards, soft-anchor α, publish helper |
| `backend/app/services/etl/nfl/recv_yds_features.py` | Build feature dicts for lined RB/WR/TE (usage, YPR, depth, pace, matchup) |
| `backend/app/services/etl/nfl/recv_yds_projector.py` | Features → model_yards → soft-anchor → upsert `pred_recv_yds_predictions` |
| `backend/app/services/etl/nfl/recv_yds_betting.py` | Odds `player_reception_yds` slate + fail-closed attach / edge / pick |
| `backend/app/services/etl/nfl/recv_yds_weekly.py` | Chain: slate → features → project → betting fields |
| `backend/app/services/etl/nfl/recv_yds_usage.py` | Odds name → nflverse/ATD usage priors (`target_share`, YPR, snaps) |
| `backend/app/services/etl/nfl/collect_recv_yds_actuals.py` | Grade actual receiving yards → `pred_recv_yds_actuals` |
| `backend/app/models/predictions_models.py` | `RecvYdsPredictions`, `RecvYdsActuals` ORM |
| `backend/alembic/versions/2026_11_10_nfl_recv_yds.py` | Create `pred_recv_yds_predictions` + `pred_recv_yds_actuals` |
| `backend/app/tasks/etl_pipeline.py` | Celery leaf `nfl.recv_yds_weekly` (+ actuals) in `NFL_PHASES` / gameday |
| `backend/app/services/player_props_service.py` | Add `player_reception_yds` to `FALLBACK_PLAYER_PROP_MARKETS` NFL list |
| `backend/app/api/v1/predictions.py` | `receiving_yards_predictions` on `GET /nfl` |
| `backend/app/services/player_prop_projection_display.py` | Enrich recv yards rows (Model/Market/Edge/Pick) |
| `backend/.env.example` | Document `NFL_RECV_ANCHOR_ALPHA` |
| `backend/docs/NFL_ETL_PARITY.md` | Module / phase / API map for recv yards |
| `backend/docs/NFL_ML_OPS.md` | Note recv soft-anchor (no ML promote in v1) |
| `frontend/src/lib/propProjectionDisplay.ts` | `NFL_RECV_YDS_COLUMNS` (+ Pos) |
| `frontend/src/lib/propPositionFilter.ts` | `filterRowsByPosition` / All·RB·WR·TE |
| `frontend/src/components/yetai/SportPredictionsPage.tsx` | Optional `positionFilterKey` on `PropGroup` |
| `frontend/src/app/predictions/nfl/page.tsx` | Receiving Yards PropGroup |
| `frontend/src/app/predictions/stats/page.tsx` | Hub card desc includes receiving yards |
| `docs/api/openapi*.json` | Regenerated after API change |
| Tests under `backend/tests/test_nfl_recv_yds_*.py` and `frontend/src/lib/propProjectionDisplay.nfl-recv-yds.test.ts` | TDD coverage |

---

### Task 1: Soft-anchor + non-ML model math

**Files:**
- Create: `backend/app/services/etl/nfl/recv_yds_model.py`
- Create: `backend/tests/test_nfl_recv_yds_model.py`

**Interfaces:**
- Consumes: env `NFL_RECV_ANCHOR_ALPHA`
- Produces:
  - `DEFAULT_RECV_ANCHOR_ALPHA: float` (= `0.25`)
  - `recv_anchor_alpha() -> float`  # clamp [0,1]; NaN/invalid → default
  - `expected_targets(*, target_share: float | None, team_pass_attempts: float | None, snap_pct: float | None = None) -> float | None`
  - `model_receiving_yards(*, expected_targets: float, ypr: float, depth_adj: float = 1.0, pace_adj: float = 1.0, matchup_adj: float = 1.0) -> float`
  - `soft_anchor_recv_yards(*, model_yards: float, ou_line: float, alpha: float | None = None) -> float`
  - `published_recv_yards(*, model_yards: float | None, ou_line: float | None, line_is_real: bool, anchor_alpha: float | None = None) -> tuple[float | None, str | None]`
  - Invariant: if `expected_targets` inputs missing → `None` (never invent from line)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_nfl_recv_yds_model.py
import math

from app.services.etl.nfl.recv_yds_model import (
    DEFAULT_RECV_ANCHOR_ALPHA,
    expected_targets,
    model_receiving_yards,
    published_recv_yards,
    recv_anchor_alpha,
    soft_anchor_recv_yards,
)


def test_recv_anchor_alpha_defaults_to_quarter(monkeypatch):
    monkeypatch.delenv("NFL_RECV_ANCHOR_ALPHA", raising=False)
    assert DEFAULT_RECV_ANCHOR_ALPHA == 0.25
    assert recv_anchor_alpha() == 0.25


def test_recv_anchor_alpha_clamps_and_handles_nan(monkeypatch):
    monkeypatch.setenv("NFL_RECV_ANCHOR_ALPHA", "1.5")
    assert recv_anchor_alpha() == 1.0
    monkeypatch.setenv("NFL_RECV_ANCHOR_ALPHA", "-0.2")
    assert recv_anchor_alpha() == 0.0
    monkeypatch.setenv("NFL_RECV_ANCHOR_ALPHA", "nan")
    assert recv_anchor_alpha() == 0.25
    monkeypatch.setenv("NFL_RECV_ANCHOR_ALPHA", "nope")
    assert recv_anchor_alpha() == 0.25


def test_soft_anchor_recv_yards_spec_example():
    # Spec: model=100, line=80, α=0.25 → 85.0
    assert soft_anchor_recv_yards(model_yards=100.0, ou_line=80.0, alpha=0.25) == 85.0
    assert soft_anchor_recv_yards(model_yards=100.0, ou_line=80.0, alpha=1.0) == 100.0
    assert soft_anchor_recv_yards(model_yards=100.0, ou_line=80.0, alpha=0.0) == 80.0


def test_expected_targets_from_share_times_attempts():
    assert expected_targets(target_share=0.25, team_pass_attempts=36.0) == 9.0


def test_expected_targets_never_invents_from_missing_usage():
    assert expected_targets(target_share=None, team_pass_attempts=36.0) is None
    assert expected_targets(target_share=0.25, team_pass_attempts=None) is None
    assert expected_targets(target_share=0.0, team_pass_attempts=36.0) is None


def test_model_receiving_yards_multiplicative():
    yards = model_receiving_yards(
        expected_targets=8.0,
        ypr=12.5,
        depth_adj=1.05,
        pace_adj=0.95,
        matchup_adj=1.1,
    )
    assert abs(yards - (8.0 * 12.5 * 1.05 * 0.95 * 1.1)) < 1e-9


def test_published_recv_yards_soft_anchors_when_line_and_model():
    yards, method = published_recv_yards(
        model_yards=100.0, ou_line=80.0, line_is_real=True, anchor_alpha=0.25
    )
    assert yards == 85.0
    assert method == "soft_anchor"
    assert yards != 80.0


def test_published_recv_yards_skips_without_model_or_line():
    yards, method = published_recv_yards(
        model_yards=None, ou_line=80.0, line_is_real=True
    )
    assert yards is None and method is None
    yards, method = published_recv_yards(
        model_yards=100.0, ou_line=None, line_is_real=False
    )
    assert yards is None and method is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_model.py -v`  
Expected: FAIL with `ModuleNotFoundError` / import error for `recv_yds_model`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/etl/nfl/recv_yds_model.py
"""Non-ML receiving-yards model + soft-anchor publish (QB #162 pattern)."""

from __future__ import annotations

import os

DEFAULT_RECV_ANCHOR_ALPHA = 0.25


def recv_anchor_alpha() -> float:
    """Model weight α in soft-anchor publish: ``α·model + (1−α)·line``."""
    raw = os.getenv("NFL_RECV_ANCHOR_ALPHA", str(DEFAULT_RECV_ANCHOR_ALPHA)).strip()
    try:
        alpha = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_RECV_ANCHOR_ALPHA
    if alpha != alpha:  # NaN
        return DEFAULT_RECV_ANCHOR_ALPHA
    return min(1.0, max(0.0, alpha))


def expected_targets(
    *,
    target_share: float | None,
    team_pass_attempts: float | None,
    snap_pct: float | None = None,
) -> float | None:
    """Honest usage prior. Never invent targets from a market line.

    ``snap_pct`` is reserved for future depth blends; v1 requires share × attempts.
    """
    del snap_pct  # unused in v1; kept for API stability
    if target_share is None or team_pass_attempts is None:
        return None
    share = float(target_share)
    attempts = float(team_pass_attempts)
    if share <= 0 or attempts <= 0:
        return None
    return share * attempts


def model_receiving_yards(
    *,
    expected_targets: float,
    ypr: float,
    depth_adj: float = 1.0,
    pace_adj: float = 1.0,
    matchup_adj: float = 1.0,
) -> float:
    """``targets × YPR × depth/pace/matchup`` — independent of the O/U line."""
    return (
        float(expected_targets)
        * float(ypr)
        * float(depth_adj)
        * float(pace_adj)
        * float(matchup_adj)
    )


def soft_anchor_recv_yards(
    *,
    model_yards: float,
    ou_line: float,
    alpha: float | None = None,
) -> float:
    """Blend model toward the market line: ``α·model + (1−α)·line``."""
    a = DEFAULT_RECV_ANCHOR_ALPHA if alpha is None else float(alpha)
    a = min(1.0, max(0.0, a))
    model = float(model_yards)
    line = float(ou_line)
    if a >= 1.0 - 1e-12:
        return round(model, 1)
    if a <= 1e-12:
        return round(line, 1)
    return round(a * model + (1.0 - a) * line, 1)


def published_recv_yards(
    *,
    model_yards: float | None,
    ou_line: float | None,
    line_is_real: bool,
    anchor_alpha: float | None = None,
) -> tuple[float | None, str | None]:
    """Publish soft-anchored yards when both model and a real line exist.

    Never returns the raw market line as the sole projection when model is missing.
    """
    if not line_is_real or ou_line is None or model_yards is None:
        return None, None
    alpha = recv_anchor_alpha() if anchor_alpha is None else float(anchor_alpha)
    return (
        soft_anchor_recv_yards(
            model_yards=float(model_yards),
            ou_line=float(ou_line),
            alpha=alpha,
        ),
        "soft_anchor",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_model.py -v`  
Expected: PASS (all tests)

- [ ] **Step 5: Format and commit**

```bash
cd backend && python3 -m black app/services/etl/nfl/recv_yds_model.py tests/test_nfl_recv_yds_model.py
cd /agent/repos/yetai
git add backend/app/services/etl/nfl/recv_yds_model.py backend/tests/test_nfl_recv_yds_model.py
git commit -m "$(cat <<'EOF'
feat(nfl): receiving yards soft-anchor and non-ML model math

EOF
)"
```

---

### Task 2: SQLAlchemy models + Alembic migration

**Files:**
- Modify: `backend/app/models/predictions_models.py` (append after ATD models region / near QB models — place after `NFLAnytimeTDActuals`)
- Create: `backend/alembic/versions/2026_11_10_nfl_recv_yds.py`
- Create: `backend/tests/test_nfl_recv_yds_models_import.py`

**Interfaces:**
- Produces:
  - `RecvYdsPredictions` → table `pred_recv_yds_predictions`
  - `RecvYdsActuals` → table `pred_recv_yds_actuals`
  - UniqueConstraint `(season, week, player_id)` named `unique_nfl_recv_yds_prediction` / `unique_nfl_recv_yds_actual`
- Migration `revision = "20261110_nfl_recv_yds"`, `down_revision = "20260911_password_set"` (current dated tip on this branch; re-check `alembic heads` before implementing if main moved)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_nfl_recv_yds_models_import.py
from app.models.predictions_models import RecvYdsActuals, RecvYdsPredictions


def test_recv_yds_tablename_and_unique():
    assert RecvYdsPredictions.__tablename__ == "pred_recv_yds_predictions"
    assert RecvYdsActuals.__tablename__ == "pred_recv_yds_actuals"
    pred_cols = {c.name for c in RecvYdsPredictions.__table__.columns}
    for required in {
        "player_id",
        "player_name",
        "position",
        "team_name",
        "opponent_team_name",
        "season",
        "week",
        "game_date",
        "predicted_receiving_yards",
        "model_yards",
        "ou_line",
        "edge",
        "edge_percentage",
        "betting_recommendation",
        "confidence_score",
        "prediction_method",
        "features",
        "model_version",
    }:
        assert required in pred_cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_models_import.py -v`  
Expected: FAIL with `ImportError: cannot import name 'RecvYdsPredictions'`

- [ ] **Step 3: Add ORM models**

Append to `backend/app/models/predictions_models.py` (after `NFLAnytimeTDActuals`):

```python
class RecvYdsPredictions(Base):
    """Weekly receiving-yards board rows (lined RB/WR/TE only)."""

    __tablename__ = "pred_recv_yds_predictions"

    id = Column(Integer, primary_key=True)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    game_date = Column(Date, nullable=False)
    player_id = Column(String(20), nullable=False)
    player_name = Column(String(100), nullable=False)
    position = Column(String(10), nullable=False)  # RB / WR / TE
    team_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)

    predicted_receiving_yards = Column(Float, nullable=False)  # soft-anchored publish
    model_yards = Column(Float, nullable=True)  # pre-anchor non-ML yards
    ou_line = Column(Float, nullable=True)
    over_odds = Column(Integer, nullable=True)
    under_odds = Column(Integer, nullable=True)
    best_over_book = Column(String(50), nullable=True)
    best_under_book = Column(String(50), nullable=True)
    edge = Column(Float, nullable=True)  # publish − line
    edge_percentage = Column(Float, nullable=True)
    betting_recommendation = Column(String(20), nullable=True)  # OVER/UNDER/PASS
    bet_size = Column(String(10), nullable=True)
    recommendation_reason = Column(String(200), nullable=True)
    confidence_score = Column(Float, nullable=True)
    prediction_method = Column(String(50), nullable=True)  # soft_anchor
    features = Column(JSON, nullable=True)
    model_version = Column(String(64), nullable=True)
    prediction_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "season",
            "week",
            "player_id",
            name="unique_nfl_recv_yds_prediction",
        ),
        Index("idx_nfl_recv_yds_predictions_date", "game_date"),
        Index("idx_nfl_recv_yds_predictions_edge", "edge"),
        Index("idx_nfl_recv_yds_predictions_pos", "position"),
    )


class RecvYdsActuals(Base):
    """Post-week actual receiving yards for grading."""

    __tablename__ = "pred_recv_yds_actuals"

    id = Column(Integer, primary_key=True)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    game_date = Column(Date, nullable=False)
    player_id = Column(String(20), nullable=False)
    player_name = Column(String(100), nullable=False)
    position = Column(String(10), nullable=False)
    team_name = Column(String(100), nullable=False)
    opponent_team_name = Column(String(100), nullable=False)
    actual_receiving_yards = Column(Float, nullable=False)
    actual_receptions = Column(Integer, nullable=True)
    actual_targets = Column(Integer, nullable=True)
    predicted_receiving_yards = Column(Float, nullable=True)
    ou_line = Column(Float, nullable=True)
    prediction_error = Column(Float, nullable=True)
    hit_over_under = Column(Boolean, nullable=True)
    prediction_method = Column(String(50), nullable=True)
    data_collection_date = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "season",
            "week",
            "player_id",
            name="unique_nfl_recv_yds_actual",
        ),
        Index("idx_nfl_recv_yds_actuals_date", "game_date"),
    )
```

Ensure `Index` is already imported at the top of `predictions_models.py` (it is).

- [ ] **Step 4: Add Alembic migration**

```python
# backend/alembic/versions/2026_11_10_nfl_recv_yds.py
"""NFL receiving yards predictions + actuals tables."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261110_nfl_recv_yds"
down_revision: Union[str, None] = "20260911_password_set"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("pred_recv_yds_predictions"):
        op.create_table(
            "pred_recv_yds_predictions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("season", sa.Integer(), nullable=False),
            sa.Column("week", sa.Integer(), nullable=False),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("player_id", sa.String(20), nullable=False),
            sa.Column("player_name", sa.String(100), nullable=False),
            sa.Column("position", sa.String(10), nullable=False),
            sa.Column("team_name", sa.String(100), nullable=False),
            sa.Column("opponent_team_name", sa.String(100), nullable=False),
            sa.Column("predicted_receiving_yards", sa.Float(), nullable=False),
            sa.Column("model_yards", sa.Float(), nullable=True),
            sa.Column("ou_line", sa.Float(), nullable=True),
            sa.Column("over_odds", sa.Integer(), nullable=True),
            sa.Column("under_odds", sa.Integer(), nullable=True),
            sa.Column("best_over_book", sa.String(50), nullable=True),
            sa.Column("best_under_book", sa.String(50), nullable=True),
            sa.Column("edge", sa.Float(), nullable=True),
            sa.Column("edge_percentage", sa.Float(), nullable=True),
            sa.Column("betting_recommendation", sa.String(20), nullable=True),
            sa.Column("bet_size", sa.String(10), nullable=True),
            sa.Column("recommendation_reason", sa.String(200), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("prediction_method", sa.String(50), nullable=True),
            sa.Column("features", sa.JSON(), nullable=True),
            sa.Column("model_version", sa.String(64), nullable=True),
            sa.Column("prediction_date", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "season",
                "week",
                "player_id",
                name="unique_nfl_recv_yds_prediction",
            ),
        )
        op.create_index(
            "idx_nfl_recv_yds_predictions_date",
            "pred_recv_yds_predictions",
            ["game_date"],
        )
        op.create_index(
            "idx_nfl_recv_yds_predictions_edge",
            "pred_recv_yds_predictions",
            ["edge"],
        )
        op.create_index(
            "idx_nfl_recv_yds_predictions_pos",
            "pred_recv_yds_predictions",
            ["position"],
        )

    if not _has_table("pred_recv_yds_actuals"):
        op.create_table(
            "pred_recv_yds_actuals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("season", sa.Integer(), nullable=False),
            sa.Column("week", sa.Integer(), nullable=False),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("player_id", sa.String(20), nullable=False),
            sa.Column("player_name", sa.String(100), nullable=False),
            sa.Column("position", sa.String(10), nullable=False),
            sa.Column("team_name", sa.String(100), nullable=False),
            sa.Column("opponent_team_name", sa.String(100), nullable=False),
            sa.Column("actual_receiving_yards", sa.Float(), nullable=False),
            sa.Column("actual_receptions", sa.Integer(), nullable=True),
            sa.Column("actual_targets", sa.Integer(), nullable=True),
            sa.Column("predicted_receiving_yards", sa.Float(), nullable=True),
            sa.Column("ou_line", sa.Float(), nullable=True),
            sa.Column("prediction_error", sa.Float(), nullable=True),
            sa.Column("hit_over_under", sa.Boolean(), nullable=True),
            sa.Column("prediction_method", sa.String(50), nullable=True),
            sa.Column("data_collection_date", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "season",
                "week",
                "player_id",
                name="unique_nfl_recv_yds_actual",
            ),
        )
        op.create_index(
            "idx_nfl_recv_yds_actuals_date",
            "pred_recv_yds_actuals",
            ["game_date"],
        )


def downgrade() -> None:
    if _has_table("pred_recv_yds_actuals"):
        op.drop_table("pred_recv_yds_actuals")
    if _has_table("pred_recv_yds_predictions"):
        op.drop_table("pred_recv_yds_predictions")
```

- [ ] **Step 5: Run tests, black, commit**

```bash
cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_models_import.py -v
cd backend && python3 -m black app/models/predictions_models.py alembic/versions/2026_11_10_nfl_recv_yds.py tests/test_nfl_recv_yds_models_import.py
git add backend/app/models/predictions_models.py backend/alembic/versions/2026_11_10_nfl_recv_yds.py backend/tests/test_nfl_recv_yds_models_import.py
git commit -m "$(cat <<'EOF'
feat(nfl): receiving yards predictions and actuals tables

EOF
)"
```

Expected pytest: PASS

---

### Task 3: Feature builder (never invent targets)

**Files:**
- Create: `backend/app/services/etl/nfl/recv_yds_features.py`
- Create: `backend/tests/test_nfl_recv_yds_features.py`

**Interfaces:**
- Consumes: lined slate player dicts; usage priors (`target_share`, `team_pass_attempts`, `ypr`, optional `adot`, game total / implied pass volume, opponent recv yards allowed)
- Produces:
  - `SKILL_POSITIONS = frozenset({"RB", "WR", "TE"})`
  - `build_recv_feature_row(player: dict, *, game_env: dict | None = None, opponent_defense: dict | None = None) -> dict | None`
  - Returns `None` when position not skill, or when `expected_targets` / `ypr` cannot be computed honestly
  - Feature dict keys: `player_id`, `player_name`, `position`, `team_name`, `opponent_team_name`, `game_date`, `season`, `week`, `target_share`, `team_pass_attempts`, `expected_targets`, `ypr`, `depth_adj`, `pace_adj`, `matchup_adj`, `model_yards`, `confidence_score`, `features` (nested debug blob)
  - `confidence_score` ≤ `0.55` when only thin priors (e.g. missing depth/matchup); never fabricate `target_share` from `ou_line`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_nfl_recv_yds_features.py
from app.services.etl.nfl.recv_yds_features import build_recv_feature_row


def _base_player(**overrides):
    row = {
        "player_id": "00-0035676",
        "player_name": "A.J. Brown",
        "position": "WR",
        "team_name": "Philadelphia Eagles",
        "opponent_team_name": "Dallas Cowboys",
        "game_date": "2026-11-15",
        "season": 2026,
        "week": 11,
        "target_share": 0.28,
        "team_pass_attempts": 35.0,
        "ypr": 14.0,
        "adot": 11.0,
        "ou_line": 72.5,  # must NEVER be used as a target prior
    }
    row.update(overrides)
    return row


def test_build_recv_feature_row_computes_model_yards():
    out = build_recv_feature_row(_base_player())
    assert out is not None
    assert out["expected_targets"] == 0.28 * 35.0
    assert out["model_yards"] > 0
    assert out["position"] == "WR"
    assert "ou_line" not in (out.get("features") or {}) or out["features"].get(
        "targets_from_line"
    ) is not True


def test_build_recv_feature_row_skips_missing_targets():
    assert build_recv_feature_row(_base_player(target_share=None)) is None
    assert build_recv_feature_row(_base_player(team_pass_attempts=None)) is None


def test_build_recv_feature_row_skips_qb_and_unknown():
    assert build_recv_feature_row(_base_player(position="QB")) is None
    assert build_recv_feature_row(_base_player(position="UNK")) is None


def test_build_recv_feature_row_does_not_derive_targets_from_line():
    # Even with a fat line and missing share, skip — never invent.
    assert (
        build_recv_feature_row(_base_player(target_share=None, ou_line=120.5)) is None
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_features.py -v`  
Expected: FAIL import `recv_yds_features`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/etl/nfl/recv_yds_features.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_features.py tests/test_nfl_recv_yds_model.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && python3 -m black app/services/etl/nfl/recv_yds_features.py tests/test_nfl_recv_yds_features.py
git add backend/app/services/etl/nfl/recv_yds_features.py backend/tests/test_nfl_recv_yds_features.py
git commit -m "$(cat <<'EOF'
feat(nfl): receiving yards feature builder without invented targets

EOF
)"
```

---

### Task 4: Betting helpers — slate, fail-closed, edge/pick

**Files:**
- Create: `backend/app/services/etl/nfl/recv_yds_betting.py`
- Create: `backend/tests/test_nfl_recv_yds_betting.py`

**Interfaces:**
- Consumes: Odds API via `sync_odds_get` (same pattern as `qb_betting.py`); `soft_anchor_recv_yards` / `published_recv_yards`
- Produces:
  - `RECV_YDS_MARKET = "player_reception_yds"`
  - `normalize_player_name(name: str) -> str`
  - `get_best_line(player_lines: dict) -> dict`  # `{over, under}` with line/odds/book
  - `clear_betting_fields() -> dict`  # nulls ou_line, odds, edge, pick (ATD-style fail-closed)
  - `generate_betting_recommendation(prediction, ou_line, confidence) -> dict`  # QB thresholds, no classifier
  - `attach_recv_betting(*, model_yards, confidence_score, player_lines) -> dict | None`  # None if no real line
  - `fetch_reception_yds_lines() -> dict[str, dict]`  # name → bookmaker lines (empty on miss/off-season)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_nfl_recv_yds_betting.py
from app.services.etl.nfl.recv_yds_betting import (
    RECV_YDS_MARKET,
    attach_recv_betting,
    clear_betting_fields,
    generate_betting_recommendation,
    get_best_line,
    normalize_player_name,
)


def test_market_key_is_reception_yds():
    assert RECV_YDS_MARKET == "player_reception_yds"


def test_normalize_player_name_aliases():
    assert normalize_player_name("AJ Brown") == "A.J. Brown"


def test_clear_betting_fields_nulls_market_columns():
    cleared = clear_betting_fields()
    assert cleared["ou_line"] is None
    assert cleared["edge"] is None
    assert cleared["edge_percentage"] is None
    assert cleared["betting_recommendation"] is None
    assert cleared["over_odds"] is None
    assert cleared["under_odds"] is None


def test_generate_recommendation_pass_on_thin_edge():
    rec = generate_betting_recommendation(prediction=85.0, ou_line=80.0, confidence=0.72)
    # edge = 5 yards → 6.25% < 7% → PASS
    assert rec["recommendation"] == "PASS"


def test_generate_recommendation_over_on_strong_edge():
    rec = generate_betting_recommendation(prediction=92.0, ou_line=80.0, confidence=0.80)
    # 15% edge → OVER LARGE
    assert rec["recommendation"] == "OVER"
    assert rec["bet_size"] == "LARGE"


def test_attach_recv_betting_fail_closed_without_line():
    assert attach_recv_betting(model_yards=70.0, confidence_score=0.72, player_lines={}) is None


def test_attach_recv_betting_soft_anchors_and_sets_edge():
    lines = {
        "FanDuel": {
            "over": {"line": 80.0, "odds": -110},
            "under": {"line": 80.0, "odds": -110},
        }
    }
    out = attach_recv_betting(
        model_yards=100.0, confidence_score=0.80, player_lines=lines, anchor_alpha=0.25
    )
    assert out is not None
    assert out["ou_line"] == 80.0
    assert out["predicted_receiving_yards"] == 85.0
    assert out["prediction_method"] == "soft_anchor"
    assert out["edge"] == 5.0
    assert out["predicted_receiving_yards"] != out["ou_line"]


def test_get_best_line_picks_books():
    best = get_best_line(
        {
            "FanDuel": {
                "over": {"line": 70.5, "odds": -115},
                "under": {"line": 70.5, "odds": -105},
            },
            "DraftKings": {
                "over": {"line": 71.5, "odds": -110},
                "under": {"line": 71.5, "odds": -110},
            },
        }
    )
    assert best["over"]["line"] == 71.5
    assert best["under"]["line"] == 70.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_betting.py -v`  
Expected: FAIL import

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/etl/nfl/recv_yds_betting.py
"""Odds attach for NFL receiving yards (`player_reception_yds`) — fail-closed."""

from __future__ import annotations

import os
from typing import Any

from app.services.etl.nfl.recv_yds_model import published_recv_yards

RECV_YDS_MARKET = "player_reception_yds"
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4/sports/"
SPORT = "americanfootball_nfl"

# Mirror qb_betting.generate_betting_recommendation thresholds (no O/U classifier).
MIN_EDGE = 7.0
MIN_CONFIDENCE = 0.70
STRONG_EDGE = 12.0
STRONG_CONFIDENCE = 0.75


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


def get_best_line(player_lines: dict) -> dict:
    best_over = {"line": 0, "odds": -110, "book": "N/A"}
    best_under = {"line": 999, "odds": -110, "book": "N/A"}
    for bookmaker, lines in player_lines.items():
        if "over" in lines:
            over_line = lines["over"]
            if over_line["line"] > best_over["line"] or (
                over_line["line"] == best_over["line"]
                and over_line["odds"] > best_over["odds"]
            ):
                best_over = {
                    "line": over_line["line"],
                    "odds": over_line["odds"],
                    "book": bookmaker,
                }
        if "under" in lines:
            under_line = lines["under"]
            if under_line["line"] < best_under["line"] or (
                under_line["line"] == best_under["line"]
                and under_line["odds"] > best_under["odds"]
            ):
                best_under = {
                    "line": under_line["line"],
                    "odds": under_line["odds"],
                    "book": bookmaker,
                }
    return {"over": best_over, "under": best_under}


def clear_betting_fields() -> dict[str, Any]:
    """Null betting columns when Odds attach fails or a row is unmatched."""
    return {
        "ou_line": None,
        "over_odds": None,
        "under_odds": None,
        "best_over_book": None,
        "best_under_book": None,
        "edge": None,
        "edge_percentage": None,
        "betting_recommendation": None,
        "bet_size": None,
        "recommendation_reason": None,
    }


def generate_betting_recommendation(
    prediction: float,
    ou_line: float,
    confidence: float,
) -> dict[str, Any]:
    edge = prediction - ou_line
    edge_percentage = (edge / ou_line) * 100 if ou_line > 0 else 0.0

    if confidence < MIN_CONFIDENCE:
        return {
            "recommendation": "PASS",
            "reason": f"Low confidence ({confidence:.1%})",
            "edge_percentage": edge_percentage,
            "bet_size": None,
        }
    if abs(edge_percentage) < MIN_EDGE:
        return {
            "recommendation": "PASS",
            "reason": f"Insufficient edge ({edge_percentage:.1f}%)",
            "edge_percentage": edge_percentage,
            "bet_size": None,
        }
    if edge_percentage >= MIN_EDGE:
        bet_type = "OVER"
        if edge_percentage >= STRONG_EDGE and confidence >= STRONG_CONFIDENCE:
            bet_size = "LARGE"
            reason = (
                f"Strong edge ({edge_percentage:.1f}%) + "
                f"High confidence ({confidence:.1%})"
            )
        else:
            bet_size = "MEDIUM"
            reason = f"Good edge ({edge_percentage:.1f}%)"
    else:
        bet_type = "UNDER"
        if abs(edge_percentage) >= STRONG_EDGE and confidence >= STRONG_CONFIDENCE:
            bet_size = "LARGE"
            reason = (
                f"Strong edge ({abs(edge_percentage):.1f}%) + "
                f"High confidence ({confidence:.1%})"
            )
        else:
            bet_size = "MEDIUM"
            reason = f"Good edge ({abs(edge_percentage):.1f}%)"
    return {
        "recommendation": bet_type,
        "reason": reason,
        "edge_percentage": edge_percentage,
        "bet_size": bet_size,
    }


def attach_recv_betting(
    *,
    model_yards: float,
    confidence_score: float,
    player_lines: dict,
    anchor_alpha: float | None = None,
) -> dict[str, Any] | None:
    """Soft-anchor + edge/pick when a real reception-yards line exists; else None."""
    if not player_lines:
        return None
    best = get_best_line(player_lines)
    ou_line = float(best["over"]["line"] or 0)
    if ou_line <= 0:
        return None
    published, method = published_recv_yards(
        model_yards=float(model_yards),
        ou_line=ou_line,
        line_is_real=True,
        anchor_alpha=anchor_alpha,
    )
    if published is None or method is None:
        return None
    rec = generate_betting_recommendation(
        prediction=published,
        ou_line=ou_line,
        confidence=float(confidence_score),
    )
    return {
        "predicted_receiving_yards": published,
        "model_yards": float(model_yards),
        "prediction_method": method,
        "ou_line": ou_line,
        "over_odds": best["over"]["odds"],
        "under_odds": best["under"]["odds"],
        "best_over_book": best["over"]["book"],
        "best_under_book": best["under"]["book"],
        "edge": published - ou_line,
        "edge_percentage": rec["edge_percentage"],
        "betting_recommendation": rec["recommendation"],
        "bet_size": rec["bet_size"],
        "recommendation_reason": rec["reason"],
        "confidence_score": float(confidence_score),
    }


def fetch_reception_yds_lines() -> dict[str, dict]:
    """Fetch week slate of `player_reception_yds` keyed by Odds player description.

    Fail-closed: any HTTP/off-season/budget miss returns ``{}`` (no invented lines).
    """
    from app.services.odds_api_service import sport_in_season
    from app.services.odds_api_sync import sync_odds_get

    if not sport_in_season(SPORT):
        return {}
    try:
        url = f"{BASE_URL}{SPORT}/events"
        response = sync_odds_get(
            url,
            params={"apiKey": ODDS_API_KEY, "dateFormat": "iso"},
            caller="etl.nfl.recv_yds_betting.events",
            raise_for_status=False,
        )
        if response is None or response.status_code != 200:
            return {}
        games = response.json()
        all_lines: dict[str, dict] = {}
        for game in games:
            event_id = game["id"]
            odds_response = sync_odds_get(
                f"{BASE_URL}{SPORT}/events/{event_id}/odds",
                params={
                    "apiKey": ODDS_API_KEY,
                    "regions": "us",
                    "markets": RECV_YDS_MARKET,
                    "oddsFormat": "american",
                    "bookmakers": "fanduel,draftkings,betmgm",
                },
                caller=f"etl.nfl.recv_yds_betting.odds.{event_id}",
                raise_for_status=False,
            )
            if odds_response is None or odds_response.status_code != 200:
                continue
            odds_data = odds_response.json()
            for bookmaker in odds_data.get("bookmakers", []):
                bookmaker_name = bookmaker["title"]
                for market in bookmaker.get("markets", []):
                    if market["key"] != RECV_YDS_MARKET:
                        continue
                    for outcome in market["outcomes"]:
                        player_name = outcome["description"]
                        bet_type = outcome["name"]
                        line = outcome.get("point", 0)
                        odds = outcome.get("price", 0)
                        all_lines.setdefault(player_name, {})
                        all_lines[player_name].setdefault(bookmaker_name, {})
                        all_lines[player_name][bookmaker_name][bet_type.lower()] = {
                            "line": line,
                            "odds": odds,
                        }
        return all_lines
    except Exception:
        return {}


def match_player_lines(player_name: str, all_lines: dict[str, dict]) -> dict | None:
    normalized = normalize_player_name(player_name)
    for line_player_name, lines in all_lines.items():
        if (
            normalized.lower() in line_player_name.lower()
            or line_player_name.lower() in normalized.lower()
        ):
            return lines
    return None
```

- [ ] **Step 4: Run tests**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_betting.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && python3 -m black app/services/etl/nfl/recv_yds_betting.py tests/test_nfl_recv_yds_betting.py
git add backend/app/services/etl/nfl/recv_yds_betting.py backend/tests/test_nfl_recv_yds_betting.py
git commit -m "$(cat <<'EOF'
feat(nfl): receiving yards Odds attach helpers fail-closed

EOF
)"
```

---

### Task 5: Projector upsert + weekly chain

**Files:**
- Create: `backend/app/services/etl/nfl/recv_yds_projector.py`
- Create: `backend/app/services/etl/nfl/recv_yds_weekly.py`
- Create: `backend/tests/test_nfl_recv_yds_projector.py`

**Interfaces:**
- Consumes: feature rows + matched Odds lines; `RecvYdsPredictions`; `attach_recv_betting`
- Produces:
  - `upsert_recv_prediction(session, row: dict) -> RecvYdsPredictions`
  - `project_lined_players(session, feature_rows: list[dict], all_lines: dict) -> dict` with keys `upserted`, `skipped_no_line`, `skipped_no_publish`
  - `run()` on weekly module: fetch lines → (caller supplies feature assembly in full ETL; for unit tests inject) → project
  - Lined-only: **no row written** without a real attached line + soft-anchored publish

Full production feature assembly (nflverse weekly + ATD snaps/target_share + `pred_nfl_game_lines`) lives in `recv_yds_projector.load_usage_priors_for_slate` — implement with the same nflverse patterns as `anytime_td_features.py` / fantasy analytics (`target_share`, receiving YPR). Unit tests mock this loader.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_nfl_recv_yds_projector.py
from types import SimpleNamespace

from app.services.etl.nfl.recv_yds_projector import project_lined_players


class _FakeQuery:
    def __init__(self, existing=None):
        self._existing = existing

    def filter_by(self, **kwargs):
        return self

    def one_or_none(self):
        return self._existing


class _FakeSession:
    def __init__(self):
        self.added = []
        self._existing = None

    def query(self, model):
        return _FakeQuery(self._existing)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None


def test_project_lined_players_skips_without_odds_match():
    session = _FakeSession()
    feature_rows = [
        {
            "player_id": "1",
            "player_name": "A.J. Brown",
            "position": "WR",
            "team_name": "Philadelphia Eagles",
            "opponent_team_name": "Dallas Cowboys",
            "game_date": "2026-11-15",
            "season": 2026,
            "week": 11,
            "model_yards": 100.0,
            "confidence_score": 0.8,
            "features": {},
            "model_version": "recv_nonml_v1",
        }
    ]
    stats = project_lined_players(session, feature_rows, all_lines={})
    assert stats["upserted"] == 0
    assert stats["skipped_no_line"] == 1
    assert session.added == []


def test_project_lined_players_upserts_soft_anchored_row():
    session = _FakeSession()
    feature_rows = [
        {
            "player_id": "1",
            "player_name": "A.J. Brown",
            "position": "WR",
            "team_name": "Philadelphia Eagles",
            "opponent_team_name": "Dallas Cowboys",
            "game_date": "2026-11-15",
            "season": 2026,
            "week": 11,
            "model_yards": 100.0,
            "confidence_score": 0.8,
            "features": {"target_share": 0.28},
            "model_version": "recv_nonml_v1",
        }
    ]
    all_lines = {
        "A.J. Brown": {
            "FanDuel": {
                "over": {"line": 80.0, "odds": -110},
                "under": {"line": 80.0, "odds": -110},
            }
        }
    }
    stats = project_lined_players(
        session, feature_rows, all_lines=all_lines, anchor_alpha=0.25
    )
    assert stats["upserted"] == 1
    assert len(session.added) == 1
    row = session.added[0]
    assert row.predicted_receiving_yards == 85.0
    assert row.ou_line == 80.0
    assert row.prediction_method == "soft_anchor"
    assert row.position == "WR"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_projector.py -v`  
Expected: FAIL import

- [ ] **Step 3: Implement projector + weekly chain**

```python
# backend/app/services/etl/nfl/recv_yds_projector.py
"""Upsert lined receiving-yards board rows (soft-anchored)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.models.predictions_models import RecvYdsPredictions
from app.services.etl.nfl.recv_yds_betting import (
    attach_recv_betting,
    match_player_lines,
)


def _as_game_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def upsert_recv_prediction(session, payload: dict[str, Any]) -> RecvYdsPredictions:
    existing = (
        session.query(RecvYdsPredictions)
        .filter_by(
            season=payload["season"],
            week=payload["week"],
            player_id=payload["player_id"],
        )
        .one_or_none()
    )
    if existing is None:
        existing = RecvYdsPredictions(
            season=payload["season"],
            week=payload["week"],
            player_id=payload["player_id"],
            game_date=_as_game_date(payload["game_date"]),
            player_name=payload["player_name"],
            position=payload["position"],
            team_name=payload["team_name"],
            opponent_team_name=payload["opponent_team_name"],
            predicted_receiving_yards=payload["predicted_receiving_yards"],
            prediction_date=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        session.add(existing)
    for key, value in payload.items():
        if key == "game_date":
            setattr(existing, key, _as_game_date(value))
        elif hasattr(existing, key):
            setattr(existing, key, value)
    session.flush()
    return existing


def project_lined_players(
    session,
    feature_rows: list[dict[str, Any]],
    all_lines: dict[str, dict],
    *,
    anchor_alpha: float | None = None,
) -> dict[str, int]:
    stats = {"upserted": 0, "skipped_no_line": 0, "skipped_no_publish": 0}
    for feat in feature_rows:
        lines = match_player_lines(feat["player_name"], all_lines)
        if not lines:
            stats["skipped_no_line"] += 1
            continue
        attached = attach_recv_betting(
            model_yards=float(feat["model_yards"]),
            confidence_score=float(feat["confidence_score"]),
            player_lines=lines,
            anchor_alpha=anchor_alpha,
        )
        if attached is None:
            stats["skipped_no_publish"] += 1
            continue
        payload = {
            "season": feat["season"],
            "week": feat["week"],
            "game_date": feat["game_date"],
            "player_id": feat["player_id"],
            "player_name": feat["player_name"],
            "position": feat["position"],
            "team_name": feat["team_name"],
            "opponent_team_name": feat["opponent_team_name"],
            "features": feat.get("features"),
            "model_version": feat.get("model_version"),
            **attached,
        }
        upsert_recv_prediction(session, payload)
        stats["upserted"] += 1
    return stats
```

```python
# backend/app/services/etl/nfl/recv_yds_weekly.py
"""Weekly receiving-yards chain: Odds slate → features → soft-anchor upsert."""

from __future__ import annotations

from typing import Any, Callable


def _run_core(
    session,
    *,
    fetch_lines: Callable[[], dict[str, dict]],
    load_priors: Callable[[list[str]], list[dict[str, Any]]],
) -> dict[str, Any]:
    from app.services.etl.nfl.recv_yds_features import build_recv_feature_row
    from app.services.etl.nfl.recv_yds_projector import project_lined_players

    all_lines = fetch_lines()
    if not all_lines:
        return {
            "status": "ok",
            "task": "nfl_recv_yds_weekly",
            "upserted": 0,
            "note": "no_reception_yds_lines",
        }
    prior_rows = load_priors(list(all_lines.keys()))
    feature_rows = []
    for prior in prior_rows:
        feat = build_recv_feature_row(
            prior,
            game_env=prior.get("game_env"),
            opponent_defense=prior.get("opponent_defense"),
        )
        if feat is not None:
            feature_rows.append(feat)
    stats = project_lined_players(session, feature_rows, all_lines)
    session.commit()
    return {"status": "ok", "task": "nfl_recv_yds_weekly", **stats}


def run() -> dict:
    from app.services.etl.nfl._db import close_session, db_session, init_session
    from app.services.etl.nfl.recv_yds_betting import fetch_reception_yds_lines
    from app.services.etl.nfl.recv_yds_usage import load_usage_priors_for_names

    init_session()
    try:
        return _run_core(
            db_session(),
            fetch_lines=fetch_reception_yds_lines,
            load_priors=load_usage_priors_for_names,
        )
    finally:
        close_session()
```

Also create `backend/app/services/etl/nfl/recv_yds_usage.py` with `load_usage_priors_for_names(names: list[str]) -> list[dict]`:

```python
# backend/app/services/etl/nfl/recv_yds_usage.py
"""Join Odds-lined receiver names to nflverse / ATD-adjacent usage priors."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from app.services.etl.nfl.nfl_common import get_current_nfl_week, get_nfl_season
from app.services.etl.nfl.recv_yds_betting import normalize_player_name
from app.services.etl.nfl.recv_yds_features import SKILL_POSITIONS


def _name_key(name: str) -> str:
    return normalize_player_name(name).strip().lower()


def _ypr(receiving_yards: float, receptions: float) -> float | None:
    if receptions is None or float(receptions) <= 0:
        return None
    return float(receiving_yards) / float(receptions)


def select_usage_priors_for_names(
    player_names: list[str],
    weekly_rows: list[dict[str, Any]],
    *,
    season: int,
    week: int,
    game_date: date | str,
    schedule_by_team: dict[str, dict[str, Any]] | None = None,
    game_env_by_team: dict[str, dict[str, Any]] | None = None,
    defense_by_team: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Pure join used by unit tests — never invents ``target_share`` from a line."""
    wanted = {_name_key(n) for n in player_names}
    schedule_by_team = schedule_by_team or {}
    game_env_by_team = game_env_by_team or {}
    defense_by_team = defense_by_team or {}
    out: list[dict[str, Any]] = []
    for row in weekly_rows:
        pos = str(row.get("position") or "").upper()
        if pos not in SKILL_POSITIONS:
            continue
        pname = str(row.get("player_name") or row.get("player_display_name") or "")
        if _name_key(pname) not in wanted:
            continue
        share = row.get("target_share")
        attempts = row.get("team_pass_attempts")
        if share is None and row.get("targets") is not None and attempts:
            # Honest derive from counted targets / team attempts only — not from O/U.
            try:
                share = float(row["targets"]) / float(attempts)
            except (TypeError, ValueError, ZeroDivisionError):
                share = None
        ypr = row.get("ypr")
        if ypr is None:
            ypr = _ypr(row.get("receiving_yards") or 0.0, row.get("receptions") or 0.0)
        if share is None or attempts is None or ypr is None:
            continue
        team = row.get("team_name") or row.get("recent_team") or row.get("team")
        sched = schedule_by_team.get(str(team), {})
        opponent = sched.get("opponent_team_name") or row.get("opponent_team_name")
        if not team or not opponent:
            continue
        out.append(
            {
                "player_id": str(row.get("player_id") or row.get("gsis_id")),
                "player_name": pname,
                "position": pos,
                "team_name": team,
                "opponent_team_name": opponent,
                "game_date": sched.get("game_date", game_date),
                "season": season,
                "week": week,
                "target_share": float(share),
                "team_pass_attempts": float(attempts),
                "ypr": float(ypr),
                "adot": row.get("adot") or row.get("avg_air_yards"),
                "snap_pct": row.get("snap_pct") or row.get("offense_pct"),
                "game_env": game_env_by_team.get(str(team)),
                "opponent_defense": defense_by_team.get(str(opponent)),
            }
        )
    return out


def load_weekly_receiver_rows(season: int) -> list[dict[str, Any]]:
    """Load nflverse weekly rows; prefer ATD weekly loader when available."""
    try:
        from app.services.etl.nfl.anytime_td_features import (
            load_weekly_records_for_season,
        )

        return load_weekly_records_for_season(int(season))
    except Exception:
        import nfl_data_py as nfl

        frame = nfl.import_weekly_data([int(season)])
        return frame.to_dict(orient="records")


def load_usage_priors_for_names(player_names: list[str]) -> list[dict[str, Any]]:
    """Return skill-position usage dicts for soft-name matches in ``player_names``."""
    season = int(get_nfl_season())
    week = int(get_current_nfl_week())
    weekly = load_weekly_receiver_rows(season)
    # Optional enrichment: snaps / game lines can be joined here the same way ATD does.
    return select_usage_priors_for_names(
        player_names,
        weekly,
        season=season,
        week=week,
        game_date=date.today().isoformat(),
    )
```

Also create `backend/tests/test_nfl_recv_yds_usage.py`:

```python
from app.services.etl.nfl.recv_yds_usage import select_usage_priors_for_names


def test_select_usage_skips_missing_share_and_never_uses_line():
    rows = select_usage_priors_for_names(
        ["A.J. Brown"],
        [
            {
                "player_id": "1",
                "player_name": "A.J. Brown",
                "position": "WR",
                "team_name": "Philadelphia Eagles",
                "opponent_team_name": "Dallas Cowboys",
                "target_share": None,
                "team_pass_attempts": 35.0,
                "ypr": 14.0,
                "ou_line": 120.5,  # must be ignored
            }
        ],
        season=2026,
        week=11,
        game_date="2026-11-15",
        schedule_by_team={
            "Philadelphia Eagles": {
                "opponent_team_name": "Dallas Cowboys",
                "game_date": "2026-11-15",
            }
        },
    )
    assert rows == []


def test_select_usage_matches_normalized_name():
    rows = select_usage_priors_for_names(
        ["AJ Brown"],
        [
            {
                "player_id": "1",
                "player_name": "A.J. Brown",
                "position": "WR",
                "team_name": "Philadelphia Eagles",
                "target_share": 0.28,
                "team_pass_attempts": 35.0,
                "receptions": 5,
                "receiving_yards": 70,
            }
        ],
        season=2026,
        week=11,
        game_date="2026-11-15",
        schedule_by_team={
            "Philadelphia Eagles": {
                "opponent_team_name": "Dallas Cowboys",
                "game_date": "2026-11-15",
            }
        },
    )
    assert len(rows) == 1
    assert rows[0]["target_share"] == 0.28
    assert rows[0]["ypr"] == 14.0
```

- [ ] **Step 4: Run projector tests**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_projector.py -v`  
Expected: PASS (usage NotImplemented is OK until wired; weekly `run()` integration test should mock `load_usage_priors_for_names`)

Add `backend/tests/test_nfl_recv_yds_weekly.py`:

```python
from app.services.etl.nfl.recv_yds_weekly import _run_core


class _FakeSession:
    def __init__(self):
        self.added = []
        self.committed = False

    def query(self, model):
        class Q:
            def filter_by(self, **kw):
                return self

            def one_or_none(self):
                return None

        return Q()

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None

    def commit(self):
        self.committed = True


def test_run_core_upserts_lined_soft_anchor():
    session = _FakeSession()
    result = _run_core(
        session,
        fetch_lines=lambda: {
            "A.J. Brown": {
                "FanDuel": {
                    "over": {"line": 80.0, "odds": -110},
                    "under": {"line": 80.0, "odds": -110},
                }
            }
        },
        load_priors=lambda names: [
            {
                "player_id": "1",
                "player_name": "A.J. Brown",
                "position": "WR",
                "team_name": "Philadelphia Eagles",
                "opponent_team_name": "Dallas Cowboys",
                "game_date": "2026-11-15",
                "season": 2026,
                "week": 11,
                "target_share": 0.28,
                "team_pass_attempts": 35.0,
                "ypr": 14.0,
                "adot": 11.0,
                "snap_pct": 0.9,
                "game_env": {"implied_team_pass_attempts": 36.0},
                "opponent_defense": {"wr_recv_yards_index": 1.05},
            }
        ],
    )
    assert result["upserted"] == 1
    assert session.committed is True
    assert session.added[0].prediction_method == "soft_anchor"
    assert session.added[0].predicted_receiving_yards != session.added[0].ou_line
```

- [ ] **Step 5: Commit**

```bash
cd backend && python3 -m black app/services/etl/nfl/recv_yds_projector.py app/services/etl/nfl/recv_yds_weekly.py app/services/etl/nfl/recv_yds_usage.py tests/test_nfl_recv_yds_projector.py tests/test_nfl_recv_yds_usage.py tests/test_nfl_recv_yds_weekly.py
git add backend/app/services/etl/nfl/recv_yds_projector.py backend/app/services/etl/nfl/recv_yds_weekly.py backend/app/services/etl/nfl/recv_yds_usage.py backend/tests/test_nfl_recv_yds_projector.py backend/tests/test_nfl_recv_yds_usage.py backend/tests/test_nfl_recv_yds_weekly.py
git commit -m "$(cat <<'EOF'
feat(nfl): receiving yards projector and weekly chain

EOF
)"
```

---

### Task 6: Celery leaf + Odds fallback market + actuals stub

**Files:**
- Modify: `backend/app/tasks/etl_pipeline.py`
- Modify: `backend/app/services/player_props_service.py` (`FALLBACK_PLAYER_PROP_MARKETS` NFL list)
- Create: `backend/app/services/etl/nfl/collect_recv_yds_actuals.py`
- Create: `backend/tests/test_nfl_recv_yds_celery_catalog.py`
- Create: `backend/tests/test_nfl_recv_yds_fallback_markets.py`

**Interfaces:**
- Produces Celery tasks:
  - `app.tasks.etl_pipeline.nfl.recv_yds_weekly` → `recv_yds_weekly.run`
  - `app.tasks.etl_pipeline.nfl.collect_recv_yds_actuals` → `collect_recv_yds_actuals.run`
- Insert `nfl_recv_yds_weekly` into `NFL_PHASES` **predictions** list (after `nfl_kickers`) and into gameday predictions phase
- Insert `nfl_collect_recv_yds_actuals` into **actuals** phase
- Fallback markets include `player_reception_yds`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_nfl_recv_yds_fallback_markets.py
from app.services.player_props_service import FALLBACK_PLAYER_PROP_MARKETS


def test_nfl_fallback_includes_reception_yds():
    assert "player_reception_yds" in FALLBACK_PLAYER_PROP_MARKETS["americanfootball_nfl"]
```

```python
# backend/tests/test_nfl_recv_yds_celery_catalog.py
from app.tasks import etl_pipeline


def test_recv_yds_weekly_task_registered():
    assert hasattr(etl_pipeline, "nfl_recv_yds_weekly")
    assert etl_pipeline.nfl_recv_yds_weekly.name == (
        "app.tasks.etl_pipeline.nfl.recv_yds_weekly"
    )


def test_recv_yds_in_nfl_phases_predictions_and_actuals():
    phases = {name: tasks for name, tasks in etl_pipeline.NFL_PHASES}
    pred_names = [t.name for t in phases["predictions"]]
    actual_names = [t.name for t in phases["actuals"]]
    assert "app.tasks.etl_pipeline.nfl.recv_yds_weekly" in pred_names
    assert "app.tasks.etl_pipeline.nfl.collect_recv_yds_actuals" in actual_names
    # After kickers in predictions:
    assert pred_names.index("app.tasks.etl_pipeline.nfl.recv_yds_weekly") > pred_names.index(
        "app.tasks.etl_pipeline.nfl.kickers"
    )


def test_recv_yds_in_gameday_predictions():
    phases = {name: tasks for name, tasks in etl_pipeline.NFL_GAMEDAY_AVAILABILITY_PHASES}
    names = [t.name for t in phases["predictions"]]
    assert "app.tasks.etl_pipeline.nfl.recv_yds_weekly" in names
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Wire Celery + fallback + actuals collector**

In `player_props_service.py` NFL fallback list, add `"player_reception_yds"` after `"player_receptions"`:

```python
    "americanfootball_nfl": [
        "player_pass_yds",
        "player_pass_tds",
        "player_rush_yds",
        "player_receptions",
        "player_reception_yds",
        "player_anytime_td",
    ],
```

Add tasks near QB weekly (after `nfl_kickers` task definition):

```python
@celery_app.task(name="app.tasks.etl_pipeline.nfl.recv_yds_weekly")
def nfl_recv_yds_weekly():
    from app.services.etl.nfl.recv_yds_weekly import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.collect_recv_yds_actuals")
def nfl_collect_recv_yds_actuals():
    from app.services.etl.nfl.collect_recv_yds_actuals import run

    return run()
```

Wire phases exactly (edit the existing lists in place):

```python
NFL_PHASES = [
    (
        "actuals",
        [
            nfl_collect_qb_actuals,
            nfl_collect_kicker_actuals,
            nfl_store_game_actuals,
            nfl_anytime_td_actuals,
            nfl_collect_recv_yds_actuals,
        ],
    ),
    (
        "game_lines",
        [
            nfl_update_game_lines,
        ],
    ),
    (
        "predictions",
        [
            nfl_yetiwatch,
            nfl_qb_weekly,
            nfl_kickers,
            nfl_recv_yds_weekly,
        ],
    ),
    # ... game_projections and anytime_td unchanged ...
]

NFL_GAMEDAY_AVAILABILITY_PHASES = [
    (
        "predictions",
        [
            nfl_qb_weekly,
            nfl_kickers,
            nfl_recv_yds_weekly,
        ],
    ),
    # ... game_projections and anytime_td unchanged ...
]
```

```python
# backend/app/services/etl/nfl/collect_recv_yds_actuals.py
"""Grade receiving yards actuals into pred_recv_yds_actuals."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def grade_recv_row(
    *,
    actual_yards: float,
    predicted: float | None,
    ou_line: float | None,
) -> dict[str, Any]:
    err = None if predicted is None else float(actual_yards) - float(predicted)
    hit = None if ou_line is None else float(actual_yards) > float(ou_line)
    return {
        "actual_receiving_yards": float(actual_yards),
        "prediction_error": err,
        "hit_over_under": hit,
    }


def upsert_recv_actual(session, payload: dict[str, Any]):
    from app.models.predictions_models import RecvYdsActuals

    existing = (
        session.query(RecvYdsActuals)
        .filter_by(
            season=payload["season"],
            week=payload["week"],
            player_id=payload["player_id"],
        )
        .one_or_none()
    )
    if existing is None:
        existing = RecvYdsActuals(
            season=payload["season"],
            week=payload["week"],
            player_id=payload["player_id"],
            game_date=payload["game_date"],
            player_name=payload["player_name"],
            position=payload["position"],
            team_name=payload["team_name"],
            opponent_team_name=payload["opponent_team_name"],
            actual_receiving_yards=payload["actual_receiving_yards"],
            data_collection_date=datetime.utcnow(),
        )
        session.add(existing)
    for key, value in payload.items():
        if hasattr(existing, key):
            setattr(existing, key, value)
    return existing


def collect_for_week(session, *, season: int, week: int, weekly_stats: list[dict]) -> int:
    """Match prediction rows to weekly receiving yards and upsert actuals."""
    from app.models.predictions_models import RecvYdsPredictions

    preds = (
        session.query(RecvYdsPredictions)
        .filter_by(season=season, week=week)
        .all()
    )
    by_id = {str(r.get("player_id")): r for r in weekly_stats}
    upserted = 0
    for pred in preds:
        stat = by_id.get(str(pred.player_id))
        if not stat or stat.get("receiving_yards") is None:
            continue
        graded = grade_recv_row(
            actual_yards=float(stat["receiving_yards"]),
            predicted=pred.predicted_receiving_yards,
            ou_line=pred.ou_line,
        )
        upsert_recv_actual(
            session,
            {
                "season": season,
                "week": week,
                "game_date": pred.game_date,
                "player_id": pred.player_id,
                "player_name": pred.player_name,
                "position": pred.position,
                "team_name": pred.team_name,
                "opponent_team_name": pred.opponent_team_name,
                "actual_receptions": stat.get("receptions"),
                "actual_targets": stat.get("targets"),
                "predicted_receiving_yards": pred.predicted_receiving_yards,
                "ou_line": pred.ou_line,
                "prediction_method": pred.prediction_method,
                **graded,
            },
        )
        upserted += 1
    return upserted


def run() -> dict:
    from app.services.etl.nfl._db import close_session, db_session, init_session
    from app.services.etl.nfl.nfl_common import get_current_nfl_week, get_nfl_season
    from app.services.etl.nfl.recv_yds_usage import load_weekly_receiver_rows

    init_session()
    try:
        season = int(get_nfl_season())
        # Grade the previous completed week by default (mirror QB actuals cadence).
        week = max(1, int(get_current_nfl_week()) - 1)
        weekly = [
            r
            for r in load_weekly_receiver_rows(season)
            if int(r.get("week") or 0) == week
        ]
        n = collect_for_week(db_session(), season=season, week=week, weekly_stats=weekly)
        db_session().commit()
        return {
            "status": "ok",
            "task": "nfl_collect_recv_yds_actuals",
            "upserted": n,
            "season": season,
            "week": week,
        }
    finally:
        close_session()
```

Add `backend/tests/test_nfl_recv_yds_actuals.py`:

```python
from app.services.etl.nfl.collect_recv_yds_actuals import grade_recv_row


def test_grade_recv_row_error_and_ou_hit():
    out = grade_recv_row(actual_yards=90.0, predicted=85.0, ou_line=80.0)
    assert out["prediction_error"] == 5.0
    assert out["hit_over_under"] is True


def test_grade_recv_row_null_line():
    out = grade_recv_row(actual_yards=90.0, predicted=85.0, ou_line=None)
    assert out["hit_over_under"] is None
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_fallback_markets.py tests/test_nfl_recv_yds_celery_catalog.py -v
cd backend && python3 -m black app/tasks/etl_pipeline.py app/services/player_props_service.py app/services/etl/nfl/collect_recv_yds_actuals.py tests/test_nfl_recv_yds_*.py
git add backend/app/tasks/etl_pipeline.py backend/app/services/player_props_service.py backend/app/services/etl/nfl/collect_recv_yds_actuals.py backend/tests/test_nfl_recv_yds_fallback_markets.py backend/tests/test_nfl_recv_yds_celery_catalog.py backend/tests/test_nfl_recv_yds_actuals.py
git commit -m "$(cat <<'EOF'
feat(nfl): celery receiving yards weekly leaf and odds fallback

EOF
)"
```

---

### Task 7: API — `receiving_yards_predictions`

**Files:**
- Modify: `backend/app/api/v1/predictions.py`
- Modify: `backend/app/services/player_prop_projection_display.py`
- Create: `backend/tests/test_nfl_recv_yds_api.py`
- Regenerate: `docs/api/openapi.json`, `docs/api/openapi-public.json`, `docs/api/openapi-admin.json`

**Interfaces:**
- Consumes: `RecvYdsPredictions`, `_query_recent_nfl_with_fallback`, `enrich_prop_rows`
- Produces: response key `receiving_yards_predictions` with fields Model/Market/Edge/Pick (+ position)
- `enrich_nfl_recv_yds_row(row) -> dict` via `enrich_projection_vs_line` with `predicted_receiving_yards` / `ou_line` / `betting_recommendation`
- News entity map: `("nfl", "receiving_yards"): ("player_id", "game_date")`

- [ ] **Step 1: Write failing API contract test**

Follow `tests/test_nfl_anytime_td_api.py` patterns (TestClient + override auth/db). Minimal:

```python
# backend/tests/test_nfl_recv_yds_api.py
from datetime import date
from unittest.mock import MagicMock

from app.api.v1 import predictions as predictions_module
from app.services.player_prop_projection_display import enrich_nfl_recv_yds_row


def test_enrich_nfl_recv_yds_row_sets_edge_and_pick_keys():
    row = enrich_nfl_recv_yds_row(
        {
            "player_id": "1",
            "player_name": "A.J. Brown",
            "position": "WR",
            "predicted_receiving_yards": 85.0,
            "ou_line": 80.0,
            "betting_recommendation": "OVER",
            "edge_percentage": 6.25,
            "confidence_score": 0.8,
        }
    )
    assert row["predicted_receiving_yards"] == 85.0
    assert row["ou_line"] == 80.0
    assert "edge" in row
    assert row.get("recommendation") == "OVER" or row.get("betting_recommendation") == "OVER"


def test_nfl_predictions_includes_receiving_yards_key(monkeypatch):
    mock_db = MagicMock()

    def fake_query_recent(*args, **kwargs):
        model = args[1] if len(args) > 1 else kwargs.get("model")
        # Return one recv row shape when querying RecvYdsPredictions
        name = getattr(model, "__name__", "")
        if name == "RecvYdsPredictions":
            return [
                {
                    "player_id": "1",
                    "player_name": "A.J. Brown",
                    "position": "WR",
                    "team_name": "Philadelphia Eagles",
                    "opponent_team_name": "Dallas Cowboys",
                    "predicted_receiving_yards": 85.0,
                    "ou_line": 80.0,
                    "betting_recommendation": "OVER",
                    "prediction_method": "soft_anchor",
                    "game_date": date(2026, 11, 15),
                    "season": 2026,
                    "week": 11,
                }
            ]
        return []

    monkeypatch.setattr(
        predictions_module, "_query_recent_nfl_with_fallback", fake_query_recent
    )
    monkeypatch.setattr(
        predictions_module,
        "_query_nfl_anytime_td_predictions",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "app.services.game_projection_schedule.attach_game_times_from_lines",
        lambda db, rows, model: rows,
    )

    # Bypass enrich complexity: identity enrich for this contract check
    monkeypatch.setattr(
        predictions_module,
        "enrich_prop_rows",
        lambda rows, **kwargs: rows,
    )
    monkeypatch.setattr(
        predictions_module,
        "attach_team_opponent_fields",
        lambda rows: rows,
    )

    out = predictions_module.nfl_predictions(
        target_date=date(2026, 11, 15),
        tz="UTC",
        limit=50,
        _user={"tier": "pro"},
        db=mock_db,
    )
    assert "receiving_yards_predictions" in out
    assert out["receiving_yards_predictions"][0]["prediction_method"] == "soft_anchor"
    assert out["receiving_yards_predictions"][0]["position"] == "WR"
```

- [ ] **Step 2: Implement enrich + endpoint key**

```python
# in player_prop_projection_display.py
def enrich_nfl_recv_yds_row(row: dict[str, Any]) -> dict[str, Any]:
    """NFL receiving-yard O/U rows (soft-anchored board)."""
    out = enrich_projection_vs_line(
        row,
        projected_key="predicted_receiving_yards",
        line_key="ou_line",
        stat="receiving_yards",
        pick_key="betting_recommendation",
        recommendation_key="recommendation",
        edge_key="edge",
        confidence_key="pick_confidence",
    )
    if out.get("pick_confidence") is None and out.get("confidence_score") is not None:
        conf = _as_float(out["confidence_score"])
        if conf is not None:
            out["pick_confidence"] = round(conf * 100 if conf <= 1.0 else conf, 1)
            out["confidence_score"] = out["pick_confidence"]
    return out
```

In `enrich_prop_rows` sport/stat branch, add:

```python
    elif sport == "nfl" and stat == "receiving_yards":
        enriched = attach_team_opponent_fields(
            [enrich_nfl_recv_yds_row(r) for r in rows]
        )
```

And news map entry `("nfl", "receiving_yards"): ("player_id", "game_date")`.

In `nfl_predictions` return dict:

```python
        "receiving_yards_predictions": enrich_prop_rows(
            _query_recent_nfl_with_fallback(
                db,
                RecvYdsPredictions,
                "game_date",
                target_date,
                limit,
                tz=tz,
                dedupe_keys=("season", "week", "player_id"),
            ),
            sport="nfl",
            stat="receiving_yards",
            db=db,
        ),
```

Import `RecvYdsPredictions`. Sort optional: by `abs(edge)` desc inside enrich or query — matching QB absolute-edge UX is fine as a follow-up; default date query order is acceptable for v1.

- [ ] **Step 3: Regenerate OpenAPI**

```bash
cd backend && PYTHONPATH=. python3 scripts/export_openapi.py
```

- [ ] **Step 4: Tests + commit**

```bash
cd backend && PYTHONPATH=. python3 -m pytest tests/test_nfl_recv_yds_api.py -v
cd backend && python3 -m black app/api/v1/predictions.py app/services/player_prop_projection_display.py tests/test_nfl_recv_yds_api.py
git add backend/app/api/v1/predictions.py backend/app/services/player_prop_projection_display.py backend/tests/test_nfl_recv_yds_api.py docs/api/openapi.json docs/api/openapi-public.json docs/api/openapi-admin.json
git commit -m "$(cat <<'EOF'
feat(nfl): expose receiving_yards_predictions on predictions API

EOF
)"
```

---

### Task 8: Frontend columns, position filter, hub copy

**Files:**
- Modify: `frontend/src/lib/propProjectionDisplay.ts`
- Create: `frontend/src/lib/propProjectionDisplay.nfl-recv-yds.test.ts`
- Modify: `frontend/src/components/yetai/SportPredictionsPage.tsx`
- Create: `frontend/src/components/yetai/SportPredictionsPage.position-filter.test.tsx` (or colocate under `__tests__` if that is the repo norm — prefer next to existing SportPredictionsPage tests if any; else a small pure helper test)
- Modify: `frontend/src/app/predictions/nfl/page.tsx`
- Modify: `frontend/src/app/predictions/stats/page.tsx`

**Interfaces:**
- Produces: `NFL_RECV_YDS_COLUMNS: ColumnDef[]` with Player, Pos, Team, Opponent, Model, Market, Edge, Pick, Conf, News
- Extends `PropGroup` with optional `positionFilterKey?: string` (e.g. `'position'`)
- When any visible group sets `positionFilterKey`, toolbar shows All / RB / WR / TE chips; filter applies only to groups that declare the key
- Hub NFL `desc`: include receiving yards

- [ ] **Step 1: Write failing column + filter tests**

```typescript
// frontend/src/lib/propProjectionDisplay.nfl-recv-yds.test.ts
import { NFL_RECV_YDS_COLUMNS } from '@/lib/propProjectionDisplay';

describe('NFL_RECV_YDS_COLUMNS', () => {
  it('labels Pos + Model / Market / Edge / Pick', () => {
    expect(NFL_RECV_YDS_COLUMNS.map((c) => c.label)).toEqual([
      'Player',
      'Pos',
      'Team',
      'Opponent Team',
      'Model',
      'Market',
      'Edge',
      'Pick',
      'Conf',
      'News',
    ]);
  });

  it('binds Model to predicted_receiving_yards and Market to ou_line', () => {
    expect(NFL_RECV_YDS_COLUMNS.find((c) => c.label === 'Model')?.key).toBe(
      'predicted_receiving_yards',
    );
    expect(NFL_RECV_YDS_COLUMNS.find((c) => c.label === 'Market')?.key).toBe(
      'ou_line',
    );
    expect(NFL_RECV_YDS_COLUMNS.find((c) => c.label === 'Pos')?.key).toBe(
      'position',
    );
  });
});
```

```typescript
// frontend/src/lib/propPositionFilter.test.ts
import { filterRowsByPosition } from '@/lib/propPositionFilter';

describe('filterRowsByPosition', () => {
  const rows = [
    { player_name: 'A', position: 'WR' },
    { player_name: 'B', position: 'RB' },
    { player_name: 'C', position: 'TE' },
  ];

  it('returns all rows when filter is All', () => {
    expect(filterRowsByPosition(rows, 'position', 'All')).toHaveLength(3);
  });

  it('filters to a single position', () => {
    expect(filterRowsByPosition(rows, 'position', 'WR')).toEqual([
      { player_name: 'A', position: 'WR' },
    ]);
  });
});
```

- [ ] **Step 2: Run FE tests — expect FAIL**

Run: `cd frontend && npm run test:ci -- --run src/lib/propProjectionDisplay.nfl-recv-yds.test.ts src/lib/propPositionFilter.test.ts`  
Expected: FAIL missing exports

- [ ] **Step 3: Implement columns + filter helper + page wiring**

```typescript
// frontend/src/lib/propPositionFilter.ts
export type PositionFilter = 'All' | 'RB' | 'WR' | 'TE';

export const RECV_POSITION_FILTERS: PositionFilter[] = ['All', 'RB', 'WR', 'TE'];

export function filterRowsByPosition<T extends Record<string, unknown>>(
  rows: T[],
  positionKey: string,
  filter: PositionFilter,
): T[] {
  if (filter === 'All') return rows;
  return rows.filter((row) => String(row[positionKey] ?? '').toUpperCase() === filter);
}
```

In `propProjectionDisplay.ts`, export:

```typescript
export const NFL_RECV_YDS_COLUMNS: ColumnDef[] = [
  { key: 'player_name', label: 'Player', format: (v) => formatString(v) },
  { key: 'position', label: 'Pos', format: (v) => formatString(v) },
  TEAM_COLUMN,
  OPPONENT_TEAM_COLUMN,
  {
    key: 'predicted_receiving_yards',
    label: 'Model',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 0),
  },
  {
    key: 'ou_line',
    label: 'Market',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 1),
  },
  {
    key: 'edge',
    label: 'Edge',
    align: 'right',
    mono: true,
    format: (v) => formatSignedEdge(v),
    className: 'prop-edge-cell',
  },
  {
    key: 'recommendation',
    label: 'Pick',
    format: (v, row) => formatString(v ?? row.betting_recommendation),
    className: 'prop-pick-cell',
  },
  {
    key: 'pick_confidence',
    label: 'Conf',
    align: 'right',
    mono: true,
    format: (v, row) => formatPickConfidence(v ?? row.confidence_score),
    className: 'prop-conf-cell',
  },
  NEWS_COLUMN,
];
```

Extend `PropGroup`:

```typescript
export type PropGroup = {
  title: string;
  responseKey: string;
  columns: ColumnDef[];
  rowClassName?: (row: Record<string, unknown>) => string | undefined;
  /** When set, toolbar position chips filter this group's rows by this field. */
  positionFilterKey?: string;
};
```

In `SportPredictionsPage.tsx`:
- `const [positionFilter, setPositionFilter] = useState<PositionFilter>('All');`
- `const hasPositionFilterGroups = resolvedGroups.some((g) => g.positionFilterKey);`
- Render All/RB/WR/TE chips in the existing toolbar when `hasPositionFilterGroups`.
- When mapping rows for a group with `positionFilterKey`, apply `filterRowsByPosition(rows, g.positionFilterKey, positionFilter)`.

In `predictions/nfl/page.tsx` add group:

```typescript
    {
      title: 'Receiving Yards',
      responseKey: 'receiving_yards_predictions',
      columns: NFL_RECV_YDS_COLUMNS,
      rowClassName: propRowClassName,
      positionFilterKey: 'position',
    },
```

Update subtitle strings to mention receiving yards.

In `predictions/stats/page.tsx`:

```typescript
  { sport: 'nfl', href: '/predictions/nfl', emoji: '🏈', label: 'NFL', desc: 'QB passing, receiving yards, and kicker field goal projections.' },
```

- [ ] **Step 4: Run FE tests**

```bash
cd frontend && npm run test:ci -- --run src/lib/propProjectionDisplay.nfl-recv-yds.test.ts src/lib/propPositionFilter.test.ts
cd frontend && npm run lint && npm run type-check
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/propProjectionDisplay.ts frontend/src/lib/propProjectionDisplay.nfl-recv-yds.test.ts frontend/src/lib/propPositionFilter.ts frontend/src/lib/propPositionFilter.test.ts frontend/src/components/yetai/SportPredictionsPage.tsx frontend/src/app/predictions/nfl/page.tsx frontend/src/app/predictions/stats/page.tsx
git commit -m "$(cat <<'EOF'
feat(nfl): receiving yards PropGroup with position filter

EOF
)"
```

---

### Task 9: Ops docs + env example

**Files:**
- Modify: `backend/docs/NFL_ETL_PARITY.md`
- Modify: `backend/docs/NFL_ML_OPS.md`
- Modify: `backend/.env.example`

**Interfaces:**
- Documents Celery leaf, tables, API key, Odds market cost note, soft-anchor env
- Explicit: no `NFL_RECV_ML_ENABLED` in v1

- [ ] **Step 1: Update `.env.example`**

```bash
# NFL receiving yards soft-anchor (α·model + (1−α)·line); default 0.25
# NFL_RECV_ANCHOR_ALPHA=0.25
```

- [ ] **Step 2: Update `NFL_ETL_PARITY.md`**

Add rows:

| YetAI task | Role |
|------------|------|
| `nfl.recv_yds_weekly` | Odds `player_reception_yds` slate → features → soft-anchor → `pred_recv_yds_predictions` |
| `nfl.collect_recv_yds_actuals` | Grade → `pred_recv_yds_actuals` |

Phases: include weekly in **predictions** / gameday; actuals in **actuals**.  
API: `receiving_yards_predictions`. UI: Receiving Yards table + position filter.  
Odds: share budget; ~10 credits/event for `markets=player_reception_yds` (`regions=us`) like pass yards.

- [ ] **Step 3: Update `NFL_ML_OPS.md`**

Add a short section **Receiving yards (v1)**: soft-anchor via `NFL_RECV_ANCHOR_ALPHA` (default 0.25); non-ML only; residual ML + line-vs-ML promote gate deferred (mirror QB Phase C later).

- [ ] **Step 4: Commit**

```bash
git add backend/docs/NFL_ETL_PARITY.md backend/docs/NFL_ML_OPS.md backend/.env.example
git commit -m "$(cat <<'EOF'
docs(nfl): receiving yards ETL parity and soft-anchor ops

EOF
)"
```

---

### Task 10: Full gate verification

**Files:** none new — verify the vertical

- [ ] **Step 1: Backend full gates**

```bash
cd backend && python3 -m black .
cd backend && python3 -m black --check .
cd backend && PYTHONPATH=. python3 -m pytest -q tests/test_nfl_recv_yds_model.py tests/test_nfl_recv_yds_features.py tests/test_nfl_recv_yds_betting.py tests/test_nfl_recv_yds_projector.py tests/test_nfl_recv_yds_models_import.py tests/test_nfl_recv_yds_fallback_markets.py tests/test_nfl_recv_yds_celery_catalog.py tests/test_nfl_recv_yds_api.py
```

Then full suite before push: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest -q` (or `python3 -m pytest -q` if venv path differs).

- [ ] **Step 2: Frontend gates**

```bash
cd frontend && npm run lint && npm run type-check && npm run test:ci
```

- [ ] **Step 3: Manual acceptance checklist (against running API if available)**

1. `GET /api/v1/predictions/nfl` includes `receiving_yards_predictions` array.
2. Lined rows show `prediction_method=soft_anchor` and `predicted_receiving_yards != ou_line` when α=0.25 and model≠line.
3. Empty Odds response ⇒ empty board (no fabricated lines).
4. `/predictions/nfl` shows Receiving Yards table; position chips filter RB/WR/TE.
5. Hub card text mentions receiving yards.

- [ ] **Step 4: Final commit only if fixes were needed; push branch**

---

## Self-review vs spec

| Spec requirement | Task coverage |
|------------------|---------------|
| Betting board Model/Market/Edge/Pick | Tasks 4, 5, 7, 8 |
| Odds `player_reception_yds` | Tasks 4, 6 |
| Lined players only | Tasks 4, 5 (skip upsert without line) |
| Non-ML targets×YPR + depth/pace/matchup | Tasks 1, 3 |
| Soft-anchor α default 0.25 / `NFL_RECV_ANCHOR_ALPHA` | Tasks 1, 9 |
| Never invent targets / never market-as-projection | Tasks 1, 3, 4 tests |
| Fail-closed Odds | Task 4 `clear_betting_fields` + empty fetch |
| One table + position filter | Task 8 |
| Hub copy update | Task 8 |
| Tables `pred_recv_yds_predictions` / `_actuals` | Task 2 |
| ETL modules + weekly chain + Celery | Tasks 5, 6 |
| FALLBACK markets include reception yds | Task 6 |
| API `receiving_yards_predictions` + OpenAPI | Task 7 |
| No residual ML in v1 | Global Constraints + Task 9 |
| Clone QB soft-anchor #162 | Task 1 (same formula/tests) |
| Edge thresholds mirror QB | Task 4 |
| Actuals collector | Task 6 |
| Ops docs | Task 9 |
| Auto-pick / accuracy / rush board / ML promote | Explicitly out of scope (Follow-ups in spec) |

**Placeholder scan:** no TBD/TODO/`similar to Task N` / bare `pass` steps. Usage join is fully specified in Task 5 (`select_usage_priors_for_names` + nflverse loader). Actuals grading helpers are complete in Task 6. API contract test calls `nfl_predictions` directly.

**Type consistency:** `predicted_receiving_yards`, `ou_line`, `betting_recommendation`, `prediction_method='soft_anchor'`, `position`, response key `receiving_yards_predictions`, market `player_reception_yds`, env `NFL_RECV_ANCHOR_ALPHA` are used consistently across tasks.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-10-nfl-receiving-yards-projections.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in-session with executing-plans checkpoints  

Which approach?
