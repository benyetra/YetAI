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
| `update_injury_status.py` | `update_injury_status.py` | `nba.update_injury_status` |
| `update_expected_minutes.py` | `update_expected_minutes.py` | `nba.update_expected_minutes` |
| `update_game_lines.py` | `update_game_lines.py` | `nba.update_game_lines` |
| `points_predictions_v2.py` | `generate_points_predictions.py` | `nba.generate_predictions` |
| `rebounds/assists/steals/blocks/freethrows *_v2` | `generate_*_predictions.py` | matching tasks |
| `three_point_predictions_v2.py` | `generate_three_pt_made_predictions.py` | `nba.generate_three_pt_made_predictions` |
| `find_top_performers.py` | `find_top_performers.py` | `nba.find_top_performers` |

## Not yet ported

| YetiBets script | Notes |
|-----------------|--------|
| `no_steals.py` | Qualitative steals picks; separate from numeric steals v2 |
| `pra_predictions.py` | Combo prop after individual stats |
| `totals_projector.py` | Game O/U team totals |
| `totals_accuracy_tracker.py` | Grades totals vs actuals |
| `calculate_prediction_accuracy.py` | Aggregate accuracy metrics |
| `store_free_throw_actuals.py` | Partially covered by `store_actuals` free_throw stat |

Track new ports as Celery sub-tasks under `NBA_PHASES`; do not re-add logic to YetiBets.
