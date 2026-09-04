# NFL Accuracy P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the four highest-leverage NFL accuracy fixes: market-residual QB yards with disagreement PASS, a real week-horizon game board that reprices on QB-out plus TNF Beat, ATD skill-starter universe with RB overdispersion and gameday refresh, and live kicker weather/volume.

**Architecture:** Keep the four existing stacks. Add small pure helpers (yards publisher, projection window, QB-out margin, ATD slot fill, NegBin P(TD), kicker weather mapping) and wire them into current Celery phases. Do not add Monte Carlo, moneyline classifiers, or new prop markets.

**Tech Stack:** Python 3.11, FastAPI/SQLAlchemy, Celery Beat, pytest, Black. Work from the `feat/nfl-accuracy-p0` worktree.

## Global Constraints

- Default NFL season remains `2026` via `get_nfl_season()` / `NFL_SEASON`.
- Do not set `NFL_QB_ML_ENABLED=1` in env or docs as a required prod flip. Published yards use the **real prop line** when ML promote is off; residual GBM still requires the flag **and** `line_is_real`.
- O/U classifier disagreement always yields `PASS` (no strong-edge override).
- Game projector window must equal `GAME_LINES_HORIZON_DAYS` (14) from `update_game_lines.py`.
- QB-out spread adjustment is `QB_OUT_SPREAD_POINTS = 3.5` home-perspective points (home QB out → −3.5; away QB out → +3.5; both → 0.0).
- ATD universe: skill positions only; fill to slots `{QB: 1, RB: 2, WR: 3, TE: 1}` from usage after depth_team=1 starters; still exclude KR/PR/K/P special-teams depth slots.
- Anytime TD still counts rush+rec only (no passing TDs for the QB).
- RB anytime probability uses Negative Binomial `P(X≥1) = 1 - (r/(r+λ))^r` with `RB_TD_DISPERSION = 2.0`; other positions stay Poisson `1 - exp(-λ)`.
- Kickers must not import `weather_integration`. Weather comes from `pred_nfl_weather` fields (`temperature`, `wind_speed`) or None.
- TDD required. Black on every touched Python file. Commit with specific paths only (no `git add .`).
- Do not change OpenAPI unless an API response field is added (none expected).
- Do not enable `NFL_ANYTIME_TD_UI` / `NEXT_PUBLIC_NFL_ANYTIME_TD_UI`.
- Critical Celery tasks stay `nfl.qb_weekly` and `nfl.kickers` (do not expand abort set).

## File map

| Path | Role |
|------|------|
| `backend/app/services/etl/nfl/qb_passing_yards_ml.py` | Publish line (or GBM) when `line_is_real` |
| `backend/app/services/etl/nfl/qb_betting.py` | Disagreement → always PASS |
| `backend/app/services/etl/nfl/update_game_lines.py` | Shared `GAME_LINES_HORIZON_DAYS` |
| `backend/app/services/etl/nfl/spread_projector.py` | Horizon + QB-out adjustment |
| `backend/app/services/etl/nfl/totals_projector.py` | Same horizon |
| `backend/app/services/etl/nfl/qb_spread_adjustment.py` | Pure QB-out margin helper (new) |
| `backend/app/celery_app.py` | TNF/Sat gameday Beat |
| `backend/app/tasks/etl_pipeline.py` | Gameday phases: games + ATD |
| `backend/app/services/etl/nfl/anytime_td_features.py` | Usage slot fill |
| `backend/app/services/etl/nfl/anytime_td_model.py` | NegBin for RB |
| `backend/app/services/etl/nfl/anytime_td_projector.py` | Pass position into probability |
| `backend/app/services/etl/nfl/kicker_weather.py` | Map NFLWeather / drop dead import (new) |
| `backend/app/services/etl/nfl/kickers.py` | Live kicker stats + weather helper |
| `backend/app/services/etl/nfl/kicker_volume.py` | Weather multiplier on attempts/make% |
| `backend/docs/NFL_ML_OPS.md` | QB publish-line behavior |
| `backend/docs/NFL_ETL_PARITY.md` | Horizon, Beat, gameday phases |

---

### Task 1: QB market-line production + O/U disagreement PASS

**Files:**
- Modify: `backend/app/services/etl/nfl/qb_passing_yards_ml.py`
- Modify: `backend/app/services/etl/nfl/qb_betting.py`
- Modify: `backend/tests/test_nfl_qb_passing_yards_ml.py`
- Modify: `backend/tests/test_nfl_qb_ou_classifier.py`
- Modify: `backend/docs/NFL_ML_OPS.md` (one short paragraph under QB passing yards)

**Interfaces:**
- Consumes: existing `enrich_qb_prediction_for_write`, `generate_betting_recommendation`, `FEATURE_NAMES` / `pass_yds_line` / `line_is_real`
- Produces: `published_qb_yards(*, tier_yards: float, pass_yds_line: float | None, line_is_real: bool, ml_yards: float | None, ml_enabled: bool) -> tuple[float, str]` returning `(yards, method_suffix)` where method is `"gbm"` (caller maps to existing gbm method names), `"market_line"`, or `"tier"`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_nfl_qb_passing_yards_ml.py`:

```python
from app.services.etl.nfl.qb_passing_yards_ml import published_qb_yards


def test_published_qb_yards_uses_line_when_real_and_ml_off():
    yards, method = published_qb_yards(
        tier_yards=245.0,
        pass_yds_line=268.5,
        line_is_real=True,
        ml_yards=252.0,
        ml_enabled=False,
    )
    assert yards == 268.5
    assert method == "market_line"


def test_published_qb_yards_keeps_tier_without_real_line():
    yards, method = published_qb_yards(
        tier_yards=245.0,
        pass_yds_line=None,
        line_is_real=False,
        ml_yards=252.0,
        ml_enabled=False,
    )
    assert yards == 245.0
    assert method == "tier"


def test_published_qb_yards_promotes_ml_when_enabled_and_line_real():
    yards, method = published_qb_yards(
        tier_yards=245.0,
        pass_yds_line=255.0,
        line_is_real=True,
        ml_yards=260.0,
        ml_enabled=True,
    )
    assert yards == 260.0
    assert method == "gbm"


def test_enrich_publishes_market_line_when_ml_disabled(monkeypatch):
    monkeypatch.delenv("NFL_QB_ML_ENABLED", raising=False)
    with patch.object(qbm, "predict_yards_ml_loaded", return_value=252.0):
        out = enrich_qb_prediction_for_write(
            _tier_pred(),
            season=2024,
            week=3,
            context={
                "pass_yds_line": 268.5,
                "line_is_real": True,
                "dynamic_tier_yards": 245.0,
            },
        )
    assert out["predicted_passing_yards"] == 268.5
    assert out["prediction_method"] == "market_line"
    assert out["feature_importance"]["ml_shadow_yards"] == 252.0
```

Add to `backend/tests/test_nfl_qb_ou_classifier.py`:

```python
def test_betting_recommendation_ml_disagreement_passes_even_on_strong_yards_edge():
    # ~16.7% yards OVER vs ML UNDER — previously leaked OVER when |edge| >= 12
    out = generate_betting_recommendation(280.0, 240.0, 0.8, over_probability=0.35)
    assert out["recommendation"] == "PASS"
    assert "disagrees" in out["reason"].lower() or "disagree" in out["reason"].lower()
```

Keep `test_betting_recommendation_ml_disagreement_passes` (7% edge) green.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_qb_passing_yards_ml.py::test_published_qb_yards_uses_line_when_real_and_ml_off tests/test_nfl_qb_ou_classifier.py::test_betting_recommendation_ml_disagreement_passes_even_on_strong_yards_edge -q`

Expected: FAIL (import error or assertion OVER)

- [ ] **Step 3: Implement**

In `qb_passing_yards_ml.py` add:

```python
def published_qb_yards(
    *,
    tier_yards: float,
    pass_yds_line: float | None,
    line_is_real: bool,
    ml_yards: float | None,
    ml_enabled: bool,
) -> tuple[float, str]:
    if ml_enabled and ml_yards is not None and line_is_real:
        return float(ml_yards), "gbm"
    if line_is_real and pass_yds_line is not None:
        return float(pass_yds_line), "market_line"
    return float(tier_yards), "tier"
```

In `enrich_qb_prediction_for_write`, after computing `tier_yards` and `ml_yards`, call `published_qb_yards` using `_line_is_real_from_features(feats)` and `feats.get("pass_yds_line")` (treat `line_is_real` feature 0/1). If method is `"market_line"`, set `prediction_method` to `"market_line"`. If `"gbm"`, keep existing residual vs yards method mapping (`gbm_qb_residual` / `gbm_qb_yards`). If `"tier"`, keep existing method string. Still store `ml_shadow_yards` when ML is loaded and not used for production yards.

When `pass_yds_line` feature is 0.0 and `line_is_real` is false, do not treat 0 as a line.

In `generate_betting_recommendation`, change the disagreement block to drop `and abs(edge_percentage) < strong_edge` so any OVER/UNDER mismatch with `ml_rec` returns PASS.

- [ ] **Step 4: Run tests**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_qb_passing_yards_ml.py tests/test_nfl_qb_ou_classifier.py -q`

Expected: PASS

- [ ] **Step 5: Black + commit**

```bash
cd backend && python3 -m black app/services/etl/nfl/qb_passing_yards_ml.py app/services/etl/nfl/qb_betting.py tests/test_nfl_qb_passing_yards_ml.py tests/test_nfl_qb_ou_classifier.py
git add backend/app/services/etl/nfl/qb_passing_yards_ml.py backend/app/services/etl/nfl/qb_betting.py backend/tests/test_nfl_qb_passing_yards_ml.py backend/tests/test_nfl_qb_ou_classifier.py backend/docs/NFL_ML_OPS.md
git commit -m "$(cat <<'EOF'
fix(nfl): publish pass-yds line and always PASS on O/U disagreement

Stops the 46% O/U leak by using the real prop line as the production mean when ML promote is off, and by refusing picks when yards-edge and the classifier disagree.
EOF
)"
```

In `NFL_ML_OPS.md` add under the production ML gating paragraph: when `NFL_QB_ML_ENABLED` is unset, a real `pass_yds_line` is published as `predicted_passing_yards` (`prediction_method=market_line`); GBM still requires the flag.

---

### Task 2: Game horizon + QB-out reprice + TNF/Sat Beat

**Files:**
- Create: `backend/app/services/etl/nfl/qb_spread_adjustment.py`
- Create: `backend/tests/test_nfl_qb_spread_adjustment.py`
- Modify: `backend/app/services/etl/nfl/spread_projector.py`
- Modify: `backend/app/services/etl/nfl/totals_projector.py`
- Modify: `backend/tests/test_nfl_spread_projector.py`
- Modify: `backend/app/celery_app.py`
- Modify: `backend/app/tasks/etl_pipeline.py`
- Modify: `backend/tests/test_nfl_anytime_td_celery_catalog.py`
- Modify: `backend/docs/NFL_ETL_PARITY.md`

**Interfaces:**
- Consumes: `GAME_LINES_HORIZON_DAYS` from `update_game_lines.py`; `NFL_CONFIG`; `_project_spread_row`
- Produces:
  - `projection_end_date(today) -> date` = `today + timedelta(days=GAME_LINES_HORIZON_DAYS)`
  - `QB_OUT_SPREAD_POINTS = 3.5`
  - `qb_out_margin_adjustment(*, home_qb_out: bool, away_qb_out: bool, points: float = QB_OUT_SPREAD_POINTS) -> float`
  - `_project_spread_row(..., home_qb_out: bool = False, away_qb_out: bool = False)` adds adjustment to `projected_margin` before win-prob/edge
  - Beat keys: `nfl-gameday-availability-thu-am` (Thu 10:00), `nfl-gameday-availability-thu-pm` (Thu 19:00), `nfl-gameday-availability-sat` (Sat 12:30), all calling `run_nfl_gameday_availability`
  - `NFL_GAMEDAY_AVAILABILITY_PHASES` after this task: `predictions` = qb_weekly, kickers; `game_projections` = spread_projector, totals_projector. (ATD added in Task 3.)

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_nfl_qb_spread_adjustment.py`:

```python
from datetime import date

from app.services.etl.nfl.qb_spread_adjustment import (
    QB_OUT_SPREAD_POINTS,
    qb_out_margin_adjustment,
    team_qb_is_out,
)
from app.services.etl.nfl.update_game_lines import GAME_LINES_HORIZON_DAYS
from app.services.etl.nfl.spread_projector import projection_end_date, _project_spread_row


def test_qb_out_margin_home_out_hurts_home():
    assert qb_out_margin_adjustment(home_qb_out=True, away_qb_out=False) == -QB_OUT_SPREAD_POINTS


def test_qb_out_margin_away_out_helps_home():
    assert qb_out_margin_adjustment(home_qb_out=False, away_qb_out=True) == QB_OUT_SPREAD_POINTS


def test_qb_out_margin_both_or_neither_is_zero():
    assert qb_out_margin_adjustment(home_qb_out=False, away_qb_out=False) == 0.0
    assert qb_out_margin_adjustment(home_qb_out=True, away_qb_out=True) == 0.0


def test_team_qb_is_out_from_status_and_backup_flag():
    assert team_qb_is_out({"injury_status": "Out", "is_backup": False}) is True
    assert team_qb_is_out({"injury_status": "IR", "is_backup": False}) is True
    assert team_qb_is_out({"injury_status": "Doubtful", "is_backup": False}) is True
    assert team_qb_is_out({"injury_status": "Questionable", "is_backup": False}) is False
    assert team_qb_is_out({"injury_status": "Healthy", "is_backup": True}) is True
    assert team_qb_is_out({"injury_status": "Healthy", "is_backup": False}) is False


def test_projection_end_date_matches_game_lines_horizon():
    today = date(2026, 9, 9)
    end = projection_end_date(today)
    assert (end - today).days == GAME_LINES_HORIZON_DAYS
    assert GAME_LINES_HORIZON_DAYS >= 10


def test_spread_row_applies_home_qb_out():
    base = _project_spread_row(
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        spread_home=-3.0,
        elos={"Kansas City Chiefs": 1600.0, "Baltimore Ravens": 1400.0},
        ppg_stats={
            "Kansas City Chiefs": (24.0, 20.0),
            "Baltimore Ravens": (24.0, 20.0),
        },
    )
    adj = _project_spread_row(
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        spread_home=-3.0,
        elos={"Kansas City Chiefs": 1600.0, "Baltimore Ravens": 1400.0},
        ppg_stats={
            "Kansas City Chiefs": (24.0, 20.0),
            "Baltimore Ravens": (24.0, 20.0),
        },
        home_qb_out=True,
    )
    assert adj["projected_margin"] == pytest.approx(base["projected_margin"] - 3.5)
```

Add `import pytest` at top.

In `test_nfl_anytime_td_celery_catalog.py` extend `test_gameday_availability_beat_and_catalog`:

```python
    beat = celery_app.conf.beat_schedule
    assert beat["nfl-gameday-availability-thu-am"]["task"] == orch
    assert beat["nfl-gameday-availability-thu-pm"]["task"] == orch
    assert beat["nfl-gameday-availability-sat"]["task"] == orch
    assert "app.tasks.etl_pipeline.nfl.spread_projector" in flat
    assert "app.tasks.etl_pipeline.nfl.totals_projector" in flat
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_qb_spread_adjustment.py tests/test_nfl_anytime_td_celery_catalog.py::test_gameday_availability_beat_and_catalog -q`

Expected: FAIL (missing module / missing beat keys)

- [ ] **Step 3: Implement**

`qb_spread_adjustment.py`:

```python
QB_OUT_SPREAD_POINTS = 3.5
_OUT_STATUSES = frozenset({"out", "ir", "doubtful", "injured reserve"})


def qb_out_margin_adjustment(
    *,
    home_qb_out: bool,
    away_qb_out: bool,
    points: float = QB_OUT_SPREAD_POINTS,
) -> float:
    if home_qb_out and away_qb_out:
        return 0.0
    if home_qb_out:
        return -float(points)
    if away_qb_out:
        return float(points)
    return 0.0


def team_qb_is_out(row: dict) -> bool:
    status = str(row.get("injury_status") or "").strip().lower()
    if status in _OUT_STATUSES:
        return True
    return bool(row.get("is_backup"))
```

Add `projection_end_date(today)` in `spread_projector.py` (import horizon from `update_game_lines`). Use it in both `spread_projector.run` and `totals_projector.run` instead of `timedelta(days=1)`.

Extend `_project_spread_row` with `home_qb_out=False, away_qb_out=False`; add `qb_out_margin_adjustment(...)` to `projected_margin` before `margin_to_win_prob`. Record `qb_out_adj` in `factors`.

In `spread_projector.run`, build `qb_out_by_team` from `pred_qb_predictions` for the current NFL week (`get_current_nfl_week` / `get_nfl_season`): for each team_name, `team_qb_is_out` on that row. Match `NFLGameLines.home_team_name` / `away_team_name`. If no QB row, treat as not out.

`totals_projector` already calls `_project_spread_row` — pass the same out flags so scores stay aligned.

Celery Beat: copy Sunday entry pattern; `day_of_week="4"` Thursday, `"6"` Saturday. Hours: 10 and 19 Thursday, 12:30 Saturday. `expires: 7200`.

`NFL_GAMEDAY_AVAILABILITY_PHASES`:

```python
NFL_GAMEDAY_AVAILABILITY_PHASES = [
    ("predictions", [nfl_qb_weekly, nfl_kickers]),
    ("game_projections", [nfl_spread_projector, nfl_totals_projector]),
]
```

QB weekly must stay before spread so backup flags exist.

- [ ] **Step 4: Run tests**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_qb_spread_adjustment.py tests/test_nfl_spread_projector.py tests/test_nfl_anytime_td_celery_catalog.py tests/test_nfl_pipeline_phases.py -q`

Expected: PASS

- [ ] **Step 5: Black + commit**

```bash
cd backend && python3 -m black app/services/etl/nfl/qb_spread_adjustment.py app/services/etl/nfl/spread_projector.py app/services/etl/nfl/totals_projector.py tests/test_nfl_qb_spread_adjustment.py tests/test_nfl_spread_projector.py tests/test_nfl_anytime_td_celery_catalog.py
git add backend/app/services/etl/nfl/qb_spread_adjustment.py backend/app/services/etl/nfl/spread_projector.py backend/app/services/etl/nfl/totals_projector.py backend/app/celery_app.py backend/app/tasks/etl_pipeline.py backend/tests/test_nfl_qb_spread_adjustment.py backend/tests/test_nfl_spread_projector.py backend/tests/test_nfl_anytime_td_celery_catalog.py backend/docs/NFL_ETL_PARITY.md
git commit -m "$(cat <<'EOF'
fix(nfl): project the full week slate and reprice spreads when the QB is out

Game boards used a today+1 window while lines cover 14 days, and a late scratch never moved the spread. Add TNF/Saturday gameday Beat ticks.
EOF
)"
```

Update `NFL_ETL_PARITY.md` gameday bullet: horizon 14 days, QB-out 3.5 pts, Thu/Sat Beat.

---

### Task 3: ATD starter slot-fill + RB NegBin + gameday ATD

**Files:**
- Modify: `backend/app/services/etl/nfl/anytime_td_features.py` (`select_skill_universe`)
- Modify: `backend/app/services/etl/nfl/anytime_td_model.py`
- Modify: `backend/app/services/etl/nfl/anytime_td_projector.py`
- Modify: `backend/app/services/etl/nfl/anytime_td_calibration.py` (hierarchical_probability must use new signature)
- Modify: `backend/app/tasks/etl_pipeline.py` (`NFL_GAMEDAY_AVAILABILITY_PHASES`)
- Modify: `backend/tests/test_nfl_anytime_td_feature_assembly.py`
- Modify: `backend/tests/test_nfl_anytime_td_models_import.py` or add `backend/tests/test_nfl_anytime_td_model.py`
- Modify: `backend/tests/test_nfl_anytime_td_celery_catalog.py`
- Modify: `backend/docs/NFL_ANYTIME_TD.md`

**Interfaces:**
- Consumes: `_USAGE_STARTER_SLOTS`, `starter_ids_from_usage`, `select_skill_universe`, `anytime_td_probability`, `project_prediction_from_features`
- Produces:
  - `select_skill_universe` fills remaining per-team slots from usage after depth_team=1 (still skip ST slots). Existing depth starters remain.
  - `anytime_td_probability(expected_tds: float, *, dispersion: float | None = None) -> float`
  - `RB_TD_DISPERSION = 2.0`
  - Projector/calibration pass `dispersion=RB_TD_DISPERSION` when position is RB
  - Gameday phases add `anytime_td` after game_projections: `nfl_anytime_td_projector`, `nfl_anytime_td_betting` (schemes already synced daily; optional `nfl_sync_defense_schemes` is OK if cheap — include it for freshness)

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_nfl_anytime_td_model.py`:

```python
import math

from app.services.etl.nfl.anytime_td_model import (
    RB_TD_DISPERSION,
    anytime_td_probability,
)


def test_poisson_anytime_td_probability():
    assert anytime_td_probability(0.0) == 0.0
    p = anytime_td_probability(0.5)
    assert abs(p - (1.0 - math.exp(-0.5))) < 1e-12


def test_rb_negbin_is_below_poisson_for_same_lambda():
    lam = 0.6
    pois = anytime_td_probability(lam)
    nb = anytime_td_probability(lam, dispersion=RB_TD_DISPERSION)
    assert nb < pois
    assert 0.0 < nb < 1.0
```

In `test_nfl_anytime_td_feature_assembly.py` add (usage must include a second WR with touches ≥ 3 not on the depth chart):

```python
def test_select_universe_fills_wr_and_rb_slots_from_usage():
    depth = [
        {
            "gsis_id": "qb1",
            "full_name": "QB One",
            "position": "QB",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "QB",
            "week": 3,
        },
        {
            "gsis_id": "rb1",
            "full_name": "Star RB",
            "position": "RB",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 3,
        },
        {
            "gsis_id": "wr1",
            "full_name": "Star WR",
            "position": "WR",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "WR",
            "week": 3,
        },
    ]
    usage = aggregate_player_usage_from_weekly(_weekly_sample(), as_of_week=3)
    usage["wr2"] = {
        "player_id": "wr2",
        "player_name": "WR Two",
        "position": "WR",
        "team_abbr": "KC",
        "touches_season": 20.0,
        "targets_l3": 18.0,
        "carries_l3": 0.0,
    }
    usage["rb_committee"] = {
        "player_id": "rb_committee",
        "player_name": "RB Two",
        "position": "RB",
        "team_abbr": "KC",
        "touches_season": 25.0,
        "targets_l3": 4.0,
        "carries_l3": 12.0,
    }
    universe = select_skill_universe(depth_records=depth, usage_by_player=usage, week=3)
    ids = {p["player_id"] for p in universe}
    assert "wr1" in ids
    assert "wr2" in ids
    assert "rb1" in ids
    assert "rb_committee" in ids
```

`test_select_universe_starters_only_from_depth` must still exclude `wr_kr`. `rb2` stays excluded unless present in usage with enough touches (current weekly sample should keep this assertion).

Gameday catalog test: assert `nfl.anytime_td_projector` and `nfl.anytime_td_betting` in `NFL_GAMEDAY_AVAILABILITY_PHASES` flat names.

Projector unit: if `test_nfl_anytime_td_projector.py` exists, add RB probability < Poisson for same λ via `project_prediction_from_features` with position RB.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_anytime_td_model.py tests/test_nfl_anytime_td_feature_assembly.py::test_select_universe_fills_wr_and_rb_slots_from_usage -q`

Expected: FAIL

- [ ] **Step 3: Implement**

`anytime_td_probability`:

```python
RB_TD_DISPERSION = 2.0


def anytime_td_probability(
    expected_tds: float, *, dispersion: float | None = None
) -> float:
    lam = max(0.0, float(expected_tds))
    if dispersion is not None and dispersion > 0:
        r = float(dispersion)
        prob = 1.0 - (r / (r + lam)) ** r
    else:
        prob = 1.0 - math.exp(-lam)
    return min(1.0, max(0.0, prob))
```

`select_skill_universe`: after the depth branch (when universe is non-empty), for each team in universe, count current players by position; for missing slots up to `_USAGE_STARTER_SLOTS`, add players from `starter_ids_from_usage` / ranked usage who are not already in `universe`. Reuse the same scoring as `starter_ids_from_usage`. Do not add KR/PR via usage (usage is already skill-position filtered).

`project_prediction_from_features`: read `position` from row; if RB, pass `dispersion=RB_TD_DISPERSION` into `anytime_td_probability`. Update `anytime_td_calibration.hierarchical_probability` similarly so GBM input `hier_p` matches.

Gameday phases:

```python
NFL_GAMEDAY_AVAILABILITY_PHASES = [
    ("predictions", [nfl_qb_weekly, nfl_kickers]),
    ("game_projections", [nfl_spread_projector, nfl_totals_projector]),
    (
        "anytime_td",
        [
            nfl_sync_defense_schemes,
            nfl_anytime_td_projector,
            nfl_anytime_td_betting,
        ],
    ),
]
```

- [ ] **Step 4: Run tests**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_anytime_td_model.py tests/test_nfl_anytime_td_feature_assembly.py tests/test_nfl_anytime_td_projector.py tests/test_nfl_anytime_td_calibration.py tests/test_nfl_anytime_td_celery_catalog.py tests/test_nfl_pipeline_phases.py -q`

Expected: PASS. If calibration tests construct Poisson by hand, update them to the new signature.

- [ ] **Step 5: Black + commit**

```bash
cd backend && python3 -m black app/services/etl/nfl/anytime_td_model.py app/services/etl/nfl/anytime_td_features.py app/services/etl/nfl/anytime_td_projector.py app/services/etl/nfl/anytime_td_calibration.py tests/test_nfl_anytime_td_model.py tests/test_nfl_anytime_td_feature_assembly.py
git add backend/app/services/etl/nfl/anytime_td_model.py backend/app/services/etl/nfl/anytime_td_features.py backend/app/services/etl/nfl/anytime_td_projector.py backend/app/services/etl/nfl/anytime_td_calibration.py backend/app/tasks/etl_pipeline.py backend/tests/test_nfl_anytime_td_model.py backend/tests/test_nfl_anytime_td_feature_assembly.py backend/tests/test_nfl_anytime_td_celery_catalog.py backend/docs/NFL_ANYTIME_TD.md
git commit -m "$(cat <<'EOF'
feat(nfl): fill ATD starter slots, overdisperse RBs, refresh ATD on gameday

Depth-only boards dropped WR2/RB2; Poisson overstated committee RBs. Gameday availability now rebuilds the anytime-TD slate after QB status locks.
EOF
)"
```

---

### Task 4: Kicker live weather + real volume inputs

**Files:**
- Create: `backend/app/services/etl/nfl/kicker_weather.py`
- Create: `backend/tests/test_nfl_kicker_weather.py`
- Modify: `backend/app/services/etl/nfl/kickers.py` (replace `weather_integration` import and hardcoded 82/35/0.80)
- Modify: `backend/app/services/etl/nfl/kicker_volume.py` (`weather_make_multiplier`)
- Modify: `backend/tests/test_nfl_kicker_attempts.py` (or new tests in `test_nfl_kicker_weather.py`)
- Modify: `backend/docs/NFL_ML_OPS.md` kicker blend section (one sentence: weather from `pred_nfl_weather`)

**Interfaces:**
- Consumes: `NFLWeather` columns `temperature`, `wind_speed`, `venue_name`; kicker_data keys already built in `kickers.py` (`career_fg_percentage` if present, else use `fg_percentage` / `made`/`attempts`)
- Produces:
  - `weather_dict_from_nfl_row(row) -> dict | None` with keys `temperature`, `wind_speed`
  - `kicker_stat_inputs(kicker_data: Mapping) -> dict` with `career_fg_percentage`, `total_attempts`, `recent_form` from the row (defaults 82 / 35 / 0.80 only when keys missing)
  - `weather_make_multiplier(*, wind_speed: float | None, temperature: float | None, is_dome: bool) -> float` clamped `[0.85, 1.05]`; dome → 1.0; wind > 18 → 0.95; temp < 32 → 0.97
  - `kickers.py` uses these helpers; never `from weather_integration import ...`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_nfl_kicker_weather.py`:

```python
from types import SimpleNamespace

from app.services.etl.nfl.kicker_weather import (
    kicker_stat_inputs,
    weather_dict_from_nfl_row,
    weather_make_multiplier,
)


def test_weather_dict_from_nfl_row():
    row = SimpleNamespace(temperature=41.0, wind_speed=22.0, venue_name="Highmark Stadium")
    out = weather_dict_from_nfl_row(row)
    assert out == {"temperature": 41.0, "wind_speed": 22.0}


def test_kicker_stat_inputs_prefers_row_over_league_defaults():
    out = kicker_stat_inputs(
        {
            "career_fg_percentage": 91.2,
            "total_attempts": 88,
            "recent_form": 0.93,
        }
    )
    assert out["career_fg_percentage"] == 91.2
    assert out["total_attempts"] == 88
    assert out["recent_form"] == 0.93


def test_kicker_stat_inputs_defaults_when_missing():
    out = kicker_stat_inputs({})
    assert out["career_fg_percentage"] == 82
    assert out["total_attempts"] == 35
    assert out["recent_form"] == 0.80


def test_weather_make_multiplier_dome_neutral():
    assert weather_make_multiplier(wind_speed=30.0, temperature=10.0, is_dome=True) == 1.0


def test_weather_make_multiplier_wind_reduces():
    calm = weather_make_multiplier(wind_speed=5.0, temperature=60.0, is_dome=False)
    windy = weather_make_multiplier(wind_speed=22.0, temperature=60.0, is_dome=False)
    assert windy < calm
    assert 0.85 <= windy <= 1.05
```

Add a test that `kickers.py` source does not contain `weather_integration`:

```python
from pathlib import Path

def test_kickers_module_does_not_import_weather_integration():
    text = Path("app/services/etl/nfl/kickers.py").read_text()
    assert "weather_integration" not in text
```

(Run from `backend/` so the relative path works; prefer importing the module file via `Path(__file__).resolve().parents[1] / "app/services/etl/nfl/kickers.py"`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_kicker_weather.py -q`

Expected: FAIL

- [ ] **Step 3: Implement**

Create `kicker_weather.py` with the three functions. `weather_make_multiplier`: start at 1.0; if `is_dome`: return 1.0; if wind_speed is not None and > 18: multiply 0.95; if temperature is not None and < 32: multiply 0.97; clamp to `[0.85, 1.05]`.

In `kicker_volume.mixture_make_probability` / `estimate_attempts_heuristic`, if weather_data provided, multiply make% by `weather_make_multiplier` (attempts heuristic already has wind/temp terms — leave those; apply make% multiplier only in `mixture_make_probability` via existing `weather_mult` argument: `kickers.py` should pass `weather_mult=weather_make_multiplier(...)`).

In `kickers.py` replace the `weather_integration` try/except with: query `NFLWeather` by `venue_name` if SessionLocal is already in play, else leave `weather_data=None`. Do not add a new Celery job. Build `enhanced_kicker_data = kicker_stat_inputs(kicker_data)` instead of the hardcoded dict. Map kicker_data fields: if `career_fg_percentage` absent, use `fg_pct` or `fg_percentage`; if `total_attempts` absent, use `fg_attempts` or `attempts`.

- [ ] **Step 4: Run tests**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_kicker_weather.py tests/test_nfl_kicker_attempts.py tests/test_nfl_kicker_blend_tune.py tests/test_nfl_collect_kicker_actuals.py -q`

Expected: PASS

- [ ] **Step 5: Black + commit**

```bash
cd backend && python3 -m black app/services/etl/nfl/kicker_weather.py app/services/etl/nfl/kickers.py app/services/etl/nfl/kicker_volume.py tests/test_nfl_kicker_weather.py
git add backend/app/services/etl/nfl/kicker_weather.py backend/app/services/etl/nfl/kickers.py backend/app/services/etl/nfl/kicker_volume.py backend/tests/test_nfl_kicker_weather.py backend/docs/NFL_ML_OPS.md
git commit -m "$(cat <<'EOF'
fix(nfl): drive kicker volume with live weather and the kicker's own stats

The dead weather_integration import always failed, and the statistical path hardcoded league-average make rate. Use pred_nfl_weather and the row's career/form numbers.
EOF
)"
```

---

## Self-review

1. Spec coverage: (1) line-as-mean + disagreement PASS (2) 14-day horizon + 3.5 QB-out + TNF/Sat Beat (3) WR/RB slot fill + RB NegBin + gameday ATD (4) kicker weather + real stats. No Monte Carlo / UI flags / OpenAPI.
2. Placeholders: none.
3. Types: `published_qb_yards` → `(float, str)`; `qb_out_margin_adjustment` kwargs; `anytime_td_probability(..., dispersion=)`; `GAME_LINES_HORIZON_DAYS` shared.
4. Task 2 gameday phases omit ATD; Task 3 adds them — no conflict if Task 3 replaces the full list.
5. Existing `test_enrich_shadow_stores_ml_when_disabled` has no line context and must stay 245 / tier-v3.
6. Existing `test_betting_recommendation_ml_agreement` still OVER.
