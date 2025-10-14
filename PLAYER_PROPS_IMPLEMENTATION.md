# Player Props Implementation Guide

## Overview

This document describes the complete player props betting implementation for YetAI. Player props allow users to bet on individual player statistics (e.g., passing yards, points scored, rebounds) across NFL, NBA, NHL, and MLB games.

**Current Status:** Backend complete, ready for frontend integration
**Bookmaker:** Limited to FanDuel only (to conserve API quota)
**Sports Supported:** NFL, NBA, NHL, MLB

---

## Architecture

### Data Flow

```
User → Frontend → API Endpoints → PlayerPropsService → Odds API
                                        ↓
                              SimplifiedUnifiedBet
                                        ↓
                              PostgreSQL Database
```

### Key Components

1. **PlayerPropsService** ([player_props_service.py](YetAI/backend/app/services/player_props_service.py))
   - Fetches player prop markets from The Odds API
   - Organizes props by market and player
   - Converts market keys to human-readable names

2. **SimpleUnifiedBet Model** ([simple_unified_bet_model.py](YetAI/backend/app/models/simple_unified_bet_model.py:109-115))
   - Extended with player prop fields:
     - `player_name` - Player name for prop bets
     - `prop_market` - Market key (e.g., `player_pass_tds`)
     - `prop_line` - The line/point value
     - `prop_selection` - Over or Under

3. **Bet Placement** ([simple_unified_bet_service.py](YetAI/backend/app/services/simple_unified_bet_service.py))
   - Handles player prop bet creation
   - Supports both single bets and parlay legs
   - Stores all prop metadata for tracking

4. **Verification Service** ([unified_bet_verification_service.py](YetAI/backend/app/services/unified_bet_verification_service.py:291-295))
   - Player props skip auto-verification (require external stats data)
   - Marked for manual verification

---

## API Endpoints

### 1. Get Player Props for Event

**Endpoint:** `GET /api/player-props/{sport}/{event_id}`

**Parameters:**
- `sport` (required): Sport key (`americanfootball_nfl`, `basketball_nba`, `icehockey_nhl`, `baseball_mlb`)
- `event_id` (required): Odds API event ID
- `markets` (optional): Comma-separated list of specific markets to fetch

**Example Request:**
```bash
curl "https://api.yetai.app/api/player-props/americanfootball_nfl/abc123?markets=player_pass_tds,player_pass_yds"
```

**Example Response:**
```json
{
  "status": "success",
  "data": {
    "event_id": "abc123",
    "sport_key": "americanfootball_nfl",
    "sport_title": "NFL",
    "commence_time": "2025-01-15T18:00:00Z",
    "home_team": "Kansas City Chiefs",
    "away_team": "Buffalo Bills",
    "markets": {
      "player_pass_tds": {
        "market_key": "player_pass_tds",
        "last_update": "2025-01-15T12:00:00Z",
        "players": [
          {
            "player_name": "Patrick Mahomes",
            "line": 1.5,
            "over": -150,
            "under": +120
          },
          {
            "player_name": "Josh Allen",
            "line": 1.5,
            "over": -180,
            "under": +140
          }
        ]
      }
    }
  }
}
```

### 2. Get Available Markets for Sport

**Endpoint:** `GET /api/player-props/markets/{sport}`

**Parameters:**
- `sport` (required): Sport key

**Example Request:**
```bash
curl "https://api.yetai.app/api/player-props/markets/americanfootball_nfl"
```

**Example Response:**
```json
{
  "status": "success",
  "sport": "americanfootball_nfl",
  "markets": [
    {
      "key": "player_pass_tds",
      "display_name": "Pass Touchdowns"
    },
    {
      "key": "player_pass_yds",
      "display_name": "Pass Yards"
    },
    {
      "key": "player_rush_yds",
      "display_name": "Rush Yards"
    }
  ]
}
```

### 3. Place Player Prop Bet

**Endpoint:** `POST /api/bets/place`

**Request Body:**
```json
{
  "bet_type": "prop",
  "selection": "Patrick Mahomes Over 1.5 Passing TDs",
  "odds": -150,
  "amount": 50,
  "game_id": "abc123",
  "home_team": "Kansas City Chiefs",
  "away_team": "Buffalo Bills",
  "sport": "americanfootball_nfl",
  "commence_time": "2025-01-15T18:00:00Z",
  "player_name": "Patrick Mahomes",
  "prop_market": "player_pass_tds",
  "prop_line": 1.5,
  "prop_selection": "over"
}
```

**Response:**
```json
{
  "status": "success",
  "bet_id": "uuid-here",
  "message": "Bet placed successfully",
  "bet": {
    "id": "uuid-here",
    "bet_type": "prop",
    "player_name": "Patrick Mahomes",
    "prop_market": "player_pass_tds",
    "prop_line": 1.5,
    "prop_selection": "over",
    "odds": -150,
    "amount": 50,
    "potential_win": 33.33,
    "status": "pending"
  }
}
```

---

## Available Markets by Sport

### NFL (18 markets)
- `player_pass_tds` - Passing Touchdowns
- `player_pass_yds` - Passing Yards
- `player_pass_completions` - Pass Completions
- `player_pass_attempts` - Pass Attempts
- `player_pass_interceptions` - Interceptions Thrown
- `player_pass_longest_completion` - Longest Completion
- `player_rush_yds` - Rushing Yards
- `player_rush_attempts` - Rush Attempts
- `player_rush_longest` - Longest Rush
- `player_receptions` - Receptions
- `player_reception_yds` - Receiving Yards
- `player_reception_longest` - Longest Reception
- `player_kicking_points` - Kicker Points
- `player_field_goals` - Field Goals Made
- `player_tackles_assists` - Tackles + Assists
- `player_1st_td` - First Touchdown Scorer
- `player_last_td` - Last Touchdown Scorer
- `player_anytime_td` - Anytime Touchdown Scorer

### NBA (14 markets)
- `player_points` - Points Scored
- `player_rebounds` - Total Rebounds
- `player_assists` - Assists
- `player_threes` - 3-Pointers Made
- `player_blocks` - Blocks
- `player_steals` - Steals
- `player_turnovers` - Turnovers
- `player_points_rebounds_assists` - Points + Rebounds + Assists
- `player_points_rebounds` - Points + Rebounds
- `player_points_assists` - Points + Assists
- `player_rebounds_assists` - Rebounds + Assists
- `player_blocks_steals` - Blocks + Steals
- `player_double_double` - Double Double
- `player_triple_double` - Triple Double

### NHL (9 markets)
- `player_points` - Points (Goals + Assists)
- `player_assists` - Assists
- `player_shots_on_goal` - Shots on Goal
- `player_blocked_shots` - Blocked Shots
- `player_goalie_saves` - Goalie Saves
- `player_goalie_shutout` - Goalie Shutout
- `player_power_play_points` - Power Play Points
- `player_anytime_goal_scorer` - Anytime Goal Scorer
- `player_first_goal` - First Goal Scorer

### MLB (13 markets)
- `player_hits` - Hits
- `player_total_bases` - Total Bases
- `player_runs` - Runs Scored
- `player_rbis` - RBIs
- `player_home_runs` - Home Runs
- `player_stolen_bases` - Stolen Bases
- `player_strikeouts` - Batter Strikeouts
- `player_pitcher_strikeouts` - Pitcher Strikeouts
- `player_hits_allowed` - Hits Allowed (Pitcher)
- `player_walks` - Walks (Batter)
- `player_pitcher_walks` - Walks Allowed (Pitcher)
- `player_earned_runs` - Earned Runs (Pitcher)
- `player_outs` - Outs Pitched

---

## Database Schema

### New Fields in `simple_unified_bets` Table

```sql
ALTER TABLE simple_unified_bets ADD COLUMN player_name VARCHAR(255);
ALTER TABLE simple_unified_bets ADD COLUMN prop_market VARCHAR(100);
ALTER TABLE simple_unified_bets ADD COLUMN prop_line FLOAT;
ALTER TABLE simple_unified_bets ADD COLUMN prop_selection VARCHAR(10); -- 'over', 'under', 'none'
```

**Migration Required:** Yes, database migration needed to add these columns.

---

## Frontend Integration Guide

### 1. Fetching Player Props for a Game

```typescript
// frontend/src/lib/api.ts
export async function getPlayerProps(
  sport: string,
  eventId: string,
  markets?: string[]
): Promise<PlayerPropsResponse> {
  const params = new URLSearchParams();
  if (markets && markets.length > 0) {
    params.append('markets', markets.join(','));
  }

  const response = await fetch(
    `${API_URL}/api/player-props/${sport}/${eventId}?${params}`,
    {
      headers: {
        'Authorization': `Bearer ${getToken()}`
      }
    }
  );

  return await response.json();
}
```

### 2. Displaying Player Props

```tsx
// Example component
interface PlayerProp {
  player_name: string;
  line: number;
  over: number;
  under: number;
}

function PlayerPropsCard({ eventId, sport }: { eventId: string, sport: string }) {
  const [props, setProps] = useState<PlayerPropsResponse | null>(null);

  useEffect(() => {
    getPlayerProps(sport, eventId, ['player_pass_tds', 'player_pass_yds'])
      .then(setProps);
  }, [eventId, sport]);

  return (
    <div>
      {props?.data.markets.player_pass_tds?.players.map((prop: PlayerProp) => (
        <div key={prop.player_name}>
          <h3>{prop.player_name}</h3>
          <p>Line: {prop.line}</p>
          <button onClick={() => placeProp(prop, 'over')}>
            Over {prop.over > 0 ? `+${prop.over}` : prop.over}
          </button>
          <button onClick={() => placeProp(prop, 'under')}>
            Under {prop.under > 0 ? `+${prop.under}` : prop.under}
          </button>
        </div>
      ))}
    </div>
  );
}
```

### 3. Placing a Player Prop Bet

```typescript
async function placeProp(prop: PlayerProp, selection: 'over' | 'under') {
  const betData = {
    bet_type: 'prop',
    selection: `${prop.player_name} ${selection} ${prop.line} Passing TDs`,
    odds: selection === 'over' ? prop.over : prop.under,
    amount: betAmount,
    game_id: eventId,
    home_team: gameData.home_team,
    away_team: gameData.away_team,
    sport: gameData.sport,
    commence_time: gameData.commence_time,
    // Player prop specific fields
    player_name: prop.player_name,
    prop_market: 'player_pass_tds',
    prop_line: prop.line,
    prop_selection: selection
  };

  await placeBet(betData);
}
```

### 4. Adding Props to Parlay

```typescript
async function addPropToParlay(prop: PlayerProp, selection: 'over' | 'under') {
  const leg = {
    bet_type: 'prop',
    selection: `${prop.player_name} ${selection} ${prop.line}`,
    odds: selection === 'over' ? prop.over : prop.under,
    game_id: eventId,
    home_team: gameData.home_team,
    away_team: gameData.away_team,
    sport: gameData.sport,
    commence_time: gameData.commence_time,
    // Player prop fields
    player_name: prop.player_name,
    prop_market: 'player_pass_tds',
    prop_line: prop.line,
    prop_selection: selection
  };

  // Add to parlay cart
  addLegToParlay(leg);
}
```

---

## YetAI Bet Integration

### Enabling Player Props in AI Bet Generation

To enable YetAI to generate player prop recommendations, you'll need to:

1. **Update YetAI Prompt** - Include player props in the analysis context
2. **Fetch Player Props** - Get available props for games being analyzed
3. **Generate Recommendations** - Have AI analyze player matchups and recommend props
4. **Link to Bet Placement** - Use `yetai_bet_id` field when placing prop bets

**Example YetAI Bet Structure:**
```json
{
  "id": "yetai-bet-123",
  "title": "Patrick Mahomes Over 1.5 Passing TDs",
  "description": "Mahomes has thrown 2+ TDs in 8 of last 10 games. Buffalo defense ranks 24th against QB TDs.",
  "bet_type": "prop",
  "confidence": 0.72,
  "player_name": "Patrick Mahomes",
  "prop_market": "player_pass_tds",
  "prop_line": 1.5,
  "prop_selection": "over",
  "odds": -150
}
```

---

## Testing

### Manual Testing Checklist

- [ ] Fetch player props for an NFL game
- [ ] Fetch player props for an NBA game
- [ ] Get available markets for each sport
- [ ] Place a single player prop bet
- [ ] Add player prop to a parlay
- [ ] Verify player prop bet appears in bet history
- [ ] Verify player prop stays "pending" (no auto-verification)

### Example Test Commands

```bash
# Get NFL player props
curl "https://api.yetai.app/api/player-props/americanfootball_nfl/EVENT_ID" \
  -H "Authorization: Bearer TOKEN"

# Get available NBA markets
curl "https://api.yetai.app/api/player-props/markets/basketball_nba"

# Place player prop bet
curl -X POST "https://api.yetai.app/api/bets/place" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "bet_type": "prop",
    "selection": "Patrick Mahomes Over 1.5 Passing TDs",
    "odds": -150,
    "amount": 50,
    "game_id": "EVENT_ID",
    "home_team": "Kansas City Chiefs",
    "away_team": "Buffalo Bills",
    "sport": "americanfootball_nfl",
    "commence_time": "2025-01-15T18:00:00Z",
    "player_name": "Patrick Mahomes",
    "prop_market": "player_pass_tds",
    "prop_line": 1.5,
    "prop_selection": "over"
  }'
```

---

## Limitations & Future Work

### Current Limitations

1. **FanDuel Only** - Limited to one bookmaker to conserve API quota
2. **Manual Verification** - Player props require manual verification (no auto-settlement)
3. **No Stats Integration** - Cannot verify props without external stats API
4. **Limited Markets** - Only markets available via The Odds API

### Future Enhancements

1. **Stats API Integration**
   - Integrate with sports stats API (SportsData.io, ESPN API, etc.)
   - Enable automatic verification of player prop bets
   - Real-time player stat tracking

2. **Multiple Bookmakers**
   - Add DraftKings, BetMGM, Caesars when quota allows
   - Compare odds across bookmakers
   - Best line finder

3. **Live Player Props**
   - In-game player props
   - Updated lines based on game flow
   - Cash out functionality

4. **Enhanced AI Analysis**
   - Player matchup analysis
   - Historical performance trends
   - Injury impact assessment
   - Weather conditions for outdoor sports

5. **Social Features**
   - Share player prop picks
   - Player prop leaderboards
   - Prop-specific analytics dashboard

---

## API Quota Management

### Current Usage

- Player props use the `/v4/sports/{sport}/events/{eventId}/odds` endpoint
- Limited to FanDuel bookmaker (reduces data transfer)
- Estimated: ~100 requests per day for player props

### Optimization Tips

1. **Cache Aggressively** - Cache prop data for 5-10 minutes
2. **Batch Requests** - Fetch multiple markets in one call
3. **Filter Markets** - Only fetch commonly used markets
4. **Monitor Usage** - Track API calls in CloudWatch

---

## Support & Troubleshooting

### Common Issues

**Issue:** "Sport not supported for player props"
**Solution:** Ensure sport key is one of: `americanfootball_nfl`, `basketball_nba`, `icehockey_nhl`, `baseball_mlb`

**Issue:** "Event not found"
**Solution:** Verify the event ID is correct and the event has player props available

**Issue:** "No player prop markets configured for sport"
**Solution:** Check that the sport is in the PLAYER_PROP_MARKETS dictionary

### Logging

Player props service logs are prefixed with market and player info:
```
INFO: Fetching player props for americanfootball_nfl event abc123, markets: player_pass_tds,player_pass_yds
INFO: Parlay abc123: Found 2 legs via parlay_legs JSON field
```

---

## References

- [The Odds API Documentation](https://the-odds-api.com/liveapi/guides/v4/)
- [Betting Markets Reference](https://the-odds-api.com/sports-odds-data/betting-markets.html)
- [SimpleUnifiedBet Model](YetAI/backend/app/models/simple_unified_bet_model.py)
- [PlayerPropsService](YetAI/backend/app/services/player_props_service.py)

---

---

## Frontend Components (Implemented)

### Components Created

1. **PlayerPropsCard** ([PlayerPropsCard.tsx](YetAI/frontend/src/components/PlayerPropsCard.tsx))
   - Displays player props grouped by market
   - Expandable/collapsible markets
   - Over/Under buttons with odds
   - Visual selection feedback
   - Auto-fetches props for an event

2. **PlayerPropBetModal** ([PlayerPropBetModal.tsx](YetAI/frontend/src/components/PlayerPropBetModal.tsx))
   - Dedicated modal for placing player prop bets
   - Shows player, prop type, line, and selection
   - Quick amount buttons ($10, $25, $50, $100, $250)
   - Potential win calculator
   - Bet confirmation flow
   - Success/error handling

3. **GameDetailsWithProps** ([GameDetailsWithProps.tsx](YetAI/frontend/src/components/GameDetailsWithProps.tsx))
   - Complete example showing game lines + player props
   - Tabbed interface (Game Lines / Player Props)
   - Integrates both traditional bets and player props
   - Ready-to-use template for game pages

### Usage Example

```tsx
import GameDetailsWithProps from '@/components/GameDetailsWithProps';

function GamePage() {
  const game = {
    id: 'abc123',
    sport: 'NFL',
    sport_key: 'americanfootball_nfl',
    home_team: 'Kansas City Chiefs',
    away_team: 'Buffalo Bills',
    commence_time: '2025-01-15T18:00:00Z',
    home_odds: -150,
    away_odds: +130,
    spread: -3.5,
    total: 52.5
  };

  return <GameDetailsWithProps game={game} />;
}
```

### Integration into Existing Components

To add player props to your existing game displays:

```tsx
// In your game card/details component
import PlayerPropsCard from '@/components/PlayerPropsCard';
import PlayerPropBetModal from '@/components/PlayerPropBetModal';

const [showPropModal, setShowPropModal] = useState(false);
const [selectedProp, setSelectedProp] = useState(null);

// Add props card
<PlayerPropsCard
  sportKey={game.sport_key}
  eventId={game.id}
  gameInfo={{
    home_team: game.home_team,
    away_team: game.away_team,
    commence_time: game.commence_time
  }}
  onPlaceBet={(prop) => {
    setSelectedProp(prop);
    setShowPropModal(true);
  }}
/>

// Add modal
<PlayerPropBetModal
  isOpen={showPropModal}
  onClose={() => setShowPropModal(false)}
  propBet={selectedProp}
/>
```

---

**Last Updated:** 2025-01-14
**Version:** 1.1
**Status:** ✅ Backend Complete, ✅ Frontend Complete
