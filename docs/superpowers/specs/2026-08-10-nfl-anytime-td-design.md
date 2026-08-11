# NFL Anytime Touchdown Prop — Design Spec

**Date:** 2026-08-10  
**Status:** Approved for implementation planning  
**Decisions:** Full anytime market (QB/RB/WR/TE); full feature set before UI go-live; hierarchical λ → P(≥1 TD); curated defensive scheme tags + nflverse aggregates.

## Problem

YetAI’s NFL predictions page covers QB pass yards, kickers, and (as of readiness work) game spreads/totals. Bettors and users also want a **ranked Anytime Touchdown board** — who is most likely to score a TD this week — driven by a real model (usage, red zone, opponent defense/scheme, weather, offense tendencies), not just Odds scraping.

Odds API already exposes `player_anytime_td`; no skill-player TD probability ETL exists.

## Goals

1. Model **P(player scores ≥1 TD)** for active QB/RB/WR/TE each REG week.
2. Rank and display highest-probability plays with market odds/edge when lines exist.
3. Ship UI only after feature ETL is complete and a **backtest gate** passes.
4. Maintain curated opponent **defensive scheme tags** (Cover / man-zone / pressure lean) alongside nflverse defense aggregates.

## Non-goals (v1)

- First TD / last TD markets
- Monte Carlo game simulation as the TD engine
- Paid third-party scheme feeds
- Auto-pick source (follow-up after grading exists)
- Preseason product surface

## Approach

**Hierarchical expected TDs → anytime probability**, with optional light residual calibration later:

```text
team scoring env (implied total, pace, weather)
  × RZ / goal-line opportunity rate
  × player role (RZ share, GL carries, targets, snaps)
  × conversion rates (by position / recent form)
  × opponent defense (TDs allowed by pos + curated scheme tags)
  → expected TDs λ
  → P(anytime) = 1 − exp(−λ)   # NegBin if overdispersion warrants
  → Odds player_anytime_td → implied, edge, recommendation
```

---

## Features

| Group | Sources | Examples |
|-------|---------|----------|
| Usage / prior weeks | nflverse weekly + PBP + `pbp_participation` (routes); fantasy `player_analytics` | snaps, targets, carries, routes, TD history L3/L5/season |
| Red zone / goal line | nflverse PBP (≤20, ≤5) | RZ share, GL carries, RZ targets, team RZ pass rate |
| Offense tendencies | nflverse PBP + team weekly | early-down pass%, script from implied margin |
| Opponent defense | nflverse aggregates | TDs allowed to QB/RB/WR/TE, RZ TD rate allowed, EPA |
| Scheme tags (curated) | versioned YAML/CSV in repo | cover_base (1/2/3/4/6), man_zone_lean, pressure_lean |
| Weather | `pred_nfl_weather` / venue | outdoor, wind, precip — rush GL / short-yardage nudge |
| Game env | `pred_nfl_game_lines` + totals projector | market/model total & spread → scoring opportunities |

### Scheme tag contract

- Primary: `backend/data/nfl/defensive_schemes.yaml` (per team, season/`as_of`)
- Optional weekly overrides: `backend/data/nfl/defensive_schemes_weekly.yaml`
- Loaded into `pred_nfl_defense_scheme` (team, season, week nullable, cover_base, man_zone_lean, pressure_lean, source, updated_at)
- Encoded as model factors (not free text)

### Player universe

QB/RB/WR/TE **starters only** (`depth_team=1`, excluding KR/PR/return slots).
When depth charts are unavailable, fall back to top prior-usage players per team
(QB1 / RB1 / WR1–3 / TE1).

---

## Data model

| Table | Role |
|-------|------|
| `pred_nfl_anytime_td_predictions` | Weekly predictions: `expected_tds`, `td_probability`, market odds/implied, edge, recommendation, confidence, feature JSON, `model_version` |
| `pred_nfl_anytime_td_actuals` | Binary anytime + TD count for grading |
| `pred_nfl_defense_scheme` | Curated scheme snapshot |
| `pred_nfl_td_feature_weekly` (optional) | Materialized weekly features for train/infer |

Unique key: `(season, week, player_id)` (and/or `game_date` + player).

---

## Pipeline

Extend `run_nfl_update_pipeline` / `NFL_PHASES` (after game projections, coordinated with existing props):

1. **Feature build** — weekly player + team + opponent + scheme + weather
2. **`nfl.anytime_td_projector`** — λ → P(anytime), upsert predictions
3. **`nfl.anytime_td_betting`** — Odds API `player_anytime_td` attach
4. **Actuals** — post-week binary anytime + TD count → accuracy buckets

UI remains off until gate passes: env `NFL_ANYTIME_TD_UI=0` by default.

---

## API & frontend

**API:** `GET /api/v1/predictions/nfl` adds:

```json
"anytime_td_predictions": [ /* sorted by td_probability descending */ ]
```

Core fields: player, position, team, opponent, `td_probability`, `expected_tds`, market odds/implied, edge, recommendation, confidence, game_date/week.

**Accuracy:** Brier / log-loss, top-N hit rate, +EV subset when market present.

**Frontend:** `/predictions/nfl` group **Anytime Touchdowns** — ranked table (P(TD), Odds, Edge, Pick, Conf); optional position filter. Gated by `NFL_ANYTIME_TD_UI`. Copy: model anytime TD (not first/last).

---

## Backtest gate (required before UI on)

Walk-forward 2023–2025 REG (train ≤ Y−1, test Y):

| Check | Initial target |
|-------|----------------|
| Calibration | Brier ≤ baseline (market-implied when available; else position prior) |
| Ranking | Top-20 weekly quality better than market or usage-only baseline |
| Stability | No position with pathological calibration |

Artifacts: `backend/models/nfl/anytime_td_metrics.json` + offline/quick backtest smoke. Enable UI only when metrics + `NFL_ANYTIME_TD_UI=1`.

---

## Success criteria

1. Feature ETL produces complete weekly rows for scheme, RZ, usage, defense, weather, game env.
2. Predictions exist for the active REG week’s QB/RB/WR/TE universe with calibrated `td_probability`.
3. Odds anytime-TD lines attach when available; edge/recommendation populated.
4. Backtest metrics meet gate; UI flag can be turned on safely.
5. `/predictions/nfl` shows a descending-probability Anytime TD table when the flag is on.

## Follow-ups

- Auto-pick source for +EV anytime TD
- First/last TD markets
- Midweek line refresh alignment with game-board Beat tune
