# League Vault Pilot PRD

**Two real league history sites, on real infrastructure, to decide whether this is a business**

| | |
|---|---|
| **Status** | Phase 2 complete on this branch — identity, all-play/luck, records, snapshot |
| **Author** | Bennett |
| **Date** | 2026-08-06 |
| **Supersedes for now** | `LeagueVault-PRD.md` (commercial product — parked, not cancelled) |
| **Scope** | Bennett's Sleeper league + ESPN league `838295` |
| **Target** | Live before Week 1 of the 2026 NFL season |

## Pilot leagues

| League | Platform | Slug (provisional) | Seasons |
|--------|----------|--------------------|---------|
| Mike's Hard Fantasy Football | Sleeper | `mikes-hard` | 2021–2026 (12 teams) |
| ESPN `838295` | ESPN | `league-838295` | 2017–2026 (12→10 teams) |

## Phases

| Phase | Scope | Status |
|-------|--------|--------|
| **P0** | API spike + fixtures | ✅ Green (Sleeper chain + ESPN history with `view=mMatchup`) |
| **P1** | `lv_*` schema, ingest, normalizer, sync CLI | ✅ Models + migration + tests on this branch; prior prod ingest on local |
| **P2** | Identity overrides, all-play/luck, record book, snapshot JSON | ✅ This branch |
| **P3** | Wildcard DNS, `/vault/[slug]` pages, OG images, mobile | Next |
| **P4** | Ship links to group chats; go/no-go | Planned |

## Non-goals (binding)

No Stripe, no self-serve onboarding, no commissioner admin UI, no themes, no auth on vault pages, no weekly automated sync (manual CLI is fine).

## Schema (`lv_*`)

`lv_league_lineage`, `lv_sites`, `lv_managers`, `lv_seasons`, `lv_teams`, `lv_matchups`, `lv_transactions`, `lv_drafts`, `lv_draft_picks`, `lv_records` (lineage-scoped: `record_key`, `scope`, `context`, `computed_at`), `lv_sync_jobs`.

Deferred: `lv_roster_spots`, custom trophies, billing columns.

## P2 deliverables

| Module | Path |
|--------|------|
| Identity overrides | `app/services/league_vault/identity/resolver.py` + `scripts/league_vault/seed_overrides.json` |
| All-play / luck | `app/services/league_vault/compute/standings.py` |
| Record book | `app/services/league_vault/compute/records.py` |
| Snapshot | `app/services/league_vault/publish/snapshot.py` |
| CLI | `scripts/league_vault/compute_pilot.py` |

Record keys include: highest/lowest single-week score, biggest blowout, closest game, most points in a loss, fewest in a win, highest combined, highest season PF/PPG, best/worst regular-season record, win/loss streaks, titles, career wins, all-play / luck leaders.

Snapshots omit `platform_user_id` / SWID (public boundary).

## Ops

```bash
cd backend
# after DATABASE_URL + .env.leaguevault.local
PYTHONPATH=. python3 scripts/league_vault/sync_pilot.py
PYTHONPATH=. python3 scripts/league_vault/compute_pilot.py \
  --overrides scripts/league_vault/seed_overrides.json
```

Snapshots write to `scripts/league_vault_snapshots/` (gitignored).
