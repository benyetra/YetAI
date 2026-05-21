# WNBA Support — Design Spec

**Date:** 2026-05-21
**Author:** brainstorming session (byetra@gmail.com + Claude)
**Status:** Approved, awaiting implementation plan

## Goal

Add WNBA support to YetAI's predictions pipeline, matching the player-prop and game-line coverage we have for NBA. Target: incredibly accurate predictions, on par with or better than the existing NBA models.

Scope per league surface:
- **Game lines:** market spreads, totals, moneylines + our own totals projection + our own spread/win-probability projection
- **Player props:** points, assists, rebounds (subset of NBA's 8-prop suite)

## Phased Rollout

The WNBA 2026 regular season is starting now (today is 2026-05-21). Player-prop models require historical training data and accuracy validation that cannot be rushed without sacrificing the "incredibly accurate" bar. We split the work:

### Phase 1 — Game lines (target: 2-3 weeks)
- Market line ingestion via the-odds-api (already wired at the sport-key layer)
- Own totals projection model (port + retune of NBA `totals_projector.py`)
- Own spread / win-probability model (NEW — beyond NBA parity)
- Accuracy tracking active from day 1
- Ship to UI behind a `WNBA` league toggle in existing screens

### Phase 2 — Player props (target: mid-season 2026 launch, or 2027 if quality demands)
- XGBoost models for points, assists, rebounds, trained on 2021-2025 WNBA history
- Validation gate: backtest on 2025 season against pre-set MAE thresholds
- A prop type that fails its threshold does not ship

### Cross-phase decisions
- Parallel `pred_wnba_*` tables (no schema unification with NBA in this project)
- ESPN scoreboard for game discovery; `nba_api` (already installed) with `LeagueID="10"` for stats.wnba.com authoritative stats; ESPN for injuries
- Reuse existing `SportKey.BASKETBALL_WNBA` integration in `odds_api_service.py`
- New per-sport API endpoint `/api/v1/predictions/wnba` (mirrors existing `/nba`, `/nhl`, `/mlb`, `/nfl` per-sport routes). Earlier spec wording about a `league` query param was inconsistent with the actual per-sport pattern in `app/api/v1/predictions.py` and has been corrected.

## Beyond-NBA-Parity Note

This project ships a **spread / win-probability projection model** for WNBA that does not exist for NBA. The NBA pipeline only has a totals projector. The WNBA spread model is logged here as discovered work to backport to NBA in a future project (see Discovered Work).

## Data Sources

| Feed | Module | Purpose |
|---|---|---|
| the-odds-api | existing `app/services/odds_api_service.py` | Market lines (spreads, totals, ML). Already supports `basketball_wnba`. No change. |
| ESPN WNBA scoreboard | new `app/services/etl/wnba/_espn.py` | Game discovery, final scores, team-ID anchor. Endpoint: `site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard`. Mirrors NBA `_espn.py`. |
| stats.wnba.com | new `app/services/etl/wnba/_wnba_stats.py` (wraps `nba_api` with `LeagueID="10"`) | Authoritative box scores, season averages, advanced team stats, player career data, rosters. Stats.nba.com and stats.wnba.com share the same API surface; the WNBA is `LeagueID=10`. Fall back to a direct HTTP call for any specific endpoint that does not pass through cleanly. |
| ESPN WNBA injuries | new helper in `_espn.py` | Injury statuses (stats.wnba.com does not publish injuries). |

All clients get a thin retry wrapper: 3 attempts, exponential backoff, 60s pause on 429 — same pattern as NBA `_api_sports.py`.

## ETL Package Layout

```
app/services/etl/wnba/
  __init__.py
  _espn.py                          # game discovery + injury feed
  _wnba_stats.py                    # stats.wnba.com client (wraps nba_api with LeagueID="10")
  _team_id_map.py                   # ESPN id ↔ wnba_id ↔ odds-api team name
  _feature_engineering.py           # Phase 2 — Points/Assists/Rebounds feature vectors
  _ml_predict.py                    # Phase 2 — XGBoost model loading + inference

  # Phase 1
  update_team_roster.py
  update_recent_games.py
  update_team_offense_stats.py
  update_team_defense_stats.py
  update_injury_status.py
  update_game_lines.py              # market lines → pred_wnba_game_lines
  totals_projector.py               # own totals model
  spread_projector.py               # own spread/win-prob model (NEW vs NBA)
  store_actuals.py
  totals_accuracy_tracker.py
  spreads_accuracy_tracker.py       # NEW

  # Phase 2
  update_expected_minutes.py
  today_active_players.py
  generate_points_predictions.py
  generate_assists_predictions.py
  generate_rebounds_predictions.py
  calculate_prediction_accuracy.py

  # One-shot
  backfill_wnba_history.py          # idempotent backfill for Phase 2 training data
```

## Database Schema

Parallel `pred_wnba_*` tables. **All tables created in one migration up front** so Phase 2 does not require a second schema rev.

### Phase 1 tables
| Table | Mirrors |
|---|---|
| `pred_wnba_team_roster` | `pred_team_roster` |
| `pred_wnba_recent_games` | `pred_recent_games` |
| `pred_wnba_team_offense_stats` | `pred_team_offense_stats` |
| `pred_wnba_team_defense_stats` | `pred_team_defense_stats` |
| `pred_wnba_player_injury_status` | `pred_player_injury_status` |
| `pred_wnba_game_lines` | `pred_nba_game_lines` |
| `pred_wnba_totals_projections` | `pred_nba_totals_projections` |
| `pred_wnba_totals_actuals` | `pred_nba_totals_actuals` |
| `pred_wnba_totals_accuracy` | `pred_nba_totals_accuracy` |
| `pred_wnba_team_pace_efficiency` | `pred_nba_team_pace_efficiency` |
| `pred_wnba_spread_projections` | *(new)* |
| `pred_wnba_spread_actuals` | *(new)* |
| `pred_wnba_spread_accuracy` | *(new)* |

### Phase 2 tables
| Table | Mirrors |
|---|---|
| `pred_wnba_today_active_players` | `pred_today_active_players` |
| `pred_wnba_points_projections` | `pred_points_projections` |
| `pred_wnba_points_actuals` | `pred_points_actuals` |
| `pred_wnba_assists_projections` | `pred_assists_projections` |
| `pred_wnba_assists_actuals` | `pred_assists_actuals` |
| `pred_wnba_rebounds_projections` | `pred_rebounds_projections` |
| `pred_wnba_rebounds_actuals` | `pred_rebounds_actuals` |

SQLAlchemy models added to `app/models/predictions_models.py` under a `# --- WNBA ---` section header.

**Market-line storage decision:** `pred_wnba_game_lines` stores **consensus average across books** (single row per game per market), NOT per-book rows as NBA does. If a future "best line" UI is added, this will need re-visiting (logged in Discovered Work).

**Identity:** WNBA player IDs and team IDs from stats.wnba.com are in their own integer namespace — no collision risk with NBA IDs.

## Phase 1 — Modeling

### Totals projector (rule-based, port of `totals_projector.py`)

WNBA-tuned constants:

| Constant | NBA value | WNBA value |
|---|---|---|
| League avg pace | 99.5 | 80.0 |
| League avg ORtg | 114.0 | 102.0 |
| League avg DRtg | 114.0 | 102.0 |
| League avg total | 225.0 | 164.0 |
| Altitude bonus | Denver +2.5 | none |

- Star-player impact list rebuilt for WNBA (A'ja Wilson, Caitlin Clark, Breanna Stewart, Napheesa Collier, Sabrina Ionescu, Alyssa Thomas, etc.) with values scaled to ~60% of NBA values (lower total baseline → smaller absolute swings)
- B2B / rest adjustment retained and expected to carry more weight than in NBA (more aggressive WNBA travel schedule)
- Initial star list and impact values are estimates and will be re-tuned against early-season actuals via the accuracy tracker

### Spread / win-probability model (Elo + pace overlay)

No ML training for Phase 1. Approach:

1. Elo rating per team, updated game-by-game. Bootstrap from 2022-2025 final scores via `wnba_api` history. Each season seeded as `0.75 * prior_end_rating + 0.25 * league_mean`.
2. Expected margin = `(home_elo - away_elo) / 25 + HCA`. WNBA home-court advantage estimated at **2.5 points** (NBA ~2.8). To be re-verified during implementation against 2022-2024 data.
3. Pace/efficiency overlay shares team-rating inputs with the totals model — totals and spread move consistently.
4. Win probability from margin via a logistic curve fit on historical WNBA data (do NOT borrow NBA's spread→win-prob curve; WNBA has higher per-possession variance which loosens the fit).

**Why no ML for Phase 1 spread:** Elo + pace covers most signal a tree model would extract from team-only features. ML's marginal value is in player-availability features, which Phase 2 will bring. The spread model can then be upgraded to ML using the Phase 2 feature pipeline as input.

### Edge surfacing (totals + spreads)

Each projection row stores: `our_projection`, `market_line_consensus`, `edge`, `confidence`, `recommended_side` (only set when `|edge| > threshold`).

## Phase 2 — Player Props

### Historical training data
- Backfill 2021-2025 regular season + playoffs box scores via `nba_api` (LeagueID=10) into `pred_wnba_recent_games`
- Estimated ~20k player-game training rows per model (~3,500-4,500 per season)
- One-shot idempotent `backfill_wnba_history.py` script, separate from nightly ETL

### Feature engineering
Port `_feature_engineering.py` from NBA. Adapted feature set:
- Recent form windows: last 3 / 5 / 10 games
- Season averages: points/assists/rebounds, minutes, usage rate, TS%
- Opponent defense: opp DRtg, opp position-specific defense (expect noisier signal — smaller roster sample per position)
- Rest days, B2B flag, home/away
- Expected minutes: retuned for WNBA (40-min games vs 48; rotations shorter; stars 32-36 min — higher minutes-share concentration)
- Injury context: teammate injuries → usage redistribution
- Pace-adjusted opponent stats

Dropped from NBA: altitude flag (no WNBA altitude games), specific elite-defender matchup features (data sparser).

### Training & validation
- One XGBoost regressor per prop (points, assists, rebounds). NBA hyperparameter starting point, grid-search retuned on WNBA validation set.
- Train on 2021-2024, validate on 2025.

### Hard ship gates (acceptance thresholds, set before training to prevent goalpost-moving)

| Prop | MAE threshold | Notes |
|---|---|---|
| Points | ≤ 4.5 | NBA baseline ~5.0; WNBA scoring tighter → tighter MAE expected |
| Assists | ≤ 1.5 | |
| Rebounds | ≤ 2.0 | |
| Calibration (all) | residuals approximately zero-mean across projection range | No systematic over/under bias near the line |

A prop type failing its threshold does not ship. It returns to feature work or more training data.

### Inference (nightly)
Mirrors NBA `generate_{prop}_predictions.py`:
1. Query `pred_wnba_today_active_players` for today's games
2. Skip injured (out/IR/doubtful) and players with < 5 games of history
3. Build feature vector → run model → clamp negatives to 0
4. Upsert into `pred_wnba_{prop}_projections`

### Edge surfacing (props)
Same pattern as game lines. The-odds-api supports `player_points`, `player_assists`, `player_rebounds` markets for WNBA — book coverage to confirm on first integration run.

## Scheduling (Celery beat)

All jobs season-gated (default May 1 – October 31, expanded for playoffs). Outside the window: no-op.

| Job | Cadence | Phase |
|---|---|---|
| `update_wnba_team_roster` | Daily 03:00 ET | 1 |
| `update_wnba_team_offense_stats` / `_defense_stats` | Daily 03:30 ET | 1 |
| `update_wnba_injury_status` | Every 2 hours during season | 1 |
| `update_wnba_recent_games` | Daily 03:00 ET | 1 |
| `update_wnba_game_lines` | Every 30 min, game-day gated | 1 |
| `wnba_totals_projector` | Daily 08:00 ET + 1h before each game | 1 |
| `wnba_spread_projector` | Daily 08:00 ET + 1h before each game | 1 |
| `wnba_today_active_players` | Daily 09:00 ET | 2 |
| `generate_wnba_{points,assists,rebounds}_predictions` | Daily 10:00 ET + 1h before each game | 2 |
| `store_wnba_actuals` | Daily 04:00 ET (next morning) | 1+2 |
| `wnba_totals_accuracy_tracker` / `spreads_accuracy_tracker` | Daily 05:00 ET | 1 |
| `calculate_wnba_prediction_accuracy` (props) | Daily 05:00 ET | 2 |

## Accuracy Tracking

Extend existing accuracy dashboard with league filter. Add WNBA-specific metrics:
- Totals: MAE, RMSE, hit-rate vs market (% picks correct when `|edge| > threshold`)
- Spreads: ATS hit-rate, win-prob Brier score, calibration buckets
- Props (Phase 2): per-player MAE, per-prop hit-rate, calibration curve

## API & Frontend

### API
- `GET /odds/...` — already returns WNBA via `SportKey.BASKETBALL_WNBA`. No change.
- `GET /api/v1/predictions/wnba` — new per-sport route. Returns `totals` (Phase 1), `spreads` (Phase 1), and `points`/`assists`/`rebounds` (Phase 2 — empty until Phase 2 ships). Mirrors `/nba`, `/nhl`, `/mlb`, `/nfl` per-sport shape.

### Frontend
- New `/predictions/wnba/page.tsx` mirroring `/predictions/nba/page.tsx`
- Reuse `SportPredictionsPage` + `NbaTotalsProjectionsTable`-style components (rename or generalize as needed for WNBA totals + spreads)
- Phase 2 only: add a "model confidence" badge on prop cards (WNBA models newer/less proven)

## Discovered Work (file as beads issues during implementation)

- **NBA spread projector** — backport the WNBA Elo + pace model to NBA (NBA currently has no own spread/win-prob projector)
- **Per-book market line storage for WNBA** — current design uses consensus avg; if UI grows a "best line" feature, this will need revisit
- **Schema unification across leagues** — current design uses parallel `pred_wnba_*` tables; if maintenance cost grows, consider migrating to a unified schema with a `league` discriminator column

## Out of Scope

- Other player props beyond points/assists/rebounds (blocks, steals, 3PM, FTM, PRA combos)
- WNBA futures (championship, MVP, etc.)
- Per-book line storage for WNBA
- Schema refactor of existing NBA tables
- NBA spread/win-prob model
