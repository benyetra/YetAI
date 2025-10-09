# Testing Guide for Bet Verification Fixes

## Overview
This guide covers how to test the updated bet verification system to ensure all fixes are working correctly.

## Quick Validation

### 1. Syntax & Import Validation
```bash
cd /Users/byetz/Development/YetAI/YetAI/backend
./validate_changes.sh
```

This will check:
- ✅ Python syntax in all modified files
- ✅ No imports of old BetVerificationService
- ✅ Unified service is properly used
- ✅ Enum usage (no string comparisons)
- ✅ Score matching by team name
- ✅ Proper documentation

Expected output: **✅ ALL VALIDATION CHECKS PASSED**

### 2. Unit Tests (with database)
```bash
cd /Users/byetz/Development/YetAI/YetAI/backend
python3 test_unified_bet_verification.py
```

This will test:
- ✅ Moneyline bets store `team_selection` enum
- ✅ Spread bets store `spread_value` with +/- sign
- ✅ Total bets store `over_under_selection` enum
- ✅ Status uses `BetStatus` enum (not strings)
- ✅ Odds API event ID is stored
- ✅ Verification service is available

Expected output: **🎉 ALL TESTS PASSED!**

## Manual Testing Steps

### Step 1: Start the Application
```bash
cd /Users/byetz/Development/YetAI/YetAI/backend
# Start your backend server
python3 -m uvicorn app.main:app --reload
```

### Step 2: Create Test Bets

Use the API or admin interface to create bets with the following scenarios:

#### Test Case 1: Moneyline Bet
```json
{
  "game_id": "valid_odds_api_event_id",
  "bet_type": "moneyline",
  "selection": "Kansas City Chiefs",
  "odds": -150,
  "amount": 100,
  "home_team": "Kansas City Chiefs",
  "away_team": "Buffalo Bills",
  "sport": "americanfootball_nfl",
  "commence_time": "2025-01-07T18:00:00Z"
}
```

**Expected Storage:**
- `team_selection` = `TeamSide.HOME`
- `selected_team_name` = "Kansas City Chiefs"
- `status` = `BetStatus.PENDING`

#### Test Case 2: Spread Bet (Favorite)
```json
{
  "game_id": "valid_odds_api_event_id",
  "bet_type": "spread",
  "selection": "Dallas Cowboys -7.5",
  "odds": -110,
  "amount": 100,
  "home_team": "Dallas Cowboys",
  "away_team": "Philadelphia Eagles",
  "sport": "americanfootball_nfl",
  "commence_time": "2025-01-07T20:00:00Z"
}
```

**Expected Storage:**
- `spread_value` = `-7.5` (negative value)
- `spread_selection` = `TeamSide.HOME`
- `selected_team_name` = "Dallas Cowboys"

#### Test Case 3: Spread Bet (Underdog)
```json
{
  "game_id": "valid_odds_api_event_id",
  "bet_type": "spread",
  "selection": "New England Patriots +3.5",
  "odds": -110,
  "amount": 100,
  "home_team": "Miami Dolphins",
  "away_team": "New England Patriots",
  "sport": "americanfootball_nfl",
  "commence_time": "2025-01-07T13:00:00Z"
}
```

**Expected Storage:**
- `spread_value` = `+3.5` (positive value)
- `spread_selection` = `TeamSide.AWAY`
- `selected_team_name` = "New England Patriots"

#### Test Case 4: Over Bet
```json
{
  "game_id": "valid_odds_api_event_id",
  "bet_type": "total",
  "selection": "Over 45.5",
  "odds": -110,
  "amount": 100,
  "home_team": "Green Bay Packers",
  "away_team": "Chicago Bears",
  "sport": "americanfootball_nfl",
  "commence_time": "2025-01-07T16:25:00Z"
}
```

**Expected Storage:**
- `total_points` = `45.5`
- `over_under_selection` = `OverUnder.OVER`

#### Test Case 5: Under Bet
```json
{
  "game_id": "valid_odds_api_event_id",
  "bet_type": "total",
  "selection": "Under 52.5",
  "odds": -110,
  "amount": 100,
  "home_team": "Denver Broncos",
  "away_team": "Las Vegas Raiders",
  "sport": "americanfootball_nfl",
  "commence_time": "2025-01-07T19:15:00Z"
}
```

**Expected Storage:**
- `total_points` = `52.5`
- `over_under_selection` = `OverUnder.UNDER`

### Step 3: Verify Data Storage

Check the database to ensure bets are stored correctly:

```sql
-- Check moneyline bet
SELECT
    id,
    selection,
    team_selection,
    selected_team_name,
    status
FROM simple_unified_bets
WHERE bet_type = 'moneyline'
ORDER BY placed_at DESC
LIMIT 1;

-- Check spread bet (should have +/- sign)
SELECT
    id,
    selection,
    spread_value,
    spread_selection,
    selected_team_name
FROM simple_unified_bets
WHERE bet_type = 'spread'
ORDER BY placed_at DESC
LIMIT 1;

-- Check total bet
SELECT
    id,
    selection,
    total_points,
    over_under_selection
FROM simple_unified_bets
WHERE bet_type = 'total'
ORDER BY placed_at DESC
LIMIT 1;
```

**Verify:**
- ✅ `team_selection` is 'home' or 'away' (not 'none')
- ✅ `spread_value` is negative for favorites (e.g., -7.5)
- ✅ `spread_value` is positive for underdogs (e.g., +3.5)
- ✅ `over_under_selection` is 'over' or 'under' (not 'none')
- ✅ `status` is 'pending' (not 'PENDING' string)

### Step 4: Test Verification

#### Manual Verification Trigger
```bash
# Use the admin API endpoint
curl -X POST http://localhost:8000/api/admin/bets/verify \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json"
```

Or use the test script:
```bash
python3 test_bet_verification.py
```

#### Check Logs
Look for these log entries:
```
🎯 Starting unified bet verification...
Verifying bet {bet_id}: {bet_type} - {selection}
Final score: {away_team} {away_score} - {home_team} {home_score}
✅ Updated bet {bet_id}: {status} - {reasoning}
```

**Good signs:**
- ✅ "Matched scores to home/away teams by name"
- ✅ "Game completed=True"
- ✅ "Won: {team} won (27-24)" or "Lost: {team} lost (27-24)"

**Bad signs (these should NOT appear):**
- ❌ "Could not match scores to teams"
- ❌ "Invalid spread value"
- ❌ "Cannot parse total from selection"

### Step 5: Verify Outcomes

After games complete, check that:

1. **Moneyline Bets:**
   - If selected team won → Status = `won`
   - If selected team lost → Status = `lost`
   - If tie → Status = `pushed`

2. **Spread Bets:**
   - If team + spread > opponent → Status = `won`
   - If team + spread < opponent → Status = `lost`
   - If team + spread = opponent → Status = `pushed`

3. **Total Bets:**
   - If OVER and total > line → Status = `won`
   - If UNDER and total < line → Status = `won`
   - If total = line → Status = `pushed`

## Integration Testing

### Automated Scheduler Test
The scheduler runs every 15 minutes automatically. To test:

1. Create bets on completed games
2. Wait for next scheduler run (max 15 minutes)
3. Check bet history endpoint
4. Verify bets are settled correctly

### Check Scheduler Status
```bash
curl http://localhost:8000/api/admin/bets/verification/stats \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

Expected response:
```json
{
  "status": {
    "running": true,
    "in_quiet_hours": false
  },
  "stats": {
    "total_runs": 10,
    "successful_runs": 10,
    "total_bets_verified": 25,
    "total_bets_settled": 25
  }
}
```

## Common Issues & Troubleshooting

### Issue: Bets Stay Pending
**Check:**
1. Game has `completed: true` in Odds API response
2. `odds_api_event_id` matches API game ID
3. Team names exactly match API response
4. Scheduler is running

### Issue: Wrong Win/Loss
**Check:**
1. Spread value has correct +/- sign
2. Team selection enum is correct (HOME vs AWAY)
3. Scores matched to correct teams
4. Check logs for reasoning

### Issue: Import Errors
**Check:**
1. Old `bet_verification_service` not imported
2. Using `unified_bet_verification_service`
3. All enum imports from `simple_unified_bet_model`

## Success Criteria

✅ **All validation checks pass**
✅ **Unit tests pass (or skip with "no data")**
✅ **Bets created with proper enum fields**
✅ **Verification matches scores by team name**
✅ **Status comparisons use enums**
✅ **Spread values include +/- sign**
✅ **No string parsing during verification**
✅ **Bets settle correctly after games complete**

## Files Modified

- `app/services/unified_bet_verification_service.py` - Main verification logic
- `app/services/simple_unified_bet_service.py` - Bet creation with enums
- `app/services/bet_scheduler_service.py` - Uses unified service
- `DEPRECATED_bet_verification_service.py` - Old service marked deprecated

## Documentation

See [BET_VERIFICATION_FIXES.md](BET_VERIFICATION_FIXES.md) for detailed explanation of all changes.

## Support

If you encounter issues:
1. Run `./validate_changes.sh` first
2. Check application logs for error messages
3. Verify database has correct enum values
4. Ensure Odds API key is valid and has credits

---
Last Updated: 2025-01-06
