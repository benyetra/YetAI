# NFL Regular-Season Readiness + Game Projections v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 2026 NFL prop pipeline correctness and ship NBA-shaped Elo spread + PPG totals game projections on `/predictions/nfl` before Week 1.

**Architecture:** Track A hardens season/week, kickoff dates, and prop hygiene. Track B adds `pred_nfl_game_lines` + Elo (seeded from nflverse REG 2023–2025) spread/totals projectors, Celery phases, API `spreads`/`totals`, and FE merge. Reuse `_spread_model.py` with `NFL_CONFIG`.

**Tech Stack:** Python 3, FastAPI/SQLAlchemy/Alembic, Celery, nfl-data-py, Odds API, Next.js/TS, pytest, Black.

**Spec reference:** `docs/superpowers/specs/2026-08-10-nfl-regular-season-readiness-design.md`

## Global Constraints

- `DEFAULT_NFL_SEASON = 2026`; env override via `NFL_SEASON`.
- NFL Elo HFA `home_court_advantage = 2.5`; `edge_threshold = 3.0`.
- Elo seed seasons: nflverse REG **2023, 2024, 2025** only (no PRE/POST).
- Game board response keys: `spreads` + `totals` (NBA shape); FE uses `mergeSpreadTotalsGameProjections`.
- Unique game keys: `(game_date, home_team_name, away_team_name)`.
- No Monte Carlo, no preseason product surface, no rushing props, no player-availability XGB in this plan.
- Before each Python commit: `cd backend && python3 -m black <touched>` and targeted pytest; full `pytest -q` before push.
- Stage specific paths only; no `git add .`.

## File map

| Path | Responsibility |
|------|----------------|
| `backend/app/services/etl/nfl/nfl_common.py` | Season/week defaults |
| `backend/app/services/etl/nfl/team_names.py` | Odds API ↔ nflverse ↔ display normalizer |
| `backend/app/services/etl/nfl/qb_dynamic.py` | REG filter + kickoff `game_date` |
| `backend/app/services/etl/nfl/qb_betting.py` | Fix dead heroku import |
| `backend/app/services/etl/nfl/kickers.py` | Season from `get_nfl_season()` |
| `backend/app/services/etl/_spread_model.py` | Add `NFL_CONFIG` |
| `backend/app/services/etl/nfl/seed_elo.py` | Seed Elo from nflverse history |
| `backend/app/services/etl/nfl/update_game_lines.py` | Odds → `pred_nfl_game_lines` |
| `backend/app/services/etl/nfl/spread_projector.py` | Elo + PPG overlay spreads |
| `backend/app/services/etl/nfl/totals_projector.py` | PPG matchup totals |
| `backend/app/services/etl/nfl/store_game_actuals.py` | Finals → spread/totals actuals + Elo update |
| `backend/app/models/predictions_models.py` | NFL game projection models |
| `backend/alembic/versions/2026_08_10_nfl_game_projections.py` | Migration |
| `backend/app/tasks/etl_pipeline.py` | Extended `NFL_PHASES` + celery tasks |
| `backend/app/api/v1/predictions.py` | Return spreads/totals |
| `backend/app/services/nfl_accuracy_service.py` | ATS / totals O/U buckets |
| `frontend/src/lib/gameProjectionsFromApi.ts` | NFL merge path |
| `backend/.env.example` | Document `NFL_SEASON` |
| `backend/docs/NFL_ETL_PARITY.md` | Pipeline/docs sync |
| `backend/tests/test_nfl_*.py` | Unit coverage |

---

### Task 1: Season default + nfl_common tests

**Files:**
- Modify: `backend/app/services/etl/nfl/nfl_common.py`
- Modify: `backend/tests/test_nfl_common.py`
- Modify: `backend/.env.example` (add `NFL_SEASON=2026` comment block if missing)

**Interfaces:**
- Consumes: env `NFL_SEASON`
- Produces: `DEFAULT_NFL_SEASON == 2026`; `get_nfl_season()` / `get_current_nfl_week()` unchanged signatures

- [ ] **Step 1: Update failing expectation in tests**

```python
# backend/tests/test_nfl_common.py — change default assertion and add 2026 week cases

def test_get_nfl_season_default(monkeypatch):
    monkeypatch.delenv("NFL_SEASON", raising=False)
    assert nfl_common.get_nfl_season() == 2026
    assert nfl_common.DEFAULT_NFL_SEASON == 2026


def test_week_before_2026_kickoff_is_week_one():
    # 2026 Labor Day is Mon Sep 7 → first Thursday Sep 10
    assert nfl_common.get_current_nfl_week(season=2026, today=date(2026, 8, 10)) == 1
    assert nfl_common.get_current_nfl_week(season=2026, today=date(2026, 9, 9)) == 1


def test_week_after_2026_kickoff():
    assert nfl_common.get_current_nfl_week(season=2026, today=date(2026, 9, 17)) == 2
```

- [ ] **Step 2: Run tests — expect default test FAIL if still 2025**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_common.py -q`
Expected: FAIL on `DEFAULT_NFL_SEASON == 2026` until Step 3

- [ ] **Step 3: Bump default**

```python
# nfl_common.py
DEFAULT_NFL_SEASON = 2026
```

Add to `backend/.env.example`:

```bash
# NFL calendar year the regular season starts in (September). Override in prod if needed.
# NFL_SEASON=2026
```

- [ ] **Step 4: Re-run tests — PASS**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_common.py -q`

- [ ] **Step 5: Black + commit**

```bash
cd backend && python3 -m black app/services/etl/nfl/nfl_common.py tests/test_nfl_common.py
git add backend/app/services/etl/nfl/nfl_common.py backend/tests/test_nfl_common.py backend/.env.example
git commit -m "fix(nfl): default season year to 2026"
```

---

### Task 2: Prop hygiene — kickoff dates, REG filter, kicker season, dead import

**Files:**
- Modify: `backend/app/services/etl/nfl/qb_dynamic.py`
- Modify: `backend/app/services/etl/nfl/qb_betting.py`
- Modify: `backend/app/services/etl/nfl/kickers.py`
- Create: `backend/tests/test_nfl_prop_hygiene.py`

**Interfaces:**
- Consumes: `nfl.import_schedules`, `get_nfl_season`
- Produces:
  - `get_team_opponent(...)` filters `game_type == "REG"` (or column equivalent)
  - `get_game_kickoff(team_abbr, season, week) -> datetime | None`
  - QB rows write `game_date` from kickoff (fallback: noon ET on computed Thursday of that week if missing)
  - `get_team_statistics(..., season_year=None)` uses `get_nfl_season()` when None
  - `qb_betting` empty-path calls `from app.services.etl.nfl.qb_dynamic import main` (or `run`) — never `qb_dynamic_heroku`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_nfl_prop_hygiene.py
from datetime import datetime
from unittest.mock import MagicMock, patch
import pandas as pd

from app.services.etl.nfl import kickers, qb_dynamic


def test_get_team_opponent_ignores_preseason_rows():
    df = pd.DataFrame(
        [
            {
                "week": 1,
                "game_type": "PRE",
                "home_team": "KC",
                "away_team": "CHI",
                "gameday": "2026-08-15",
                "gametime": "20:00",
            },
            {
                "week": 1,
                "game_type": "REG",
                "home_team": "KC",
                "away_team": "BAL",
                "gameday": "2026-09-10",
                "gametime": "20:20",
            },
        ]
    )
    with patch("app.services.etl.nfl.qb_dynamic.nfl.import_schedules", return_value=df):
        assert qb_dynamic.get_team_opponent("KC", 2026, 1) == "BAL"


def test_get_game_kickoff_parses_reg_datetime():
    df = pd.DataFrame(
        [
            {
                "week": 1,
                "game_type": "REG",
                "home_team": "KC",
                "away_team": "BAL",
                "gameday": "2026-09-10",
                "gametime": "20:20",
            }
        ]
    )
    with patch("app.services.etl.nfl.qb_dynamic.nfl.import_schedules", return_value=df):
        kickoff = qb_dynamic.get_game_kickoff("KC", 2026, 1)
        assert kickoff is not None
        assert kickoff.date().isoformat() == "2026-09-10"


def test_get_team_statistics_default_uses_get_nfl_season(monkeypatch):
    monkeypatch.setattr(kickers, "get_nfl_season", lambda: 2026)
    called = {}

    def fake_get(url, timeout=30):
        called["url"] = url
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = {"splits": {"categories": []}}
        return m

    with patch("app.services.etl.nfl.kickers.requests.get", side_effect=fake_get):
        kickers.get_team_statistics(1)  # no season_year
    assert "/seasons/2026/" in called["url"]
```

- [ ] **Step 2: Run — FAIL (missing helpers / wrong defaults)**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_prop_hygiene.py -q`

- [ ] **Step 3: Implement**

In `qb_dynamic.py`:
- Filter schedules with `(schedules["game_type"] == "REG")` when column exists
- Add `get_game_kickoff(team_abbr, season, week) -> datetime | None` combining `gameday` + `gametime` (treat as local US; store naive or UTC consistently with other NFL datetime columns — match existing `QBPredictions.game_date` usage)
- On create/update prediction set `game_date=get_game_kickoff(...) or fallback`

In `kickers.py`:
- `from app.services.etl.nfl.nfl_common import get_nfl_season`
- `def get_team_statistics(team_id, season_year=None, season_type=2):` then `season_year = season_year or get_nfl_season()`
- Ensure callers of 3rd-down / yards-allowed pass season or rely on new default

In `qb_betting.py` empty path:

```python
from app.services.etl.nfl.qb_dynamic import main as generate_dynamic_predictions
```

(If module exposes `run` instead of `main`, use that — inspect and match.)

- [ ] **Step 4: Tests PASS + black + commit**

```bash
cd backend && python3 -m black app/services/etl/nfl/qb_dynamic.py app/services/etl/nfl/qb_betting.py app/services/etl/nfl/kickers.py tests/test_nfl_prop_hygiene.py
git add backend/app/services/etl/nfl/qb_dynamic.py backend/app/services/etl/nfl/qb_betting.py backend/app/services/etl/nfl/kickers.py backend/tests/test_nfl_prop_hygiene.py
git commit -m "fix(nfl): REG schedules, kickoff game_date, kicker season, betting import"
```

---

### Task 3: NFL_CONFIG + team name normalizer + Elo seed (pure logic)

**Files:**
- Modify: `backend/app/services/etl/_spread_model.py`
- Create: `backend/app/services/etl/nfl/team_names.py`
- Create: `backend/app/services/etl/nfl/seed_elo.py`
- Create: `backend/tests/test_nfl_elo_seed.py`
- Create: `backend/tests/test_nfl_team_names.py`

**Interfaces:**
- Consumes: `_spread_model.load_elos_from_actuals`, `update_elo`
- Produces:
  - `NFL_CONFIG = SpreadLeagueConfig(home_court_advantage=2.5, edge_threshold=3.0)`
  - `normalize_team_name(name: str) -> str`
  - `seed_elos_from_games(games: Sequence[SpreadActualRow], *, cfg=NFL_CONFIG) -> dict[str, float]`
  - `fetch_reg_games_nflverse(seasons: list[int]) -> list[SimpleNamespace]` (home/away names + scores) — may be mocked in unit tests

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_nfl_team_names.py
from app.services.etl.nfl.team_names import normalize_team_name

def test_normalize_common_aliases():
    assert normalize_team_name("LA Rams") == "Los Angeles Rams"
    assert normalize_team_name("Washington Football Team") == "Washington Commanders"
    assert normalize_team_name("Washington Commanders") == "Washington Commanders"


# backend/tests/test_nfl_elo_seed.py
from types import SimpleNamespace
from app.services.etl._spread_model import NFL_CONFIG
from app.services.etl.nfl.seed_elo import seed_elos_from_games

def test_nfl_config_thresholds():
    assert NFL_CONFIG.home_court_advantage == 2.5
    assert NFL_CONFIG.edge_threshold == 3.0

def test_seed_elos_from_chronological_games():
    games = [
        SimpleNamespace(
            home_team_name="Kansas City Chiefs",
            away_team_name="Baltimore Ravens",
            home_score=27,
            away_score=20,
        ),
        SimpleNamespace(
            home_team_name="Baltimore Ravens",
            away_team_name="Kansas City Chiefs",
            home_score=10,
            away_score=17,
        ),
    ]
    elos = seed_elos_from_games(games)
    assert elos["Kansas City Chiefs"] > elos["Baltimore Ravens"]
    assert abs(sum(elos.values()) - 2 * 1500) < 1e-6  # zero-sum updates from 1500
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement**

```python
# _spread_model.py — add near NBA_CONFIG
NFL_CONFIG = SpreadLeagueConfig(home_court_advantage=2.5, edge_threshold=3.0)
```

`team_names.py`: dict map for Odds/nflverse aliases → canonical full names used in projections (include LA Rams/Chargers, NY Giants/Jets, Washington variants).

`seed_elo.py`:

```python
def seed_elos_from_games(games, *, cfg=NFL_CONFIG) -> dict[str, float]:
    return load_elos_from_actuals(games, cfg=cfg)

def fetch_reg_games_nflverse(seasons: list[int] | None = None) -> list:
    """Load completed REG games; normalize team names; skip missing scores."""
    ...
```

- [ ] **Step 4: Tests PASS + commit**

```bash
git commit -m "feat(nfl): Elo config, team name normalizer, seed helpers"
```

---

### Task 4: SQLAlchemy models + Alembic migration

**Files:**
- Modify: `backend/app/models/predictions_models.py` (add NFL game projection section near existing NFL models)
- Create: `backend/alembic/versions/2026_08_10_nfl_game_projections.py`
- Create: `backend/tests/test_nfl_game_models_import.py`

**Interfaces:**
- Produces models:
  - `NFLGameLines` → `pred_nfl_game_lines`
  - `NFLSpreadProjections` → `pred_nfl_spread_projections`
  - `NFLTotalsProjections` → `pred_nfl_totals_projections`
  - `NFLSpreadActuals` → `pred_nfl_spread_actuals`
  - `NFLTotalsActuals` → `pred_nfl_totals_actuals`
  - `NFLTeamElo` → `pred_nfl_team_elo` (`team_name` PK/unique, `elo`, `as_of_date`, `updated_at`)

Mirror NBA column sets for lines/spreads/totals/actuals. Totals projection fields needed by FE merge (match NBA totals row keys used in `mergeSpreadTotalsGameProjections` / `spreadTotalsProjectionDisplay`): include `projected_total`, `home_projected_runs`/`away_projected_runs` **or** the exact NBA field names the merge already reads — **inspect `frontend/src/lib/mergeSpreadTotalsGameProjections.ts` and NBA totals model and match those keys in API serialization** (prefer identical Python attribute names to NBA for `_query_recent` dict conversion).

- [ ] **Step 1: Failing import test**

```python
def test_nfl_game_models_importable():
    from app.models.predictions_models import (
        NFLGameLines,
        NFLSpreadProjections,
        NFLTotalsProjections,
        NFLSpreadActuals,
        NFLTotalsActuals,
        NFLTeamElo,
    )
    assert NFLGameLines.__tablename__ == "pred_nfl_game_lines"
    assert NFLTeamElo.__tablename__ == "pred_nfl_team_elo"
```

- [ ] **Step 2: Implement models + migration (revision after current head)**

Inspect `cd backend && .venv/bin/alembic heads` and chain `down_revision` correctly.

- [ ] **Step 3: Tests + black + commit**

```bash
git commit -m "feat(nfl): game lines and projection tables"
```

---

### Task 5: update_game_lines + spread + totals projectors

**Files:**
- Create: `backend/app/services/etl/nfl/update_game_lines.py`
- Create: `backend/app/services/etl/nfl/spread_projector.py`
- Create: `backend/app/services/etl/nfl/totals_projector.py`
- Create: `backend/tests/test_nfl_spread_projector.py`
- Create: `backend/tests/test_nfl_totals_projector.py`
- Create: `backend/tests/test_nfl_update_game_lines.py`

**Interfaces:**
- Consumes: Odds API via `sync_odds_get`, `NFL_CONFIG`, `NFLGameLines`, `NFLTeamElo`, team PPG helper
- Produces:
  - `update_game_lines.run() -> dict` sport key `americanfootball_nfl`
  - `spread_projector.run() -> dict` writes `NFLSpreadProjections`
  - `totals_projector.run() -> dict` writes `NFLTotalsProjections`
  - PPG overlay: load team points for/against from nflverse (or from seeded actuals averages); use `_spread_model.pace_overlay_adjustment` with PPG as off/def inputs
  - Totals: `(home_off + away_def)/2` style blend → align scores to projected margin:
    ```python
    # after margin m and total t:
    home_pts = (t + m) / 2
    away_pts = (t - m) / 2
    ```
  - Edge/recommendation via `spread_recommendation(..., cfg=NFL_CONFIG)`; totals edge threshold: recommend OVER/UNDER when `|proj - market| >= 3.0`, else NO_PLAY

Port structure from `backend/app/services/etl/nba/update_game_lines.py` and `nba/spread_projector.py` (Elo path only — skip ML). Keep NFL modules focused and smaller than WNBA totals.

- [ ] **Step 1: Unit tests with mocked DB / Odds**

Cover: normalize team names on ingest; spread HOME/AWAY at ±3.0 edge; totals score alignment identity `home+away == total` and `home-away == margin`.

- [ ] **Step 2: Implement modules**

- [ ] **Step 3: Tests PASS + commit**

```bash
git commit -m "feat(nfl): game lines, spread and totals projectors"
```

---

### Task 6: store_game_actuals + Celery phases + Elo seed task

**Files:**
- Create: `backend/app/services/etl/nfl/store_game_actuals.py`
- Modify: `backend/app/tasks/etl_pipeline.py`
- Modify: `backend/docs/NFL_ETL_PARITY.md`
- Create: `backend/tests/test_nfl_pipeline_phases.py`

**Interfaces:**
- Produces Celery tasks:
  - `app.tasks.etl_pipeline.nfl.update_game_lines`
  - `app.tasks.etl_pipeline.nfl.spread_projector`
  - `app.tasks.etl_pipeline.nfl.totals_projector`
  - `app.tasks.etl_pipeline.nfl.store_game_actuals`
  - `app.tasks.etl_pipeline.nfl.seed_elo_history` (one-off)
- `NFL_PHASES` order:
  1. actuals: qb + kicker + `nfl_store_game_actuals`
  2. game_lines: `nfl_update_game_lines`
  3. game_projections: spread + totals
  4. predictions: yetiwatch + qb_weekly + kickers

`store_game_actuals.run()`: for recently completed REG games (nflverse or ESPN), upsert spread/totals actuals; update `NFLTeamElo` via `update_elo`.

`seed_elo_history.run()`: `fetch_reg_games_nflverse([2023,2024,2025])` → write actuals chronologically OR compute elos and upsert `NFLTeamElo`.

- [ ] **Step 1: Test phase list includes new task names**

```python
from app.tasks.etl_pipeline import NFL_PHASES

def test_nfl_phases_include_game_board():
    names = [phase for phase, _ in NFL_PHASES]
    assert "game_lines" in names
    assert "game_projections" in names
    flat = [t.name for _, tasks in NFL_PHASES for t in tasks]
    assert "app.tasks.etl_pipeline.nfl.update_game_lines" in flat
    assert "app.tasks.etl_pipeline.nfl.spread_projector" in flat
```

- [ ] **Step 2: Implement + docs update (Beat already scheduled; remove stale “Not on Beat” wording)**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(nfl): wire game projection phases into Celery pipeline"
```

---

### Task 7: API spreads/totals + accuracy buckets + OpenAPI

**Files:**
- Modify: `backend/app/api/v1/predictions.py` (`nfl_predictions`)
- Modify: `backend/app/services/nfl_accuracy_service.py`
- Create: `backend/tests/test_nfl_api_route.py`
- Create: `backend/tests/test_nfl_accuracy_game_buckets.py`
- Regenerate: `docs/api/openapi*.json` via `scripts/export_openapi.py` if route schema changes

**Interfaces:**
- `GET /api/v1/predictions/nfl` returns keys: `qb_predictions`, `kicker_predictions`, `spreads`, `totals`
- Attach game times: `attach_game_times_from_lines(db, rows, NFLGameLines)`
- Docstring: QB passing + kickers + game lines (no rushing claim)
- Accuracy: add buckets for spread ATS and totals O/U when actuals exist (follow NBA/WNBA accuracy patterns if present; otherwise compute simple hit-rate in `nfl_accuracy_service`)

- [ ] **Step 1: Failing API test (mock DB query path like `test_wnba_api_route.py`)**

- [ ] **Step 2: Implement**

- [ ] **Step 3: Export OpenAPI + commit**

```bash
cd backend && PYTHONPATH=. .venv/bin/python scripts/export_openapi.py
git commit -m "feat(nfl): expose spreads and totals on predictions API"
```

---

### Task 8: Frontend merge + docs polish

**Files:**
- Modify: `frontend/src/lib/gameProjectionsFromApi.ts`
- Create or modify: `frontend/src/lib/__tests__/gameProjectionsFromApi.test.ts` (or existing test file)
- Modify: `backend/docs/NFL_ETL_PARITY.md` / `backend/docs/NFL_ML_OPS.md` if needed for game board env notes

**Interfaces:**
- `gameProjectionRows('nfl', data)` merges `data.spreads` + `data.totals`

- [ ] **Step 1: Failing FE unit test**

```ts
import { gameProjectionRows } from '@/lib/gameProjectionsFromApi';

test('nfl merges spreads and totals', () => {
  const rows = gameProjectionRows('nfl', {
    spreads: [
      {
        home_team: 'Kansas City Chiefs',
        away_team: 'Baltimore Ravens',
        home_win_prob: 0.62,
        projected_margin: 3.5,
        market_spread: -3.0,
        spread_edge: 0.5,
        spread_recommendation: 'HOME',
        game_time: '2026-09-10T00:20:00Z',
      },
    ],
    totals: [
      {
        home_team: 'Kansas City Chiefs',
        away_team: 'Baltimore Ravens',
        projected_total: 47.5,
        home_projected_runs: 25.5,
        away_projected_runs: 22.0,
        market_total: 48.5,
        edge_vs_market_total: -1.0,
        total_recommendation: 'UNDER',
      },
    ],
  });
  expect(rows.length).toBe(1);
  expect(rows[0].projected_total).toBe(47.5);
});
```

(Adjust field names to match real merge helper expectations — read `mergeSpreadTotalsGameProjections.ts` first.)

- [ ] **Step 2: Implement FE case**

```ts
case 'nfl':
  rows = mergeSpreadTotalsGameProjections(
    (data.spreads as Row[]) ?? [],
    (data.totals as Row[]) ?? [],
  );
  break;
```

- [ ] **Step 3: `cd frontend && npm run test:ci -- --testPathPattern=gameProjectionsFromApi` (or project-equivalent) + lint/type-check if touched TS**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(nfl): wire game projections merge on predictions page"
```

---

## Plan self-review

| Spec requirement | Task |
|------------------|------|
| DEFAULT 2026 + env docs | 1 |
| Kickoff game_date, REG filter, kicker season, heroku import | 2 |
| NFL_CONFIG 2.5 / 3.0, name normalizer, Elo seed 2023–25 | 3, 6 |
| Tables + migration | 4 |
| Game lines + spread + totals projectors | 5 |
| Celery phases + actuals + seed job | 6 |
| API spreads/totals + accuracy | 7 |
| FE merge | 8 |
| No MC / no preseason product | Global constraints |

No TBD placeholders. Types: `NFL_*` model names and Celery task names consistent across Tasks 4–7.
