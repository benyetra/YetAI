# NBA ETL parity vs YetiBets (read-only reference)

Source checklist: `YetiBets/scripts/nba/daily_pipeline.py` (28 steps).  
Orchestrator: `app.tasks.etl_pipeline.NBA_PHASES` + Celery Beat `nba-update-pipeline-daily` (03:30 ET).

## Ported (YetAI `app/services/etl/nba/`)

| YetiBets script | YetAI module | Celery task |
|-----------------|--------------|-------------|
| `update_team_roster_api_sports.py` | `update_team_roster.py` | `nba.update_team_roster` |
| `yesterdays_players_espn.py` | `yesterdays_players.py` | `nba.yesterdays_players` |
| `today_active_players_espn.py` | `today_active_players.py` | `nba.today_active_players` |
| `update_recent_games_api_sports_simple.py` | `update_recent_games.py` | `nba.update_recent_games` |
| `*_predictions_v2.py --store-actuals` (multi) | `store_actuals.py` | `nba.store_actuals` |
| `update_team_offense/defense *_api_sports` | `update_team_offense_stats.py` + `update_team_defense_stats.py` | `nba.update_team_stats` |
| `update_player_career_data_api_sports.py` | `update_player_career_data.py` | `nba.update_player_data` |
| `update_injury_status.py` | `update_injury_status.py` (CBS only) | `nba.update_injury_status` |
| `update_expected_minutes.py` | `update_expected_minutes.py` | `nba.update_expected_minutes` |
| `update_game_lines.py` | `update_game_lines.py` | `nba.update_game_lines` |
| `no_steals.py` | `generate_no_steals.py` | `nba.generate_no_steals` |
| `points_predictions_v2.py` | `generate_points_predictions.py` | `nba.generate_predictions` |
| `rebounds/assists/steals/blocks/freethrows *_v2` | `generate_*_predictions.py` | matching tasks |
| `three_point_predictions_v2.py` | `generate_three_pt_made_predictions.py` | `nba.generate_three_pt_made_predictions` |
| `pra_predictions.py` | `generate_pra_predictions.py` | `nba.generate_pra_predictions` |
| `totals_projector.py` | `totals_projector.py` | `nba.totals_projector` |
| *(WNBA backport)* | `spread_projector.py` | `nba.spread_projector` |
| *(WNBA backport)* | `store_spread_actuals.py` | `nba.store_spread_actuals` |
| *(WNBA backport)* | `spreads_accuracy_tracker.py` | `nba.spreads_accuracy` |
| `totals_accuracy_tracker.py` | `totals_accuracy_tracker.py` | `nba.totals_accuracy_tracker` |
| `calculate_prediction_accuracy.py` | `calculate_prediction_accuracy.py` | `nba.calculate_prediction_accuracy` |
| `find_top_performers.py` | `find_top_performers.py` | `nba.find_top_performers` |

## Not yet ported

| YetiBets script | Notes |
|-----------------|--------|
| `store_free_throw_actuals.py` | Partially covered by `store_actuals` free_throw stat |

Track new ports as Celery sub-tasks under `NBA_PHASES`; do not re-add logic to YetiBets.

## Prop calibration (BKB-2.6)

Holdout residual buckets → `P(over line)`; optional at inference via
`NBA_PROP_CALIBRATION_ENABLED=1`. Details: `docs/NBA_ML_OPS.md`.

## Validation

```bash
cd backend && PYTHONPATH=. python -m pytest tests/test_nba_totals_projector.py -v
cd backend && PYTHONPATH=. python -m pytest tests/test_nba_prop_calibration.py -v
cd backend && PYTHONPATH=. python scripts/validate_nba_pipeline.py
```

Game O/U accuracy uses `pred_nba_totals_projections`, `pred_nba_totals_actuals`, and `pred_nba_totals_accuracy` — not `pred_prediction_accuracy` player stat types.
