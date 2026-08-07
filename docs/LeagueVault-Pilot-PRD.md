# League Vault Pilot PRD

**Two real league history sites, on real infrastructure, to decide whether this is a business**

| | |
|---|---|
| **Status** | Phase 4 ready — instrumented; ship via checklist in `LeagueVault-Pilot-Log.md` |
| **Author** | Bennett |
| **Date** | 2026-08-06 |
| **Supersedes for now** | `LeagueVault-PRD.md` (commercial — parked) |
| **Scope** | Sleeper `mikes-hard` + ESPN `league-838295` |
| **Target** | Live before Week 1 of the 2026 NFL season |

## Phases

| Phase | Scope | Status |
|-------|--------|--------|
| **P0** | API spike | ✅ |
| **P1** | Schema + ingest | ✅ |
| **P2** | Identity, all-play/luck, records, snapshot | ✅ |
| **P3** | Public API, middleware, pages, OG | ✅ |
| **P4** | Analytics beacons, verify script, observation log | ✅ code — passive watch after ship |

## P4 instrumentation

| Piece | Location |
|--------|----------|
| Page-view beacon | `POST /api/vault/{slug}/events` + `VaultAnalyticsBeacon` |
| Aggregate stats | `GET /api/vault/{slug}/stats?days=14` |
| Events table | `lv_vault_events` |
| Readiness check | `scripts/league_vault/prod_verify_pilot.py` |
| Human log / go-no-go | `docs/LeagueVault-Pilot-Log.md` |

### How to measure without asking

1. Ship links with no “product test” framing.
2. After 7 days: `curl -s https://api.yetai.app/api/vault/mikes-hard/stats \| jq`
3. Compare `total_events`, `unique_paths`, and `by_path` against §9 thresholds.
4. Fill `LeagueVault-Pilot-Log.md` and write the go/no-go.

## Decision thresholds (unchanged)

**Go:** unprompted engagement; ≥70% managers visit in 7d; median depth ≥4 paths; return visit week 2; ⭐ outward share / “do my other league?”; unprompted willingness to pay.

**No-go / reshape:** polite silence; one-and-done; identity correction ≫ 30 min/league.

## Ops (ship order)

```bash
cd backend
# DATABASE_URL + .env.leaguevault.local
alembic upgrade head
PYTHONPATH=. python3 scripts/league_vault/sync_pilot.py
PYTHONPATH=. python3 scripts/league_vault/compute_pilot.py \
  --overrides scripts/league_vault/seed_overrides.json
PYTHONPATH=. python3 scripts/league_vault/prod_verify_pilot.py \
  --api-url https://api.yetai.app
```

Then DNS wildcard → Vercel, iMessage OG smoke, post to both chats, log in `LeagueVault-Pilot-Log.md`.

## Non-goals (binding)

No Stripe, onboarding, commissioner UI, or themes in the pilot.

## Auto-update (synced leagues)

Public vault sites stay current without a manual `sync_pilot` pass:

1. **Celery Beat** — `league-vault-weekly-sync` (Tue 07:15 ET) runs `app.tasks.league_vault_sync.sync_all_vault_sites`: re-ingest every `is_public` site from Sleeper/ESPN, then **force** all-play + records.
2. **Stale recompute on GET** — if `lineage.last_synced` is newer than `lv_records.computed_at`, `GET /api/vault/{slug}` rebuilds the record book (no platform pull on the request path).
3. **Manual** — `PYTHONPATH=. python3 scripts/league_vault/refresh_pilot.py` (`--slug`, `--compute-only`).

Disable the weekly job with `LEAGUE_VAULT_AUTO_SYNC=false`. ESPN re-ingest requires `ESPN_S2` + `ESPN_SWID` on the worker.
