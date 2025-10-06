# Bet Verification System Fixes - January 2025

## Summary
Fixed critical issues in bet verification that were causing bets to show as pending or be incorrectly labeled as wins/losses.

## Problems Fixed

### 1. ✅ Removed Dual Table Confusion
**Problem**: Two separate bet systems (old `bets` table and new `simple_unified_bets` table) weren't syncing.

**Fix**:
- Deprecated old `bet_verification_service.py` → `DEPRECATED_bet_verification_service.py`
- Updated `bet_scheduler_service.py` to only use `unified_bet_verification_service.py`
- All bet creation now goes through `simple_unified_bet_service.py` → `simple_unified_bets` table
- All bet verification now uses `unified_bet_verification_service.py`

### 2. ✅ Fixed Score Matching by Team Name (Not Array Index)
**Problem**: Code assumed `scores[0]` was home and `scores[1]` was away, but Odds API doesn't guarantee order.

**Fix** (`unified_bet_verification_service.py:188-209`):
```python
# Match scores to home/away teams by name
for score_entry in scores:
    team_name = score_entry.get("name", "")
    if team_name == bet.home_team:
        home_score = int(score_value)
    elif team_name == bet.away_team:
        away_score = int(score_value)
```

### 3. ✅ Fixed Game Completion Check
**Problem**: Code checked `game_data.get("completed", False)` which could be None or missing.

**Fix** (`unified_bet_verification_service.py:176-180`):
```python
# Check if game is completed using the completed boolean field from Odds API
is_completed = game_data.get("completed")
if not is_completed:
    return None
```

### 4. ✅ Simplified Bet Verification Using Enums
**Problem**: Complex string parsing during verification (checking if "over" in selection.lower(), etc.)

**Fix**: Bet creation now stores structured data in enums that verification just reads:
- **Moneyline**: Uses `team_selection` enum (TeamSide.HOME or TeamSide.AWAY)
- **Spread**: Uses `spread_selection` enum + `spread_value` with +/- sign
- **Totals**: Uses `over_under_selection` enum (OverUnder.OVER or OverUnder.UNDER)

**Before** (complex string parsing):
```python
selection = bet.selection.lower()
is_over = "over" in selection or bet.over_under_selection == OverUnder.OVER
```

**After** (simple enum check):
```python
is_over = bet.over_under_selection == OverUnder.OVER
```

### 5. ✅ Fixed Spread Value to Include +/- Sign
**Problem**: Spread stored as `7.5` without sign, code didn't know if it was +7.5 or -7.5.

**Fix** (`simple_unified_bet_service.py:521-528`):
```python
spread_str = spread_match.group(1)
# Ensure we have a sign (default to negative if no sign present)
if not spread_str.startswith(('+', '-')):
    spread_str = '-' + spread_str
result["spread_value"] = float(spread_str)  # e.g., -7.5 or +3.5
```

### 6. ✅ Removed String Matching for Over/Under
**Problem**: Searched for "over"/"under" strings in selection text.

**Fix**: Uses `over_under_selection` enum set during bet creation:
```python
# During bet creation (simple_unified_bet_service.py:540-543)
if "over" in selection_lower:
    result["over_under_selection"] = OverUnder.OVER
elif "under" in selection_lower:
    result["over_under_selection"] = OverUnder.UNDER

# During verification (unified_bet_verification_service.py:331)
is_over = bet.over_under_selection == OverUnder.OVER
```

### 7. ✅ Ensured Status Comparisons Use Enums
**Problem**: Inconsistent string vs enum comparisons for bet status.

**Fix**: All code now uses `BetStatus` enum:
```python
if bet.status == BetStatus.PENDING  # ✅ Correct
# NOT: if bet.status == "pending"  # ❌ Wrong
```

### 8. ✅ Consolidated to Single Verification Path
**Problem**: Multiple services, unclear which to use.

**Fix**: Clear documentation in both services:
- `unified_bet_verification_service.py` - "THE ONLY SERVICE FOR BET VERIFICATION"
- `simple_unified_bet_service.py` - "THE ONLY SERVICE FOR BET CREATION"

## Files Modified

### Core Services
1. **app/services/unified_bet_verification_service.py** - Main verification logic
2. **app/services/simple_unified_bet_service.py** - Bet creation with proper enum storage
3. **app/services/bet_scheduler_service.py** - Updated to use unified service only

### Deprecated
4. **DEPRECATED_bet_verification_service.py** - Old service marked as deprecated

### Documentation
5. **BET_VERIFICATION_FIXES.md** - This file

## How It Works Now

### Bet Creation Flow
1. User places bet (moneyline/spread/total)
2. `simple_unified_bet_service._parse_bet_selection()` extracts:
   - Team selection (HOME/AWAY enum)
   - Spread value with sign (-7.5)
   - Over/under selection (OVER/UNDER enum)
   - Selected team name (exact match from API)
3. Bet stored in `simple_unified_bets` with all structured data

### Bet Verification Flow
1. Scheduler runs every 15 minutes
2. `unified_bet_verification_service.verify_all_pending_bets()`:
   - Queries `simple_unified_bets` for status = PENDING
   - Fetches scores from Odds API
   - Matches games by `odds_api_event_id`
   - Matches scores by team name (not array index)
   - Checks `completed` boolean explicitly
3. For each bet type:
   - **Moneyline**: Compares `team_selection` enum to actual winner
   - **Spread**: Adds `spread_value` (with sign) to selected team's score
   - **Total**: Compares total to line using `over_under_selection` enum
4. Updates bet status to WON/LOST/PUSHED using BetStatus enum

## Testing Recommendations

### Test Scenario 1: Moneyline Bet
```
Input: Bet on "Kansas City Chiefs" (home team)
Storage: team_selection = TeamSide.HOME, selected_team_name = "Kansas City Chiefs"
Verification: Match "Kansas City Chiefs" in scores array, compare to TeamSide.HOME
```

### Test Scenario 2: Spread Bet
```
Input: "Dallas Cowboys -7.5"
Storage: spread_value = -7.5, spread_selection = TeamSide.AWAY (if Cowboys are away)
Verification: away_score + (-7.5) > home_score ?
```

### Test Scenario 3: Total Bet
```
Input: "Over 45.5"
Storage: total_points = 45.5, over_under_selection = OverUnder.OVER
Verification: (home_score + away_score) > 45.5 ?
```

## What's Left to Implement

1. ❌ **Parlay Verification** - Currently returns PENDING (line 351-355 in unified service)
2. ✅ **Single Bet Verification** - Fully implemented
3. ✅ **Enum-based Selection** - Fully implemented
4. ✅ **Score Matching** - Fully implemented

## Migration Notes

If you have bets in the old `bets` table:
1. They will NOT be verified by the new system
2. Consider migrating them to `simple_unified_bets` with proper enum fields
3. Or let them expire and only verify new bets going forward

## Monitoring

Check these logs to verify fixes are working:
- `"Verifying bet {bet_id}: {bet_type} - {selection}"` - Shows bet being processed
- `"Final score: {away_team} {away_score} - {home_team} {home_score}"` - Shows matched scores
- `"Won: {team_name} won ({score})"` - Shows win determination logic
- `"Could not match scores to teams"` - ERROR: means team name mismatch

## Contact

Created: 2025-01-06
Last Updated: 2025-01-06
