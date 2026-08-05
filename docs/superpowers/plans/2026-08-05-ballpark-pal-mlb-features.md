# Ballpark Pal MLB Feature Injection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch and snapshot Ballpark Pal (BPP) MLB projections daily, then inject them as runtime priors into game/MC, strikeouts, and hits/HR so graded boards improve — without replacing Odds API or failing the slate when BPP is down.

**Architecture:** Thin sync HTTP client → idempotent snapshot tables → pure prior math → hooks in `run_projections_phase` (fetch first), `apply_monte_carlo_to_prediction`, strikeouts board path, and hits/HR scoring. Master switch `BALLPARK_PAL_ENABLED`; missing data = existing path unchanged. No daily `matchups/predict` fan-out.

**Tech Stack:** Python 3, FastAPI/SQLAlchemy/Alembic, Celery MLB ETL, `requests`, pytest, Black.

**Spec reference:** `docs/superpowers/specs/2026-08-05-ballpark-pal-mlb-features-design.md`

## Global Constraints

- Never commit `BALLPARK_PAL_API_KEY` or paste live keys into fixtures/docs/chat logs.
- BPP soft-fail only: projections phase must complete if BPP is disabled, unauthorized, rate-limited, or empty.
- BPP `odds` field is model-implied — never use as sportsbook prices; Odds API remains market side for EV.
- Today/future dates only (US Eastern); no historical BPP backfill.
- Daily batch uses `matchups?starters=true` only — not `matchups/predict`.
- F5 (`runsFirstFive`) not used in v1 game priors.
- Before each Python commit: `cd backend && python3 -m black . && python3 -m black --check .` and targeted pytest; full `pytest -q` before push.
- Stage specific paths only (`git add path`); no `git add .`.

## File map

| Path | Responsibility |
|------|----------------|
| `backend/app/services/ballpark_pal/__init__.py` | Package exports |
| `backend/app/services/ballpark_pal/client.py` | Sync HTTP client |
| `backend/app/services/ballpark_pal/config.py` | Enabled/key/weights helpers |
| `backend/app/services/ballpark_pal/models.py` | SQLAlchemy snapshot models |
| `backend/app/services/ballpark_pal/store.py` | Upsert snapshots + loaders |
| `backend/app/services/ballpark_pal/sync.py` | Daily fetch orchestration |
| `backend/app/services/ballpark_pal/priors.py` | Pure blend/shrink math |
| `backend/app/services/ballpark_pal/inject_game.py` | MC λ prior loader + apply |
| `backend/app/core/config.py` | `BALLPARK_PAL_API_KEY` on Settings |
| `backend/.env.example` | Document env vars (placeholder only) |
| `backend/alembic/versions/2026_08_05_bpp_snapshots.py` | Tables |
| `backend/app/services/etl/mlb/pipeline.py` | Call sync at start of projections |
| `backend/app/services/etl/mlb/monte_carlo.py` | Apply game run prior |
| `backend/app/services/etl/mlb/game_projection_pipeline.py` | `+bpp` on `model_version` |
| `backend/app/services/etl/mlb/lineup_utils.py` / `strikeouts.py` | K prior + source tag |
| `backend/app/services/etl/mlb/profiles/matchup_k.py` | Extend `MatchupSource` |
| `backend/app/services/etl/mlb/hits.py` | Hits/HR prior injection |
| `backend/docs/MLB_BALLPARK_PAL.md` | Ops doc |
| `backend/scripts/smoke_mlb_ballpark_pal.py` | Offline/mocked smoke |
| `backend/tests/test_mlb_ballpark_pal_*.py` | Client, store, sync, priors, MC, K, hits |
| `backend/tests/fixtures/ballpark_pal/` | Recorded JSON envelopes |

---

### Task 1: Config + HTTP client + fixtures

**Files:**
- Create: `backend/app/services/ballpark_pal/__init__.py`
- Create: `backend/app/services/ballpark_pal/config.py`
- Create: `backend/app/services/ballpark_pal/client.py`
- Create: `backend/tests/fixtures/ballpark_pal/error_unauthorized.json`
- Create: `backend/tests/test_mlb_ballpark_pal_client.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`

**Interfaces:**
- Consumes: `requests`, env
- Produces:
  - `ballpark_pal_enabled() -> bool`
  - `get_ballpark_pal_api_key() -> str | None`
  - `bpp_game_prior_weight() -> float` (default `0.30`)
  - `bpp_k_prior_weight() -> float` (default `0.25`)
  - `bpp_hits_prior_weight() -> float` (default `0.25`)
  - `bpp_hr_prior_weight() -> float` (default `0.25`)
  - `ballpark_pal_base_url() -> str`
  - `class BallparkPalClient` with `get`, `games`, `projections_averages`, `projections_probabilities`, `parkfactors`, `parkfactors_hitters`, `matchups`
  - Soft failure returns `None` (never raise into pipeline)

- [ ] **Step 1: Write failing client tests**

```python
# backend/tests/test_mlb_ballpark_pal_client.py
from pathlib import Path
from unittest.mock import MagicMock

FIX = Path(__file__).parent / "fixtures" / "ballpark_pal"


def _load(name: str) -> dict:
    import json

    return json.loads((FIX / name).read_text())


def test_games_parses_data_items():
    from app.services.ballpark_pal.client import BallparkPalClient

    payload = {
        "meta": {"asOf": "2026-08-05T12:00:00Z", "requestId": "r1"},
        "data": {
            "items": [{"gameId": 776345, "teamAwayId": 108, "teamHomeId": 136}]
        },
    }
    client = BallparkPalClient(api_key="test_key", session=MagicMock())
    resp = MagicMock(status_code=200)
    resp.json.return_value = payload
    resp.headers = {}
    client._session.get.return_value = resp
    out = client.games("2026-08-05")
    assert out is not None
    assert out["items"][0]["gameId"] == 776345


def test_unauthorized_returns_none_not_raise():
    from app.services.ballpark_pal.client import BallparkPalClient

    client = BallparkPalClient(api_key="bad", session=MagicMock())
    resp = MagicMock(status_code=401)
    resp.json.return_value = _load("error_unauthorized.json")
    resp.headers = {}
    client._session.get.return_value = resp
    assert client.games("2026-08-05") is None


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("BALLPARK_PAL_API_KEY", raising=False)
    monkeypatch.setenv("BALLPARK_PAL_ENABLED", "1")
    from app.services.ballpark_pal.config import (
        ballpark_pal_enabled,
        get_ballpark_pal_api_key,
    )

    assert get_ballpark_pal_api_key() is None
    assert ballpark_pal_enabled() is False
```

- [ ] **Step 2: Run tests — expect fail**

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_mlb_ballpark_pal_client.py -q
```

Expected: FAIL (module missing).

- [ ] **Step 3: Add Settings field + `.env.example`**

In `backend/app/core/config.py` next to `WEATHER_API_KEY`:

```python
BALLPARK_PAL_API_KEY: Optional[str] = None
```

In `backend/.env.example`:

```bash
# Ballpark Pal MLB projections (https://www.ballparkpal.com/api/docs/)
# BALLPARK_PAL_ENABLED=0
# BALLPARK_PAL_API_KEY=
# BPP_GAME_PRIOR_WEIGHT=0.30
# BPP_K_PRIOR_WEIGHT=0.25
# BPP_HITS_PRIOR_WEIGHT=0.25
# BPP_HR_PRIOR_WEIGHT=0.25
```

- [ ] **Step 4: Implement `config.py` and `client.py`**

```python
# backend/app/services/ballpark_pal/config.py
from __future__ import annotations

import os


def get_ballpark_pal_api_key() -> str | None:
    key = (os.getenv("BALLPARK_PAL_API_KEY") or "").strip()
    return key or None


def ballpark_pal_enabled() -> bool:
    flag = os.getenv("BALLPARK_PAL_ENABLED", "0").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    return get_ballpark_pal_api_key() is not None


def _weight(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        w = float(raw)
    except ValueError:
        return default
    return max(0.0, min(1.0, w))


def bpp_game_prior_weight() -> float:
    return _weight("BPP_GAME_PRIOR_WEIGHT", 0.30)


def bpp_k_prior_weight() -> float:
    return _weight("BPP_K_PRIOR_WEIGHT", 0.25)


def bpp_hits_prior_weight() -> float:
    return _weight("BPP_HITS_PRIOR_WEIGHT", 0.25)


def bpp_hr_prior_weight() -> float:
    return _weight("BPP_HR_PRIOR_WEIGHT", 0.25)


def ballpark_pal_base_url() -> str:
    return (
        os.getenv("BALLPARK_PAL_BASE_URL") or "https://www.ballparkpal.com/api/v1"
    ).rstrip("/")
```

```python
# backend/app/services/ballpark_pal/client.py
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.services.ballpark_pal.config import (
    ballpark_pal_base_url,
    get_ballpark_pal_api_key,
)

logger = logging.getLogger(__name__)


class BallparkPalClient:
    def __init__(
        self,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout: int = 30,
    ):
        self.api_key = (
            api_key if api_key is not None else get_ballpark_pal_api_key()
        )
        self._session = session or requests.Session()
        self.timeout = timeout
        self.base_url = ballpark_pal_base_url()

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        caller: str = "bpp",
    ) -> dict | None:
        if not self.api_key:
            logger.warning("BallparkPal skip %s: no API key", caller)
            return None
        url = f"{self.base_url}{path}"
        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        try:
            resp = self._session.get(
                url, params=params or {}, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            logger.warning("BallparkPal network error caller=%s: %s", caller, exc)
            return None
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "2") or 2)
            time.sleep(min(retry_after, 10))
            try:
                resp = self._session.get(
                    url, params=params or {}, headers=headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                logger.warning(
                    "BallparkPal retry failed caller=%s: %s", caller, exc
                )
                return None
        if resp.status_code >= 400:
            req_id = None
            try:
                body = resp.json()
                req_id = (body.get("error") or {}).get("requestId")
            except Exception:
                body = None
            logger.warning(
                "BallparkPal HTTP %s caller=%s requestId=%s",
                resp.status_code,
                caller,
                req_id,
            )
            return None
        try:
            body = resp.json()
        except ValueError:
            logger.warning("BallparkPal invalid JSON caller=%s", caller)
            return None
        if "error" in body:
            logger.warning(
                "BallparkPal error envelope caller=%s: %s",
                caller,
                body.get("error"),
            )
            return None
        return body.get("data", body)

    def games(self, date: str) -> dict | None:
        return self.get("/games", {"date": date}, caller="bpp.games")

    def projections_averages(self, game_id: int) -> dict | None:
        return self.get(
            "/projections/averages",
            {"gameId": game_id},
            caller="bpp.averages",
        )

    def projections_probabilities(self, game_id: int) -> dict | None:
        return self.get(
            "/projections/probabilities",
            {"gameId": game_id},
            caller="bpp.probs",
        )

    def parkfactors(self, date: str) -> dict | None:
        return self.get("/parkfactors", {"date": date}, caller="bpp.parkfactors")

    def parkfactors_hitters(
        self, *, date: str | None = None, game_id: int | None = None
    ) -> dict | None:
        params: dict[str, Any] = {}
        if date:
            params["date"] = date
        if game_id is not None:
            params["gameId"] = game_id
        return self.get("/parkfactors/hitters", params, caller="bpp.pf_hitters")

    def matchups(self, date: str, *, starters: bool = True) -> dict | None:
        params: dict[str, Any] = {"date": date}
        if starters:
            params["starters"] = "true"
        return self.get("/matchups", params, caller="bpp.matchups")
```

```python
# backend/app/services/ballpark_pal/__init__.py
from app.services.ballpark_pal.client import BallparkPalClient
from app.services.ballpark_pal.config import ballpark_pal_enabled

__all__ = ["BallparkPalClient", "ballpark_pal_enabled"]
```

Fixture `backend/tests/fixtures/ballpark_pal/error_unauthorized.json`:

```json
{
  "error": {
    "code": "unauthorized",
    "message": "Missing API key",
    "requestId": "test"
  }
}
```

- [ ] **Step 5: Re-run client tests**

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_mlb_ballpark_pal_client.py -q
```

Expected: PASS.

- [ ] **Step 6: Format + commit**

```bash
cd backend && python3 -m black app/services/ballpark_pal app/core/config.py tests/test_mlb_ballpark_pal_client.py
git add backend/app/services/ballpark_pal backend/app/core/config.py backend/.env.example backend/tests/test_mlb_ballpark_pal_client.py backend/tests/fixtures/ballpark_pal
git commit -m "$(cat <<'EOF'
feat(mlb): add Ballpark Pal client and config gates

Introduce sync HTTP client and env helpers so ETL can soft-fail when BPP is disabled or unavailable.
EOF
)"
```

---

### Task 2: Snapshot models + Alembic migration + store

**Files:**
- Create: `backend/app/services/ballpark_pal/models.py`
- Create: `backend/app/services/ballpark_pal/store.py`
- Create: `backend/alembic/versions/2026_08_05_bpp_snapshots.py`
- Create: `backend/tests/test_mlb_ballpark_pal_store.py`
- Modify: `backend/alembic/env.py` (import models for metadata)

**Interfaces:**
- Consumes: `Base` from `app.core.database`
- Produces tables + store API:
  - `upsert_game_snapshot(session, slate_date, bpp_game_id, **, averages, probabilities) -> None`
  - `upsert_player_projs(session, slate_date, bpp_game_id, rows: list[dict]) -> int`
  - `upsert_park_factors(session, ...) -> int`
  - `upsert_matchups(session, ...) -> int`
  - `load_game_snapshot(session, game_pk, slate_date)`
  - `load_player_proj(session, player_id, slate_date, role)`
  - `load_matchup(session, batter_id, pitcher_id, slate_date)`
  - `load_hitter_park_factor(session, player_id, slate_date, bpp_game_id=None)`

**Schema:**

`bpp_game_snapshots`: `id`, `slate_date`, `bpp_game_id`, `game_pk` (nullable), `team_away_id`, `team_home_id`, `as_of`, `averages_json`, `probabilities_json`, timestamps; unique `(slate_date, bpp_game_id)`.

`bpp_player_proj_snapshots`: `id`, `slate_date`, `bpp_game_id`, `game_pk`, `player_id`, `team_id`, `role` (`batter`|`pitcher`|`team`), `averages_json`, `selected_probs_json`; unique `(slate_date, bpp_game_id, player_id, role)`. For `role=team`, set `player_id = team_id`.

`bpp_park_factor_snapshots`: `id`, `slate_date`, `bpp_game_id`, `game_pk`, `scope` (`game`|`hitter`), `player_id` (0 for game), `factors_json`; unique `(slate_date, bpp_game_id, scope, player_id)`.

`bpp_matchup_snapshots`: `id`, `slate_date`, `bpp_game_id`, `game_pk`, `batter_id`, `pitcher_id`, `probs_json`; unique `(slate_date, batter_id, pitcher_id)`.

**ID mapping (v1):** set `game_pk = bpp_game_id` (MLB StatsAPI-aligned). Log if future mismatch detected; do not invent joins.

- [ ] **Step 1: Write store upsert test** (follow pattern in `tests/test_mlb_matchup_source_persist.py` — in-memory or session fixture). Upsert twice; assert single row and updated JSON.

- [ ] **Step 2: Run — expect fail**

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_mlb_ballpark_pal_store.py -q
```

- [ ] **Step 3: Implement models + migration**

Verify head before writing:

```bash
cd backend && .venv/bin/alembic heads
```

Set `down_revision` to current head (expected `20260805_pitcher_arch` at plan time).

```python
# alembic/env.py
from app.services.ballpark_pal import models as bpp_models  # noqa: F401
```

- [ ] **Step 4: Implement `store.py`** with idempotent upserts (select-by-unique then update, or `ON CONFLICT` if using Postgres dialect helpers already in repo).

- [ ] **Step 5: Tests pass + Black + commit**

```bash
cd backend && python3 -m black app/services/ballpark_pal alembic/versions/2026_08_05_bpp_snapshots.py tests/test_mlb_ballpark_pal_store.py
git add backend/app/services/ballpark_pal backend/alembic/versions/2026_08_05_bpp_snapshots.py backend/tests/test_mlb_ballpark_pal_store.py backend/alembic/env.py
git commit -m "$(cat <<'EOF'
feat(mlb): add Ballpark Pal snapshot tables and store

Persist daily BPP game, player, park-factor, and matchup payloads for priors and future retrain.
EOF
)"
```

---

### Task 3: Daily sync + pipeline hook

**Files:**
- Create: `backend/app/services/ballpark_pal/sync.py`
- Create: `backend/tests/test_mlb_ballpark_pal_sync.py`
- Modify: `backend/app/services/etl/mlb/pipeline.py`

**Interfaces:**
- Consumes: `BallparkPalClient`, store upserts, `ballpark_pal_enabled()`
- Produces: `sync_ballpark_pal_slate(slate_date: date, *, client=None, session=None) -> dict` with `status` (`ok`|`skipped`|`error`), counts, optional `reason`/`error`

**Sync algorithm:**

1. If not `ballpark_pal_enabled()` → `{"status": "skipped", "reason": "disabled"}`
2. Open DB session if needed
3. `games = client.games(iso_date)` — if None → `{"status": "error", "error": "games_fetch_failed"}` (soft; no raise)
4. Normalize `items` whether `data` is list or `{items: [...]}`
5. For each game: averages + probabilities; upsert game row; upsert batter/pitcher/team player rows from averages
6. `parkfactors(date)` + `parkfactors_hitters(date)` → upsert
7. `matchups(date, starters=True)` → upsert
8. Catch all exceptions → log → `status=error`

**Pipeline hook** at start of `run_projections_phase`:

```python
results["ballpark_pal"] = _run_ballpark_pal_sync(today)


def _run_ballpark_pal_sync(today: date) -> dict:
    try:
        from app.services.ballpark_pal.sync import sync_ballpark_pal_slate

        return sync_ballpark_pal_slate(today)
    except Exception as exc:
        logger.warning("Ballpark Pal sync failed: %s", exc)
        return {"status": "error", "error": str(exc)}
```

- [ ] **Step 1: Failing test — mocked client; assert upserts called / status ok**

- [ ] **Step 2: Implement `sync.py` + pipeline helper**

- [ ] **Step 3: Test disabled short-circuit**

```python
def test_sync_skipped_when_disabled(monkeypatch):
    monkeypatch.setenv("BALLPARK_PAL_ENABLED", "0")
    monkeypatch.delenv("BALLPARK_PAL_API_KEY", raising=False)
    from datetime import date
    from app.services.ballpark_pal.sync import sync_ballpark_pal_slate

    out = sync_ballpark_pal_slate(date(2026, 8, 5))
    assert out["status"] == "skipped"
```

- [ ] **Step 4: Black + commit**

```bash
git commit -m "$(cat <<'EOF'
feat(mlb): sync Ballpark Pal slate at start of projections

Fetch and snapshot BPP data before strikeouts/hits/game so priors can read today's rows.
EOF
)"
```

---

### Task 4: Pure prior math

**Files:**
- Create: `backend/app/services/ballpark_pal/priors.py`
- Create: `backend/tests/test_mlb_ballpark_pal_priors.py`

**Interfaces:**

```python
def blend(value: float, prior: float, weight: float) -> float:
    """result = (1 - w) * value + w * prior; w clamped to [0, 1]."""


def blend_team_run_rates(
    home_mu: float,
    away_mu: float,
    bpp_home_runs: float | None,
    bpp_away_runs: float | None,
    weight: float,
) -> tuple[float, float, bool]:
    """No-op if weight <= 0 or either prior missing."""


def apply_park_factor_to_runs(
    home_mu: float, away_mu: float, runs_percent: int | None
) -> tuple[float, float]:
    """BPP runsPercent is int vs average (18 => +18%). Scale both by (1 + pct/100)."""


def blend_prop_mean(
    our_mean: float, bpp_mean: float | None, weight: float
) -> tuple[float, bool]:
    ...


def shrink_with_matchup_rate(
    mean: float,
    matchup_prob_pct: float | None,
    *,
    weight: float,
    typical_pa: float = 4.0,
) -> tuple[float, bool]:
    """matchup_prob_pct like 4.2 (% per PA); expected ~= pct/100 * typical_pa."""
```

- [ ] **Step 1: Write tests** — weight 0, weight 1, missing prior, park +18%

- [ ] **Step 2: Implement `priors.py`**

- [ ] **Step 3: pytest PASS + commit**

```bash
git commit -m "$(cat <<'EOF'
feat(mlb): add Ballpark Pal prior blend helpers

Pure functions for run, prop, and matchup shrink math used by game and board injectors.
EOF
)"
```

---

### Task 5: Game / Monte Carlo injection

**Files:**
- Create: `backend/app/services/ballpark_pal/inject_game.py`
- Modify: `backend/app/services/etl/mlb/monte_carlo.py`
- Modify: `backend/app/services/etl/mlb/game_projection_pipeline.py`
- Create: `backend/tests/test_mlb_ballpark_pal_mc.py`

**Interfaces:**

```python
# inject_game.py
def maybe_apply_bpp_run_priors(
    features: dict,
    rates: TeamRunRates,
    as_of,
    *,
    game_id: int | None,
    session=None,
) -> tuple[TeamRunRates, dict | None]:
    ...
```

Hook in `apply_monte_carlo_to_prediction` **after** `maybe_adjust_rates_from_lineups`:

```python
from app.services.ballpark_pal.inject_game import maybe_apply_bpp_run_priors

rates, bpp_meta = maybe_apply_bpp_run_priors(
    features, rates, as_of, game_id=pred.get("game_id")
)
if bpp_meta:
    matchup_meta = {**(matchup_meta or {}), "bpp": bpp_meta}
```

Logic:
1. If not `ballpark_pal_enabled()` → unchanged
2. Load game snapshot + team `runs` averages for home/away
3. `blend_team_run_rates` with `bpp_game_prior_weight()`
4. Apply game-level `runsPercent` via `apply_park_factor_to_runs` when present
5. Do **not** use F5
6. Meta: `{"applied": True, "weight": ..., "home_runs_prior": ..., "away_runs_prior": ...}`

**model_version:** In `store_game_projections`, if any stored `sim_distribution` has `matchup_meta.bpp`, append `+bpp` after existing `+mc` suffix.

- [ ] **Step 1: Unit test** — mocked loader; lambdas move toward prior at weight 1.0

- [ ] **Step 2: Implement injection + version suffix**

- [ ] **Step 3: Run `tests/test_mlb_monte_carlo.py` + new test — PASS**

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(mlb): blend Ballpark Pal team runs into Monte Carlo lambdas

Apply configurable BPP run priors and park-factor scale after lineup adjustments.
EOF
)"
```

---

### Task 6: Strikeouts injection

**Files:**
- Modify: `backend/app/services/etl/mlb/profiles/matchup_k.py`
- Modify: `backend/app/services/etl/mlb/strikeouts.py` (primary blend site after projected K computed)
- Create: `backend/tests/test_mlb_ballpark_pal_strikeouts.py`

**Interfaces:**
- Extend `MatchupSource = Literal[..., "ballpark_pal"]`
- After base projected K + matchup factor in `strikeouts.py`:
  1. Load BPP pitcher `strikeouts` average for pitcher/game/date
  2. `new_k, applied = blend_prop_mean(projected_k, bpp_k, bpp_k_prior_weight())`
  3. If `applied`: set `matchup_source = "ballpark_pal"` (v1 evidence; overrides profile source for that row — document in ops doc)

Optional v1 stretch (only if cheap): average lineup `strikeoutProbability` from matchup snapshots as secondary shrink — skip if it complicates the first PR.

`matchup_source` column is `String(16)`; `"ballpark_pal"` length 12 fits.

- [ ] **Step 1: Failing test for blend + source tag**

- [ ] **Step 2: Implement**

- [ ] **Step 3: Run `tests/test_mlb_matchup_k.py` + new tests + `tests/test_mlb_matchup_source_persist.py` if present**

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(mlb): apply Ballpark Pal strikeout priors on pitcher boards

Blend BPP projected K into daily strikeout projections and tag matchup_source.
EOF
)"
```

---

### Task 7: Hits / HR injection

**Files:**
- Modify: `backend/app/services/etl/mlb/hits.py`
- Create: `backend/tests/test_mlb_ballpark_pal_hits.py`

**Inject:**
1. Hitter hits-like score / projection → `blend_prop_mean(..., bpp hits, bpp_hits_prior_weight())`
2. Homer score → blend toward BPP `homeRuns`, then multiply by hitter PF combined `homeRuns` (default 1.0)
3. Optional: `shrink_with_matchup_rate` using matchup `homeRunProbability`

Skip changing `dingerParlay` sklearn path in v1; pipeline always runs `hits.run` boards.

- [ ] **Step 1: Tests with monkeypatched snapshot loaders**

- [ ] **Step 2: Implement behind `ballpark_pal_enabled()`**

- [ ] **Step 3: pytest PASS + commit**

```bash
git commit -m "$(cat <<'EOF'
feat(mlb): apply Ballpark Pal priors to hits and HR boards

Blend BPP batter averages and park/matchup signals into daily hitter boards.
EOF
)"
```

---

### Task 8: Ops docs + smoke script

**Files:**
- Create: `backend/docs/MLB_BALLPARK_PAL.md`
- Create: `backend/scripts/smoke_mlb_ballpark_pal.py`
- Modify: `AGENTS.md` (YetAI root) — smoke one-liner
- Modify: `backend/docs/MLB_ML_OPS.md` — link to BPP doc

**Smoke:**
- Default offline: load fixtures + assert prior math + client parse
- `--live`: health + today's games count only if key set; never print key

**Docs:** env table, ~35 req/day budget, rollout/rollback, graded success via existing accuracy services, note that `matchups/predict` is not batched.

- [ ] **Step 1: Write docs + smoke**

- [ ] **Step 2: Run offline smoke**

```bash
cd backend && PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_ballpark_pal.py
```

Expected: exit 0.

- [ ] **Step 3: Targeted gates + commit**

```bash
cd backend && python3 -m black . && python3 -m black --check .
PYTHONPATH=. .venv/bin/python -m pytest tests/test_mlb_ballpark_pal_*.py tests/test_mlb_monte_carlo.py tests/test_mlb_matchup_k.py -q
```

```bash
git commit -m "$(cat <<'EOF'
docs(mlb): add Ballpark Pal ops guide and smoke script

Document enablement, quotas, rollback, and graded-board success checks for BPP priors.
EOF
)"
```

---

### Task 9: Migration verify + EV untouched check

**Files:** none required (checklist)

- [ ] **Step 1: `cd backend && .venv/bin/alembic heads` and upgrade on a safe DB**

- [ ] **Step 2: Confirm EV untouched**

```bash
rg -n "ballpark_pal|BPP_|bpp_" backend/app/services/etl/mlb/mlb_ev.py
```

Expected: no matches.

- [ ] **Step 3: Document Railway vars in `MLB_BALLPARK_PAL.md` (do not enable prod in this task unless user asks):**
  - `BALLPARK_PAL_API_KEY` on YetAI + celery-worker
  - `BALLPARK_PAL_ENABLED=1` after first successful sync logs
  - default weights

- [ ] **Step 4: No commit unless docs tweak needed**

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| Client + soft-fail | 1 |
| Snapshots + upsert | 2 |
| Daily fetch incl. matchups starters | 3 |
| No matchups/predict batch | 3 (omitted by design) |
| Prior math | 4 |
| Game/MC + no F5 | 5 |
| Strikeouts + source tag | 6 |
| Hits/HR + PF + matchup | 7 |
| Ops / smoke / success bar | 8 |
| Odds/EV unchanged | 9 |

## Consistency notes

- Weight helpers and blend APIs share names across Tasks 4–7.
- `MatchupSource` gains `ballpark_pal` in Task 6.
- Re-check Alembic `down_revision` at implement time (`alembic heads`).
