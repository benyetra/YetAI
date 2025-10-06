# Quick Reference - Bet Verification System

## 🚀 Quick Start

```bash
# Validate changes
./validate_changes.sh

# Run tests
python3 test_unified_bet_verification.py

# Check syntax
python3 -m py_compile app/services/*.py
```

## 📁 Important Files

| File | Purpose |
|------|---------|
| `app/services/unified_bet_verification_service.py` | ✅ **USE THIS** - Main verification |
| `app/services/simple_unified_bet_service.py` | ✅ **USE THIS** - Bet creation |
| `app/services/bet_scheduler_service.py` | ✅ Updated to use unified |
| `DEPRECATED_bet_verification_service.py` | ❌ **DON'T USE** - Old service |

## 🔍 What Changed

| Issue | Solution |
|-------|----------|
| Dual tables | → Single `simple_unified_bets` table |
| Score index assumption | → Match by team name |
| String parsing | → Use enums (TeamSide, OverUnder) |
| Unsigned spreads | → Store with +/- sign |
| String status | → Use BetStatus enum |

## 📊 Enum Values

### BetStatus
```python
PENDING = "pending"
WON = "won"
LOST = "lost"
PUSHED = "pushed"
```

### TeamSide (moneyline, spread)
```python
HOME = "home"
AWAY = "away"
NONE = "none"
```

### OverUnder (totals)
```python
OVER = "over"
UNDER = "under"
NONE = "none"
```

## 🎯 Key Functions

### Verification
```python
# Check bet status
await unified_bet_verification_service.verify_all_pending_bets()

# Evaluate single bet type
_evaluate_moneyline(bet, home_score, away_score)
_evaluate_spread(bet, home_score, away_score)
_evaluate_total(bet, home_score, away_score)
```

### Bet Creation
```python
# Place bet with proper enums
await simple_unified_bet_service.place_bet(user_id, bet_data)

# Parse selection into enums
_parse_bet_selection(selection, bet_type, home_team, away_team)
```

## ✅ Verification Logic

### Moneyline
```python
actual_winner = TeamSide.HOME if home_score > away_score else TeamSide.AWAY
if bet.team_selection == actual_winner:
    return WON
```

### Spread
```python
adjusted_score = selected_team_score + bet.spread_value  # Already has +/-
if adjusted_score > opponent_score:
    return WON
```

### Total
```python
total = home_score + away_score
if bet.over_under_selection == OverUnder.OVER:
    return WON if total > bet.total_points else LOST
```

## 🔧 Database Schema

```sql
-- Key fields in simple_unified_bets
odds_api_event_id VARCHAR(255)  -- Match games
home_team VARCHAR(255)           -- Match scores
away_team VARCHAR(255)           -- Match scores

-- Moneyline
team_selection ENUM              -- TeamSide.HOME/AWAY
selected_team_name VARCHAR(255)

-- Spread
spread_value FLOAT               -- With +/- sign
spread_selection ENUM            -- TeamSide.HOME/AWAY

-- Total
total_points FLOAT
over_under_selection ENUM        -- OverUnder.OVER/UNDER

-- Status
status ENUM                      -- BetStatus.PENDING/WON/LOST
```

## 🧪 Test Cases

### Moneyline
```json
{
  "selection": "Kansas City Chiefs",
  "bet_type": "moneyline",
  "expected_storage": {
    "team_selection": "home",
    "selected_team_name": "Kansas City Chiefs"
  }
}
```

### Spread (Favorite)
```json
{
  "selection": "Dallas Cowboys -7.5",
  "bet_type": "spread",
  "expected_storage": {
    "spread_value": -7.5,
    "spread_selection": "home"
  }
}
```

### Spread (Underdog)
```json
{
  "selection": "Patriots +3.5",
  "bet_type": "spread",
  "expected_storage": {
    "spread_value": 3.5,
    "spread_selection": "away"
  }
}
```

### Total
```json
{
  "selection": "Over 45.5",
  "bet_type": "total",
  "expected_storage": {
    "total_points": 45.5,
    "over_under_selection": "over"
  }
}
```

## 🐛 Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| "Could not match scores" | Team name mismatch | Verify names from API |
| "Invalid spread value" | Missing +/- sign | Check bet creation |
| Status stays pending | Game not completed | Check `completed` field |
| Wrong win/loss | Wrong enum stored | Check bet creation logic |

## 📝 Checklist

### Before Deploying
- [ ] Run `./validate_changes.sh`
- [ ] Run `python3 -m py_compile app/services/*.py`
- [ ] Review documentation
- [ ] Test with sample bets

### After Deploying
- [ ] Monitor scheduler status
- [ ] Check verification stats
- [ ] Verify no bets stuck pending
- [ ] Confirm win/loss accuracy

## 🔗 Related Docs

- **[BET_VERIFICATION_FIXES.md](BET_VERIFICATION_FIXES.md)** - Detailed fixes
- **[TESTING_GUIDE.md](TESTING_GUIDE.md)** - Test instructions
- **[CHANGES_SUMMARY.md](CHANGES_SUMMARY.md)** - Executive summary

## 💡 Tips

1. **Always use enums** - Never compare with strings
2. **Match by name** - Never assume array order
3. **Check completed** - Use explicit boolean check
4. **Signed spreads** - Store with +/- for correct math
5. **Log everything** - Helps debug verification issues

---

**Quick Validation:** `./validate_changes.sh`
**Quick Test:** `python3 test_unified_bet_verification.py`
