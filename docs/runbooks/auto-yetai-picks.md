# Auto YetAI Picks — Rollout Runbook

Automated daily YetAI bet selection across all leagues and markets, gated by admin approval.

## Architecture (one-line)

Celery beat fires `auto_pick.yetai_bets` at 9:00 AM ET → orchestrator pulls candidates from ML / spread / totals / player-prop sources → `ConfidenceScorer` ranks → `BetSelector` picks top 1–4 → `YetAIBet` rows persist as `status="pending_approval"` → admin approves/rejects in the portal at `/admin/yetai-picks`.

## Feature flags

| Flag | Default | Effect |
|---|---|---|
| `AUTO_YETAI_PICKS_ENABLED` (backend env) | `false` | When `true`, the daily auto-pick job and the every-5-min expiry job are added to the Celery beat schedule. |
| `NEXT_PUBLIC_AUTO_YETAI_PICKS_ENABLED` (frontend env) | `false` | When `true`, the `/admin/yetai-picks` route renders. Otherwise it redirects to `/dashboard`. |

Set in production via the existing env management (Railway / Vercel / wherever).

## Rollout phases

### Phase 1 — Foundation (already complete on branch `feat/auto-yetai-picks`)

- Migration `186bd4461744` adds `auto_pick_runs`, `scoring_config`, new `bet_status` enum values, and new `yetai_bets` columns.
- Service modules under `backend/app/services/auto_pick/`.
- Celery tasks under `backend/app/tasks/`.
- Admin API at `/api/admin/yetai-picks/*`.
- Admin frontend at `/admin/yetai-picks`.
- Backtest CLI: `python -m app.services.auto_pick backtest --start <date> --end <date>`.

### Phase 2 — Shadow mode (recommended next step)

Goal: Let the orchestrator run daily, write to the DB, but keep subscribers unaware.

1. Apply the migration in staging/prod:
   ```bash
   cd backend && alembic upgrade head
   ```
2. Confirm `scoring_config` has the seed row:
   ```bash
   psql $DATABASE_URL -c "SELECT * FROM scoring_config;"
   ```
3. Set `AUTO_YETAI_PICKS_ENABLED=true` in backend env, restart Celery beat + worker.
4. Leave `NEXT_PUBLIC_AUTO_YETAI_PICKS_ENABLED=false` (or unset) — admin route stays redirected; subscribers see nothing new.
5. Inspect `auto_pick_runs` and `yetai_bets WHERE source='auto'` daily for ~1 week.
6. Verify picks land with `status="pending_approval"` and have a `confidence_score`, `score_breakdown`, and `reasoning`.

### Phase 3 — Live approval flow

1. Set `NEXT_PUBLIC_AUTO_YETAI_PICKS_ENABLED=true` in frontend env, redeploy.
2. Admin visits `/admin/yetai-picks` to review the queue and approve / reject.
3. Approved picks become visible to subscribers via the existing `/api/yetai-bets` endpoint, tier-gated (FREE rank 1, PRO ranks 2–3, ELITE rank 4).

### Phase 4 — Tuning

After 2–3 weeks of live data:

1. Review hit rate per tier and per market.
2. Tune `scoring_config` weights/threshold:
   ```sql
   UPDATE scoring_config SET weight_edge = 0.45, score_threshold = 70 WHERE id = 1;
   ```
3. Re-run the backtest CLI against recent history to validate before rolling.

## Things to watch

- **Source coverage** — per Task 14, only NBA spreads/totals + NBA points/steals player props have full data. Other markets/leagues return empty candidate lists. Add new sources by creating a shim in `backend/app/services/auto_pick/sources/` and wiring it in `_build_providers` in `backend/app/tasks/auto_pick.py`.
- **Historical hit rates** — `context_builder._load_historical_hit_rates` uses `(bet_type, sport)` as the key. The scorer's lookup uses `(market_type.value, candidate.league)`. These must align by string. Mismatches degrade gracefully (sub-score returns neutral 50).
- **Line movement** — currently returns `{}` because no compatible snapshot table exists. `line_movement_sub_score` returns neutral 50 for missing events.
- **Backtest** — `_load_historical_candidates_for` and `_did_win` are stubbed pending persistence of historical projection snapshots. Backtest currently produces zero picks per day; wire up when needed for weight tuning.

## Rollback

If something goes wrong:

1. Set `AUTO_YETAI_PICKS_ENABLED=false` and restart Celery — stops new auto-picks.
2. Optionally mark in-flight pending picks as rejected via the admin API or SQL.
3. Worst case, roll the migration down: `alembic downgrade -1` (drops `auto_pick_runs`, `scoring_config`, and the new columns on `yetai_bets`; the new enum values stay because Postgres doesn't support `DROP VALUE`).
