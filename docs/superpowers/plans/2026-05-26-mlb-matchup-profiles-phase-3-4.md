# MLB Matchup Profiles — Phase 3–4 (implemented)

**Spec:** `docs/superpowers/specs/2026-05-25-mlb-matchup-profiles-roadmap.md`

## Phase 3 — Strikeout integration

- `profiles/matchup_k.py` — `ProfileStore` → legacy tensor shapes, `MatchupResult(source)`
- `lineup_utils.lineup_matchup_adjusted_strikeouts` — profile path when `MLB_PROFILES_ENABLED=1`
- `strikeouts.py` — logs `matchup_source`
- `mlb_matchup_analysis.matchup_adjusted_strikeouts` — profile-aware single batter
- `backtest/cli.py --use-profiles` — sets env flag for holdout runs

**Enable in prod:** `MLB_PROFILES_ENABLED=1` after snapshots exist.

## Phase 4 — Hits / HR contact

- Batter snapshots: `xwoba_by_pitch`, `iso_by_pitch`, `barrel_rate_by_pitch`
- `profiles/matchup_contact.py` — `contact_matchup_score`
- `hits.py` — adjusts `combined_score` / `homer_score`; persists `profile_version`, `matchup_contact_score`
- Alembic `20260526_hitter_profile_meta` on `pred_hitter` / `pred_homer`
- `dingerParlay/daily_features.py` — optional `matchup_contact_score` column

**Enable in prod:** same flag + migration + profile rebuild.
