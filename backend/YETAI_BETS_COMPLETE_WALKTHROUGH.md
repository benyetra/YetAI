# YetAI Bets - Complete Implementation Walkthrough

## Overview
This document walks through the complete YetAI Bets flow from creation to settlement to tracking.

---

## Step 1: Admin Creates YetAI Bet ✅

**Endpoint**: `POST /api/admin/yetai-bets/create`

**What Happens**:
1. Admin submits bet details via admin tool including all required data:
   - `game_id`: Odds API event ID (from game selection)
   - `home_team`, `away_team`: Team names (from game selection)
   - `game`: Display string "Away Team @ Home Team"
   - `commence_time`: ISO format datetime (from game data)
   - `game_time`: Display string "10/13/2025 @01:00 PM EDT"
   - `sport`, `bet_type`, `pick`, `odds`, `confidence`, `reasoning`
2. System stores all provided data directly (NO parsing or lookups needed)
3. Creates bet in `yetai_bets` table with:
   - `id`: UUID
   - `game_id`: From request (Odds API event ID)
   - `home_team`, `away_team`: From request
   - `sport`, `bet_type`, `selection`, `odds`, `confidence`
   - `commence_time`: Parsed from ISO format
   - `status`: "pending"
   - `result`: null
   - `settled_at`: null

**Request Example**:
```json
{
    "sport": "NHL",
    "game": "Tampa Bay Lightning @ Boston Bruins",
    "game_id": "abc123xyz",
    "home_team": "Boston Bruins",
    "away_team": "Tampa Bay Lightning",
    "bet_type": "spread",
    "pick": "Boston Bruins +1.5",
    "odds": "-220",
    "confidence": 88,
    "reasoning": "Rivalry game, should be close in score.",
    "game_time": "10/13/2025 @01:00 PM EDT",
    "commence_time": "2025-10-13T13:00:00Z",
    "is_premium": false
}
```

**Response**:
```json
{
    "status": "success",
    "message": "YetAI Bet created successfully",
    "bet_id": "58b3b6ef-5558-4eed-b641-28ff333e65ee"
}
```

**Files Involved**:
- [bet_models.py:107-121](backend/app/models/bet_models.py#L107-L121) - Request model with required fields
- [yetai_bets_service_db.py:35-120](backend/app/services/yetai_bets_service_db.py#L35-L120) - Creation logic (no parsing)

---

## Step 2: Users View YetAI Bets ✅

**Endpoint**: `GET /api/yetai-bets`

**What Happens**:
1. Frontend fetches all active YetAI bets from API
2. Filters by user's subscription tier (free vs pro)
3. Displays bets with:
   - Game details
   - Pick/selection
   - Confidence score
   - Reasoning
   - "Place Bet" button (for upcoming games)
   - Result display (for completed games)

**Response Example**:
```json
{
    "status": "success",
    "bets": [
        {
            "id": "58b3b6ef-5558-4eed-b641-28ff333e65ee",
            "sport": "NHL",
            "game": "Tampa Bay Lightning @ Boston Bruins",
            "bet_type": "spread",
            "pick": "Boston Bruins +1.5",
            "odds": "-220",
            "confidence": 88,
            "reasoning": "Rivalry game, should be close in score. Taking the spread.",
            "is_premium": false,
            "game_time": "10/13/2025 @01:00 PM EDT",
            "status": "pending",
            "result": null
        }
    ]
}
```

**Files Involved**:
- [frontend/src/app/predictions/page.tsx](frontend/src/app/predictions/page.tsx) - Display component

---

## Step 3: User Places Bet from YetAI Pick ✅

**Endpoint**: `POST /api/unified-bets/place`

**What Happens**:
1. User clicks "Place Bet" on YetAI bet
2. Frontend sends bet request with:
   - `yetai_bet_id`: Links back to original YetAI bet
   - `amount`: User's bet amount
   - All bet details (odds, selection, game info)
3. Backend validates user balance and bet limits
4. Creates bet in `simple_unified_bets` table with:
   - `yetai_bet_id`: Links to YetAI bet for tracking
   - User's amount and calculated `potential_win`
   - Copies all game and bet details
   - `source`: "STRAIGHT"
   - `status`: "pending"
5. Deducts amount from user's balance

**Response**:
```json
{
    "success": true,
    "bet_id": "a7f8c2d4-1234-5678-90ab-cdef12345678",
    "message": "Bet placed successfully"
}
```

**Files Involved**:
- [main.py:122](backend/app/main.py#L122) - Added `yetai_bet_id` field to `PlaceBetRequest`
- [simple_unified_bet_model.py:138](backend/app/models/simple_unified_bet_model.py#L138) - Added `yetai_bet_id` column
- [simple_unified_bet_service.py:126](backend/app/services/simple_unified_bet_service.py#L126) - Stores `yetai_bet_id`

---

## Step 4: Game Ends & Bets Are Verified ✅

**Scheduler**: Runs every 15 minutes

**What Happens**:

### A) YetAI Bet Verification
1. Scheduler runs `verify_pending_yetai_bets()`
2. Gets all YetAI bets with `status = "pending"`
3. For each bet with a `game_id`:
   - Looks up game in database `games` table
   - Checks if `game.status = "FINAL"`
   - If final, gets `home_score` and `away_score`
   - Evaluates bet outcome:
     - **Moneyline**: Check if selected team won
     - **Spread**: Apply spread, check if covered
     - **Total**: Calculate total score, check over/under
   - Updates YetAI bet:
     - `status`: "won", "lost", or "pushed"
     - `result`: Human-readable description
     - `settled_at`: Current timestamp

### B) User Bet Verification
1. Scheduler runs `verify_all_pending_bets()` (unified bet service)
2. Gets all user bets from `simple_unified_bets` with `status = "pending"`
3. Verifies against Odds API game scores
4. Updates user bets with win/loss/push
5. Credits winnings to user balance

**Files Involved**:
- [yetai_bets_service_db.py:660-709](backend/app/services/yetai_bets_service_db.py#L660-L709) - YetAI bet verification
- [yetai_bets_service_db.py:542-658](backend/app/services/yetai_bets_service_db.py#L542-L658) - Outcome evaluation logic
- [bet_scheduler_service.py:160-207](backend/app/services/bet_scheduler_service.py#L160-L207) - Scheduler integration

---

## Step 5: Historical Tracking & Success Metrics ✅

**What We Can Track**:

### YetAI Bet Performance
```sql
SELECT
    COUNT(*) as total_bets,
    SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) as losses,
    SUM(CASE WHEN status = 'pushed' THEN 1 ELSE 0 END) as pushes,
    ROUND(100.0 * SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) / COUNT(*), 2) as win_rate
FROM yetai_bets
WHERE status IN ('won', 'lost', 'pushed');
```

### User Adoption Rate
```sql
SELECT
    yb.id as yetai_bet_id,
    yb.title,
    COUNT(sub.id) as times_placed_by_users,
    COUNT(DISTINCT sub.user_id) as unique_users
FROM yetai_bets yb
LEFT JOIN simple_unified_bets sub ON sub.yetai_bet_id = yb.id
GROUP BY yb.id, yb.title
ORDER BY times_placed_by_users DESC;
```

### User Success on YetAI Bets
```sql
SELECT
    u.username,
    COUNT(*) as yetai_bets_placed,
    SUM(CASE WHEN sub.status = 'won' THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN sub.status = 'won' THEN sub.result_amount ELSE 0 END) as total_winnings
FROM users u
JOIN simple_unified_bets sub ON sub.user_id = u.id
WHERE sub.yetai_bet_id IS NOT NULL
GROUP BY u.id, u.username;
```

**Frontend Display**:
- ✅ **Green "Won"** with checkmark icon
- ❌ **Red "Lost"** with X icon
- ⚪ **Gray "Push"** for ties
- ⏳ **"Game in Progress"** for pending past games
- 🎯 **"Place Bet"** only for upcoming games

---

## Database Schema Changes

### `yetai_bets` Table
- **Added**: `game_id` (links to `games` table)
- **Added**: `home_team`, `away_team` (parsed from game string)
- **Purpose**: Enable database-based verification instead of API

### `simple_unified_bets` Table
- **Added**: `yetai_bet_id` (links to `yetai_bets` table)
- **Purpose**: Track which YetAI bet the user placed from

### `games` Table
- **Commented Out**: `broadcast_info`, `is_nationally_televised`
- **Reason**: These columns don't exist in database yet (need migration)

---

## Key Implementation Files

1. **YetAI Bet Creation**:
   - [yetai_bets_service_db.py:35-162](backend/app/services/yetai_bets_service_db.py#L35-L162)

2. **YetAI Bet Verification**:
   - [yetai_bets_service_db.py:660-709](backend/app/services/yetai_bets_service_db.py#L660-L709)

3. **Win/Loss Evaluation**:
   - [yetai_bets_service_db.py:542-658](backend/app/services/yetai_bets_service_db.py#L542-L658)

4. **User Bet Placement**:
   - [simple_unified_bet_service.py:49-162](backend/app/services/simple_unified_bet_service.py#L49-L162)

5. **Scheduler Integration**:
   - [bet_scheduler_service.py:160-207](backend/app/services/bet_scheduler_service.py#L160-L207)

6. **Frontend Display**:
   - [frontend/src/app/predictions/page.tsx:270-421](frontend/src/app/predictions/page.tsx#L270-L421)

---

## Migration Scripts

### Backfill Existing Bets
- **Script**: [backfill_yetai_bet_game_ids.py](backend/scripts/backfill_yetai_bet_game_ids.py)
- **Purpose**: Updates existing YetAI bets with `game_id`, `home_team`, `away_team`
- **Usage**: `.venv/bin/python scripts/backfill_yetai_bet_game_ids.py`

---

## Testing Verification

### Manual Test
```python
import asyncio
from app.services.yetai_bets_service_db import YetAIBetsServiceDB

async def test():
    service = YetAIBetsServiceDB()
    result = await service.verify_pending_yetai_bets()
    print(result)

asyncio.run(test())
```

### Expected Result
```json
{
    "success": true,
    "verified": 5,
    "settled": 2
}
```

---

## Summary

✅ **Step 1**: Admin creates YetAI bet → Stored in `yetai_bets` table with `game_id`
✅ **Step 2**: Users view bets → Displayed at `/predictions` with "Place Bet" button
✅ **Step 3**: User places bet → Creates entry in `simple_unified_bets` with `yetai_bet_id` link
✅ **Step 4**: Game ends → Scheduler verifies both YetAI bets and user bets
✅ **Step 5**: Historical tracking → Query both tables to track performance and adoption

All code is formatted with Black and ready to commit! 🎉
