# NFL Anytime Touchdown Prop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build hierarchical anytime-TD probabilities (QB/RB/WR/TE), full feature ETL including curated scheme tags, Odds attach, gated UI, and a backtest smoke gate before enabling the board.

**Architecture:** Feature builders → λ (expected TDs) → P(≥1)=1−e^(−λ) → `pred_nfl_anytime_td_predictions`; Odds `player_anytime_td` for edge; FE group behind `NFL_ANYTIME_TD_UI`.

**Tech Stack:** Python 3, SQLAlchemy/Alembic, Celery, nfl-data-py, Odds API, Next.js/TS, pytest, Black, PyYAML.

**Spec:** `docs/superpowers/specs/2026-08-10-nfl-anytime-td-design.md`

## Global Constraints

- Player universe: QB/RB/WR/TE only (meaningful snaps / depth-chart active).
- Model: hierarchical λ → `td_probability = 1 - exp(-λ)`; NegBin optional later.
- Scheme tags: curated YAML → `pred_nfl_defense_scheme` (no paid vendor).
- UI off by default: `NFL_ANYTIME_TD_UI` falsy until backtest gate + explicit enable.
- API key: `anytime_td_predictions` sorted by `td_probability` desc.
- Unique prediction key: `(season, week, player_id)`.
- Before each Python commit: black touched files + targeted pytest; stage specific paths only.
- No first/last TD, no Monte Carlo TD engine, no auto-pick in this plan.

## File map

| Path | Responsibility |
|------|----------------|
| `backend/data/nfl/defensive_schemes.yaml` | Season scheme tags for 32 teams |
| `backend/app/services/etl/nfl/scheme_loader.py` | Load YAML → DB upsert |
| `backend/app/services/etl/nfl/anytime_td_model.py` | Pure λ and P(anytime) math |
| `backend/app/services/etl/nfl/anytime_td_features.py` | Build feature dicts (usage, RZ, defense, weather, env) |
| `backend/app/services/etl/nfl/anytime_td_projector.py` | Infer + upsert predictions |
| `backend/app/services/etl/nfl/anytime_td_betting.py` | Odds attach |
| `backend/app/services/etl/nfl/anytime_td_actuals.py` | Grade actuals |
| `backend/app/services/etl/nfl/anytime_td_backtest.py` | Offline/quick backtest + metrics JSON |
| `backend/app/models/predictions_models.py` | New ORM models |
| `backend/alembic/versions/2026_08_10_nfl_anytime_td.py` | Migration |
| `backend/app/tasks/etl_pipeline.py` | Celery tasks + NFL_PHASES |
| `backend/app/api/v1/predictions.py` | API key |
| `backend/app/services/nfl_accuracy_service.py` | Accuracy buckets |
| `frontend/src/app/predictions/nfl/page.tsx` | Gated table group |
| `backend/.env.example` | Document `NFL_ANYTIME_TD_UI` |

---

### Task 1: Scheme YAML + loader + pure model math

**Files:**
- Create: `backend/data/nfl/defensive_schemes.yaml`
- Create: `backend/app/services/etl/nfl/scheme_loader.py`
- Create: `backend/app/services/etl/nfl/anytime_td_model.py`
- Create: `backend/tests/test_nfl_anytime_td_model.py`
- Create: `backend/tests/test_nfl_scheme_loader.py`

**Interfaces:**
- Produces:
  - `load_schemes_from_yaml(path: Path | None = None) -> dict[str, dict]` keyed by team abbr or full name
  - `expected_tds(*, team_rz_trips, player_rz_share, conversion_rate, defense_mult, weather_mult, script_mult) -> float`
  - `anytime_td_probability(expected_tds: float) -> float`  # `1 - math.exp(-max(0, λ))`
  - Clamp probability to `[0, 1]`

- [ ] **Step 1: Failing tests**

```python
# test_nfl_anytime_td_model.py
from app.services.etl.nfl.anytime_td_model import anytime_td_probability, expected_tds

def test_zero_lambda_zero_prob():
    assert anytime_td_probability(0.0) == 0.0

def test_probability_increases_with_lambda():
    assert anytime_td_probability(0.3) < anytime_td_probability(0.8)

def test_expected_tds_multiplicative():
    lam = expected_tds(
        team_rz_trips=3.0,
        player_rz_share=0.25,
        conversion_rate=0.4,
        defense_mult=1.1,
        weather_mult=1.0,
        script_mult=1.0,
    )
    assert abs(lam - 3.0 * 0.25 * 0.4 * 1.1) < 1e-9
```

```python
# test_nfl_scheme_loader.py
from pathlib import Path
from app.services.etl.nfl.scheme_loader import load_schemes_from_yaml

def test_load_schemes_has_thirty_two_teams(tmp_path: Path):
    # either ship full yaml and assert len==32, or write minimal fixture
    schemes = load_schemes_from_yaml()
    assert len(schemes) >= 32
    sample = next(iter(schemes.values()))
    assert "cover_base" in sample
    assert "man_zone_lean" in sample
    assert "pressure_lean" in sample
```

- [ ] **Step 2: Implement model + YAML for all 32 NFL teams (reasonable 2025/26 defaults) + loader**

YAML shape per team:
```yaml
KC:
  cover_base: "cover_3"
  man_zone_lean: "zone"
  pressure_lean: "medium"
  as_of: "2026-08-01"
```

- [ ] **Step 3: Tests pass, black, commit**

```bash
git commit -m "feat(nfl): anytime TD probability math and defensive scheme YAML"
```

---

### Task 2: SQLAlchemy models + Alembic migration

**Files:**
- Modify: `backend/app/models/predictions_models.py`
- Create: `backend/alembic/versions/2026_08_10_nfl_anytime_td.py`
- Create: `backend/tests/test_nfl_anytime_td_models_import.py`

**Interfaces:**
- Models:
  - `NFLDefenseScheme` → `pred_nfl_defense_scheme`
  - `NFLAnytimeTDPredictions` → `pred_nfl_anytime_td_predictions`
  - `NFLAnytimeTDActuals` → `pred_nfl_anytime_td_actuals`
  - Optional skip `pred_nfl_td_feature_weekly` in v1 if features stay JSON on predictions row (`features` JSON column)

Prediction columns (minimum): `season`, `week`, `game_date`, `player_id`, `player_name`, `position`, `team_name`, `opponent_team_name`, `expected_tds`, `td_probability`, `market_odds`, `market_implied_prob`, `edge`, `recommendation`, `confidence_score`, `features` (JSON), `model_version`, `prediction_date`, unique `(season, week, player_id)`.

`down_revision`: current alembic head on this branch (`20260810_nfl_game_projections`).

- [ ] **Step 1: Failing import test for tablenames**
- [ ] **Step 2: Models + migration**
- [ ] **Step 3: Commit** `feat(nfl): anytime TD and defense scheme tables`

---

### Task 3: Feature builder (pure + nflverse hooks)

**Files:**
- Create: `backend/app/services/etl/nfl/anytime_td_features.py`
- Create: `backend/tests/test_nfl_anytime_td_features.py`

**Interfaces:**
- `defense_multiplier(scheme: dict | None, tds_allowed_vs_pos: float, league_avg: float) -> float`
- `weather_multiplier(*, outdoor: bool, wind_mph: float | None, precip: bool) -> float`
- `build_player_feature_row(...)` → dict with keys used by projector: `team_rz_trips`, `player_rz_share`, `conversion_rate`, `defense_mult`, `weather_mult`, `script_mult`, plus metadata
- `scheme_defense_adjustment(cover_base, man_zone_lean, pressure_lean, position) -> float` small bounded factors (e.g. 0.9–1.15)

Feature builder must accept injected dicts/DataFrames so unit tests need no network. Optional `fetch_*_nflverse` helpers can call nflverse but are mocked in tests.

Include all groups from spec (usage, RZ, offense tendencies, opponent defense aggregates, scheme, weather, game env) as fields on the feature dict even if some use league priors when data missing.

- [ ] **Step 1–4: TDD feature helpers, commit** `feat(nfl): anytime TD feature builders`

---

### Task 4: Projector + betting Odds attach

**Files:**
- Create: `backend/app/services/etl/nfl/anytime_td_projector.py`
- Create: `backend/app/services/etl/nfl/anytime_td_betting.py`
- Create: `backend/tests/test_nfl_anytime_td_projector.py`
- Create: `backend/tests/test_nfl_anytime_td_betting.py`

**Interfaces:**
- `projector.run(season=None, week=None) -> dict` upserts predictions for universe
- `betting.run(season=None, week=None) -> dict` loads Odds `americanfootball_nfl` market `player_anytime_td`, matches by player name, sets `market_odds`, `market_implied_prob`, `edge = td_probability - implied`, recommendation `OVER` if edge ≥ 0.05 else `NO_PLAY` (document threshold constant `ANYTIME_TD_EDGE_THRESHOLD = 0.05`)
- American odds → implied: standard formula

Unit-test projector with mocked feature rows; unit-test odds parse/implied/edge without live API.

- [ ] **Commit:** `feat(nfl): anytime TD projector and Odds attach`

---

### Task 5: Actuals + Celery phases + scheme sync task

**Files:**
- Create: `backend/app/services/etl/nfl/anytime_td_actuals.py`
- Create: `backend/app/services/etl/nfl/sync_defense_schemes.py` (calls scheme_loader upsert)
- Modify: `backend/app/tasks/etl_pipeline.py`
- Modify: `backend/docs/NFL_ETL_PARITY.md`
- Create: `backend/tests/test_nfl_anytime_td_pipeline.py`

**Interfaces:**
- Celery tasks:
  - `nfl.sync_defense_schemes`
  - `nfl.anytime_td_projector`
  - `nfl.anytime_td_betting`
  - `nfl.anytime_td_actuals`
- Extend `NFL_PHASES`:
  - actuals: existing + `nfl_anytime_td_actuals`
  - after game_projections (or new `anytime_td` phase before predictions props): sync schemes (or once/week), projector, betting
  - Keep QB/kicker predictions phase

Prefer structure:
```
actuals: ... + anytime_td_actuals
game_lines: ...
game_projections: ...
anytime_td: sync_defense_schemes, anytime_td_projector, anytime_td_betting
predictions: yetiwatch, qb_weekly, kickers
```

- [ ] **Commit:** `feat(nfl): wire anytime TD into Celery NFL pipeline`

---

### Task 6: API + accuracy + feature flag

**Files:**
- Modify: `backend/app/api/v1/predictions.py`
- Modify: `backend/app/services/nfl_accuracy_service.py`
- Modify: `backend/.env.example`
- Create: `backend/app/services/etl/nfl/anytime_td_config.py` with `anytime_td_ui_enabled() -> bool`
- Create: `backend/tests/test_nfl_anytime_td_api.py`
- Regenerate OpenAPI if needed

**Interfaces:**
- Always return `anytime_td_predictions` key from API (empty list if none) sorted by `td_probability` desc — **or** gate empty when UI flag off? Spec: UI gated; API may still return data for admin/testing. **Decision:** API always returns the key (sorted); FE hides group unless `NFL_ANYTIME_TD_UI` truthy **or** expose flag via existing config endpoint if present. Simplest: FE checks `process.env.NEXT_PUBLIC_NFL_ANYTIME_TD_UI` OR always show table when rows exist but document that prod keeps flag off until gate — **Spec says UI behind flag.** Implement:
  - Backend helper `anytime_td_ui_enabled()`
  - API includes `anytime_td_predictions` always (data available for backtest/clients)
  - FE only renders group when `NEXT_PUBLIC_NFL_ANYTIME_TD_UI=1` **or** when rows exist AND env set — use `NEXT_PUBLIC_NFL_ANYTIME_TD_UI` default unset/false.

Accuracy bucket for anytime TD Brier when actuals exist.

- [ ] **Commit:** `feat(nfl): expose anytime TD predictions on API`

---

### Task 7: Frontend Anytime TD group (gated)

**Files:**
- Modify: `frontend/src/app/predictions/nfl/page.tsx`
- Create: `frontend/src/lib/anytimeTdDisplay.ts` (columns + gate helper)
- Create: `frontend/src/lib/anytimeTdDisplay.test.ts`
- Modify: `frontend/.env.example` if exists

**Interfaces:**
- Columns: Player, Pos, Team, Opp, P(TD), Odds, Edge, Pick, Conf
- Format `td_probability` as percent
- Group only added when `isAnytimeTdUiEnabled()` true
- Sort client default already from API order

- [ ] **Commit:** `feat(nfl): gated anytime TD board on predictions page`

---

### Task 8: Backtest smoke + metrics artifact + docs

**Files:**
- Create: `backend/app/services/etl/nfl/anytime_td_backtest.py`
- Create: `backend/scripts/nfl_anytime_td_backtest.py` (CLI `--quick`)
- Create: `backend/models/nfl/anytime_td_metrics.json` (from quick run / fixture baseline)
- Create: `backend/tests/test_nfl_anytime_td_backtest.py`
- Modify: `backend/docs/NFL_ETL_PARITY.md` / short `backend/docs/NFL_ANYTIME_TD.md`

**Interfaces:**
- Quick mode: synthetic or tiny fixed sample asserting Brier computation + gate helper `passes_gate(metrics, baselines) -> bool`
- Document: enable UI only when metrics pass and env set

- [ ] **Commit:** `feat(nfl): anytime TD backtest smoke and go-live docs`

---

## Plan self-review

| Spec item | Task |
|-----------|------|
| Hierarchical λ → P | 1, 4 |
| Scheme YAML + DB | 1, 2, 5 |
| Full feature groups | 3 |
| Projector + Odds | 4 |
| Celery phases + actuals | 5 |
| API + accuracy | 6 |
| Gated FE board | 7 |
| Backtest gate | 8 |
| QB/RB/WR/TE universe | 3–4 |
| No first/last, no MC, no auto-pick | Global |

No TBD placeholders. Types/names consistent: `NFLAnytimeTD*`, `anytime_td_*` Celery names, API key `anytime_td_predictions`.
