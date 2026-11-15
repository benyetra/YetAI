# Bets worker: a dedicated Celery worker for YetAI Bets (YetAI-kij)

## What and why

Time-critical YetAI Bets tasks run on their own queue, `yetai_bets`, so they are never
stuck behind an hour-long ETL task on the concurrency-1 `celery-worker`:

| Task | Schedule (ET) | Queue |
|------|---------------|-------|
| `yetai_bets.settle` | every 15 min, expires 600 s | `yetai_bets` |
| `auto_pick.yetai_bets` | 11:00 and 17:30, expires 3 h | `yetai_bets` |
| `auto_pick.expire_pending` | every 5 min, expires 240 s | `yetai_bets` |
| `yetai_bets.settlement_alert` | hourly at :15, expires 1800 s | `yetai_bets` |
| `app.tasks.etl_pipeline.nba.close_capture` | every 10 min 11:00-23:50, expires 540 s | `yetai_bets` |
| `app.tasks.health.bets_queue_watch` | every 10 min | `celery` (watches `yetai_bets`) |
| everything else (ETL, games sync, model review, league vault) | | `celery` (default) |

Routing is by task name in one place: `BETS_QUEUE_TASKS` in `backend/app/celery_app.py`.
`backend/tests/test_celery_queues.py` fails if a `yetai_bets.*` / `auto_pick.*` task, or a
beat entry that expires within 15 minutes, is not routed to `yetai_bets`.

The worker command comes from `CELERY_ROLE` (`backend/app/worker_role.py`), run by
`bash /app/scripts/railway-celery.sh`:

| `CELERY_ROLE` | Command | Use |
|---------------|---------|-----|
| unset / `all` | `celery -A app.celery_app worker --beat --loglevel=info --concurrency=1 --max-memory-per-child=800000 --max-tasks-per-child=8` | the production start command exactly (the old repo scripts said `--concurrency=2`; production never used them): beat + both queues |
| `etl` | the same + `-Q celery -n etl@%h` | `celery-worker` after the rollout |
| `bets` | `celery -A app.celery_app worker --loglevel=info -Q yetai_bets --concurrency=1 --max-memory-per-child=400000 --max-tasks-per-child=50 -n bets@%h` | the new `bets-worker`; refuses `--beat` |

A worker started without `-Q` consumes every queue in `task_queues`, so the current start
command keeps settling bets as soon as this code deploys.

Only one beat ever sends. `DatabaseScheduler` holds the Redis key `yetai:beat:leader`
(TTL 90 s, refreshed every <=30 s); any other beat logs `is standby` and sends nothing,
and takes over within 90 s if the sender dies (at once if it stops cleanly). The bets
role never starts beat.

## Rollout (each step is safe alone and reversible by a setting)

Before you start: the PR is merged and the GitHub "Railway Production Deploy" run is green.

### Step 1: merge (no Railway change)

`celery-worker` keeps its start command; it now consumes both queues.

Check:
```bash
railway logs -s celery-worker | grep -A3 '\[queues\]'      # .> celery  and  .> yetai_bets
railway logs -s celery-worker | grep "yetai_bets.settle.*succeeded.*'success': True" | tail -3   # every 15 min
railway logs -s celery-worker | grep 'is the sender\|is standby'               # "is the sender" once per start
```
Rollback: revert the PR. The old code consumes only `celery`, so anything still on
`yetai_bets` stays in Redis unread (stale; beat sends fresh copies to `celery`). Clear it
with `redis-cli -u "$REDIS_URL" del yetai_bets` if you like.

### Step 2: put `celery-worker` on the role script (same command)

Railway > `celery-worker` > Settings > Deploy > Custom Start Command:
```text
bash /app/scripts/railway-celery.sh
```
Leave `CELERY_ROLE` unset. Railway redeploys.

Check: the log shows
`worker_role: celery -A app.celery_app worker --beat --loglevel=info --concurrency=1 --max-memory-per-child=800000 --max-tasks-per-child=8`
and `[queues]` still lists `celery` and `yetai_bets`.

Rollback: set the start command back to
`bash -c 'cd /app/backend && PYTHONPATH=/app/backend exec celery -A app.celery_app worker --beat --loglevel=info --concurrency=1 --max-memory-per-child=800000 --max-tasks-per-child=8'`.

### Step 3: create `bets-worker`

1. Railway > project `yetai-backend` > `celery-worker` > ... > Duplicate. Name it `bets-worker`.
   Duplicating copies the source (this repo, `backend/Dockerfile`, root `railway.json`) and
   all variables. If you create it from scratch instead (New > GitHub repo, same repo, same
   Dockerfile path), add these variables as references to `celery-worker`, e.g.
   `DATABASE_URL=${{celery-worker.DATABASE_URL}}`:
   `DATABASE_URL REDIS_URL ODDS_API_KEY ODDS_API_DAILY_BUDGET NBA_API_KEY AUTO_YETAI_PICKS_ENABLED ENVIRONMENT AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_REGION AWS_S3_BUCKET_NAME SECRET_KEY BREVO_API_KEY FROM_EMAIL SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD`
   (`REDIS_URL` and `DATABASE_URL` are required. The rest is the worker's environment
   minus API-only keys; simplest and safest is to reference every variable `celery-worker` has.)
2. Add variable `CELERY_ROLE=bets`.
3. Start command: `bash /app/scripts/railway-celery.sh`. No healthcheck, no public domain.
4. Copy the new service id (Cmd+K > copy service ID) into the GitHub repository variable
   `RAILWAY_BETS_WORKER_SERVICE_ID` (Settings > Secrets and variables > Actions > Variables)
   so every deploy also ships it. Until then the deploy step is skipped.

Check:
```bash
railway logs -s bets-worker | grep 'worker_role:'          # ... -Q yetai_bets ... -n bets@%h, no --beat
railway logs -s bets-worker | grep -A3 '\[queues\]'        # only .> yetai_bets
railway logs -s bets-worker | grep -c 'beat:'              # 0: no beat in this service
railway logs -s bets-worker | grep "yetai_bets.settle.*succeeded.*'success': True" | tail -3
```
(The settle task catches its own errors, so Celery logs `succeeded` even when it fails;
that is why the checks look for `'success': True`.)

Both workers now consume `yetai_bets`; either may run a given settle. That is fine:
settlement row-locks each bet, auto-pick takes a Postgres advisory lock and counts the
day's published picks.

Rollback: delete (or stop) `bets-worker`; `celery-worker` still consumes both queues.

### Step 4: `celery-worker` to the default queue only

Railway > `celery-worker` > Variables: add `CELERY_ROLE=etl`. Railway redeploys.

Check:
```bash
railway logs -s celery-worker | grep 'worker_role:'        # ... -Q celery -n etl@%h, with --beat
railway logs -s celery-worker | grep -A3 '\[queues\]'      # only .> celery
railway logs -s celery-worker | grep -c 'yetai_bets.settle.*received'   # 0 from now on
railway logs -s bets-worker   | grep "yetai_bets.settle.*succeeded.*'success': True" | tail -3
```
and the next day: `auto_pick_runs.run_at` within a minute of 11:00 / 17:30 ET.

Rollback: delete `CELERY_ROLE` on `celery-worker` (back to both queues). Do this before
removing `bets-worker`, never after: in between, nothing would consume `yetai_bets`.

## Watching it

`app.tasks.health.bets_queue_watch` runs every 10 minutes on the default queue and raises an
admin notification (bell, and SMS to opted-in admins if Twilio is configured) when 12 or
more messages wait on `yetai_bets` (`YETAI_BETS_QUEUE_ALERT_DEPTH`), at most once per 6 h.
Healthy depth is 0-2; nothing consuming the queue adds about 22 messages an hour.
Until `bets-worker` exists (steps 1-2) the watch can fire after a long ETL run (the
03:30 NBA pipeline takes 54-104 min): that is the delay this change removes. Manual check:
`redis-cli -u "$REDIS_URL" llen yetai_bets`.

## Delivery guarantees

`task_acks_late` is on and Redis `visibility_timeout` is 24 h. A task killed mid-run (a
deploy that outlasts the stop grace period, OOM) stays unacknowledged and is redelivered
about 24 h later. A clean stop (SIGTERM) finishes the running task and returns prefetched
ones to the queue at once.

The 24 h delay is not shortened for the bets queue on purpose: kombu restores unacked
messages for all queues from one global index, so a bets worker with a short timeout would
re-queue a still-running hour-long ETL task and run it twice. Instead every bets beat entry
has an `expires` well under 24 h, so a late redelivered copy is discarded, and beat itself
covers the gap: settle, expire-pending, close capture and the alert re-run within 5-60
minutes; a killed 11:00 auto-pick is covered by the 17:30 run, which fills the day to the cap.
Bets tasks take seconds, so a kill mid-run needs a deploy in that window.

## Cost

One more always-on container. Locally the bets worker uses about 0.3 GB (main process) +
0.1 GB (one child) resident and almost no CPU between runs. On Railway's usage pricing
that is roughly $4-6 a month (estimate; check the service's Metrics tab after a day).
