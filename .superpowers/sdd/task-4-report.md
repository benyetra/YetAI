# Task 4 Report: Anytime TD projector + Odds attach

**Status:** Complete  
**Commit:** `feat(nfl): anytime TD projector and Odds attach`

## Delivered

| File | Role |
|------|------|
| `anytime_td_projector.py` | λ → P(TD), upsert via `upsert_many`; `run(feature_rows=...)` for tests |
| `anytime_td_betting.py` | Odds `player_anytime_td` fetch/parse, implied/edge, `OVER`/`NO_PLAY` |
| `test_nfl_anytime_td_projector.py` | Pure projection + mocked upsert run |
| `test_nfl_anytime_td_betting.py` | American implied, parse, match, mocked attach run |

## Key constants

- `ANYTIME_TD_EDGE_THRESHOLD = 0.05` — recommend `OVER` when `td_probability - implied ≥ 0.05`, else `NO_PLAY`
- `MODEL_VERSION = "hierarchical_v1"`

## Behavior notes

- **Projector:** `feature_rows=None` calls `_try_build_feature_rows` (nflverse hooks raise `NotImplementedError` → 0 rows, status ok).
- **Betting:** Uses `sync_odds_get` + `sport_in_season`; pure helpers `american_to_implied_prob`, `parse_player_anytime_td_outcomes`, `match_player_odds` are unit-tested without API.

## Tests

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nfl_anytime_td_projector.py tests/test_nfl_anytime_td_betting.py -q
# 11 passed
```
