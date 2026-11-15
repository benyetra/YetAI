# Fair-price backtest on the 2025-26 NBA season (2026-11-14)

Result of the pre-registered test in docs/edge-engine-design.md ("Backtest decision criteria",
committed in a4f1661e and 8070fffd before this was computed).

## Verdict: INCONCLUSIVE, case (a)

Flags beat the closing no-vig consensus clearly (CLV +1.35 probability points, interval +1.17 to
+1.53, on 3,421 flags), but the return at the flagged price is -3.0% with an interval of -7.0% to
+0.9%. Under the rule written beforehand that means: build the live fair-price flags in shadow
only (Phase 1a), publish nothing, and let 300 live flags decide. The pipeline checks passed: the
sign-flip placebo returned what a coin flip should (12.0% vs 11.4% expected, within 1.96 se), and
random book/random side quotes lose (CLV -3.6 points, ROI -5.2%).

In plain words: the method finds prices that the market then moves toward, which is the sign of
a real edge, but on last season's rebounds and assists that edge was not large enough, after
the books' margin, to show a profit with any confidence. Most flags (66%) came from the two
exchanges, where the edge was smallest; the retail-book flags look much better (see the
exploratory table), but that cut was chosen after seeing the data, so it is a hypothesis for the
live shadow period, not a finding.

## Data (what was bought)
- Odds API historical event odds, 2025-26 regular season Nov 1 - Apr 12: 1,139 games (every game
  with box scores in production), 3 snapshots per game requested at 600, 360 and 5 minutes before
  the scheduled start (returned snapshots are 2.5-5 min earlier; the close is 5-10 min before
  tip), markets player_rebounds + player_assists, books fanduel, draftkings, betmgm,
  williamhill_us, espnbet, betrivers, hardrockbet, pinnacle, novig, prophetx (one region).
- 3,417 event-odds calls + 154 events calls; 3,412 returned both markets, 1 returned one, 4
  returned none (free); 2 HTTP 502s were retried. Every paid call cost exactly 10 x markets
  returned (x-requests-last). Credits: 68,444 for the backfill (68,290 odds + 154 events),
  plus 51 for the probe; quota after: 31,413 remaining of 100,000.
- Loaded locally through the live parser: 794,386 snapshot rows (226 MB with indexes), each book
  on 1,111-1,138 of the 1,139 events. Raw files (136 MB) kept under
  .factory/edge-engine-plan/artifacts/odds_history/nba_2025-26/.
- Props replayed: 35,462 (player x market x game). Flags: 9,066 in all; 3,421 primary (first flag
  per player, book and side at T-600 or T-360, graded); 1,174 primary flags were void (1,044 no box
  score, the player did not play or is missing from pred_recent_games; 130 names not mapped).

## Primary result (rule defaults: EV >= 5%, >= 3 other books, power de-vig, walk-forward weights)
| set | n | CLV (pp) | 95% CI | CLV > 0 | hit rate | 95% CI | ROI | 95% CI | claimed EV | median price |
|---|---|---|---|---|---|---|---|---|---|---|
| primary flags | 3,421 | +1.35 | +1.17, +1.53 | 64% | 45.8% | 44.1, 47.5 | -3.0% | -7.0, +0.9 | 7.2% | +106 |
| closing-snapshot flags (ROI only) | 2,985 | - | - | - | 47.2% | 45.5, 49.0 | +1.5% | -2.2, +5.3 | 7.8% | +106 |
| random book, random side | 3,421 | -3.59 | -3.81, -3.37 | 25% | 50.5% | 48.8, 52.2 | -5.2% | -8.3, -2.1 | - | -113 |
Paired CLV difference (flag minus its random draw): +4.93 points (+4.63, +5.24).
Intervals are clustered by game date (153 dates); hit rates are Wilson.

By market (secondary; does not change the verdict):
| market | n | CLV (pp) | 95% CI | ROI | 95% CI | secondary verdict |
|---|---|---|---|---|---|---|
| assists | 1,456 | +1.55 | +1.27, +1.83 | +0.1% | -6.0, +6.1 | GO |
| rebounds | 1,965 | +1.21 | +0.98, +1.44 | -5.3% | -10.2, -0.4 | NO GO |

By book:
| book | n | CLV (pp) | 95% CI | hit rate | ROI | 95% CI | median price |
|---|---|---|---|---|---|---|---|
| novig | 1,391 | +0.33 | +0.05, +0.61 | 43.7% | -3.9% | -9.6, +1.8 | +120 |
| prophetx | 865 | +1.02 | +0.72, +1.31 | 44.1% | -5.1% | -12.6, +2.4 | +110 |
| hardrockbet | 527 | +3.09 | +2.64, +3.55 | 51.4% | +0.5% | -7.9, +8.8 | -105 |
| espnbet | 210 | +1.10 | +0.53, +1.68 | 31.4% | -13.2% | -30.3, +4.0 | +220 |
| betmgm | 190 | +3.32 | +2.60, +4.04 | 53.7% | -2.6% | -16.9, +11.7 | -120 |
| betrivers | 117 | +4.25 | +3.23, +5.26 | 56.4% | +8.4% | -6.5, +23.2 | -107 |
| draftkings | 77 | +1.94 | +0.13, +3.75 | 55.8% | +7.1% | -17.4, +31.6 | -110 |
| fanduel | 31 | +2.06 | -0.08, +4.20 | 67.7% | +25.6% | -0.1, +51.3 | -106 |
| williamhill_us | 13 | +6.37 | +0.98, +11.76 | 61.5% | +15.3% | -40.5, +71.1 | -110 |

By claimed edge: CLV rises with the claimed EV (5-7.5%: +0.89; 7.5-10%: +1.95; 10-15%: +3.09;
15%+: +6.36 points), the dose-response a real signal should show; ROI is noisy in every bucket.
By hours before tip: T-600 flags (>= 9 h) CLV +1.03 (+0.75, +1.31); T-360 flags (6-9 h) +1.68
(+1.43, +1.92); ROI -3.1% and -3.0%. Earlier is not better on this data.

De-vig method at the close (log loss of the equal-weight consensus, ~23,000 props): the four
methods agree to the fourth decimal (assists 0.6851-0.6853, rebounds 0.6868-0.6869); power is
not better than multiplicative near even money, as expected. Keep power for lopsided lines.

Walk-forward weights moved toward prophetx/novig on assists (1.3-2.6) and espnbet/fanduel on
rebounds (1.2-1.6), pinnacle about 1.0, hardrockbet/betrivers lowest (0.6-0.8).

## Exploratory cuts (chosen after seeing the result; not part of the verdict)
| cut | n | CLV (pp) | 95% CI | hit rate | ROI | 95% CI |
|---|---|---|---|---|---|---|
| retail books (not novig/prophetx) | 1,165 | +2.82 | +2.53, +3.11 | 49.5% | -0.4% | -6.2, +5.3 |
| retail books excluding espnbet | 955 | +3.20 | +2.85, +3.54 | 53.5% | +2.4% | -3.5, +8.2 |
| exchanges (novig, prophetx) | 2,256 | +0.59 | +0.38, +0.81 | 43.9% | -4.4% | -9.5, +0.8 |
| overs | 2,063 | +1.18 | +0.89, +1.47 | 46.7% | -1.0% | -6.6, +4.6 |
| unders | 1,358 | +1.62 | +1.31, +1.93 | 44.4% | -6.1% | -12.4, +0.2 |
| price +150 or longer | 637 | +0.85 | +0.51, +1.19 | 33.3% | -3.4% | -14.5, +7.7 |

## What this means for the build (per the pre-committed rule)
- Build Phase 1a in shadow: live flags for rebounds and assists, graded daily on CLV and ROI, no
  publishing. Decision after 300 live flags, using the same GO rule.
- Hypotheses to test in the shadow period, fixed now: (1) retail books only (exchanges as
  consensus inputs but not flagged, `FAIR_PRICE_EXCLUDED_BOOKS` does not do this today: it removes
  a book from the consensus too, so a "consensus-only" list is **to build**); (2) espnbet
  alternate lines excluded from flagging; (3) EV threshold kept at 5% (the 10%+ buckets have
  more CLV but too few flags).
- Exchanges: their flagged prices are mostly plus-money (median +110 to +120) and their
  CLV is near zero. Either their posted prices are thin resting orders that the feed reports but
  that rarely matter, or our consensus is mis-weighted toward them. Not resolved by this data.
- What this cannot answer: points and the other markets (not bought), the playoffs and October
  (cut for budget), whether flags were fillable at the stated price and size, and live latency
  (three snapshots a game, not a stream).

## Reproduce
From the edge-engine-plan worktree backend/, against a local Postgres copy (never production):
```
DATABASE_URL=postgresql://postgres@localhost:<port>/<db> DEBUG=false PYTHONPATH=. \
  .venv/bin/python scripts/odds_history_backfill.py load --dir <area>/artifacts/odds_history/nba_2025-26 --apply
DATABASE_URL=... PYTHONPATH=. .venv/bin/python scripts/fair_price_backtest.py \
  --from 2025-11-01 --to 2026-04-12 --markets player_rebounds,player_assists --out <dir>
```
The run takes about 45 seconds; summary.json and flags.csv are byte-identical across runs.
