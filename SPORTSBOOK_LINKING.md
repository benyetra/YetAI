# Sportsbook Deep Linking Integration

This document explains how to link users to sportsbooks with bet information pre-filled.

## Overview

We've implemented a sportsbook linking service that generates deep links to major sportsbooks. This allows users to click a button and be taken directly to the sportsbook's website with the game/bet information ready.

## Backend API

### Endpoint: `POST /api/v1/sportsbook-link`

Generates a deep link to a sportsbook.

**Request Body:**
```json
{
  "sportsbook": "fanduel",
  "sport_key": "americanfootball_nfl",
  "home_team": "Atlanta Falcons",
  "away_team": "Buffalo Bills",
  "bet_type": "h2h",
  "bet_selection": "Buffalo Bills"
}
```

**Response:**
```json
{
  "status": "success",
  "link": "https://sportsbook.fanduel.com/navigation/nfl?utm_source=yetai&utm_medium=referral&utm_campaign=bet_placement&partner=yetai",
  "sportsbook": "fanduel",
  "requires_manual_selection": true,
  "deep_link_supported": true,
  "message": "Link generated for fanduel. Deep linking supported - takes you to the game page."
}
```

**Parameters:**
- `sportsbook`: The sportsbook key (fanduel, draftkings, caesars, betmgm, betrivers)
- `sport_key`: Sport identifier (americanfootball_nfl, basketball_nba, baseball_mlb, icehockey_nhl)
- `home_team`: Home team name
- `away_team`: Away team name
- `bet_type`: Type of bet (h2h, spreads, totals)
- `bet_selection`: (Optional) The specific selection

## Frontend Usage

### Import the API function:

```typescript
import { sportsAPI } from '@/lib/api';
```

### Generate a sportsbook link:

```typescript
const handlePlaceBet = async (game) => {
  try {
    const response = await sportsAPI.getSportsbookLink({
      sportsbook: 'fanduel',
      sport_key: game.sport_key,
      home_team: game.home_team,
      away_team: game.away_team,
      bet_type: 'h2h',
      bet_selection: game.away_team // User's selection
    });

    if (response.status === 'success') {
      // Open sportsbook in new tab
      window.open(response.link, '_blank');
    }
  } catch (error) {
    console.error('Failed to generate sportsbook link:', error);
  }
};
```

## Supported Sportsbooks

### FanDuel ✅
- Deep linking: **Partially supported**
- Takes user to the sport/league page
- User needs to find the specific game
- Affiliate tracking: Supported via `partner` parameter

### DraftKings ✅
- Deep linking: **Partially supported**
- Takes user to the sport/league page with game lines
- User needs to find the specific game
- Affiliate tracking: Supported via `wpsrc` parameter

### Caesars ⚠️
- Deep linking: **Generic link only**
- Takes user to sportsbook homepage
- User must navigate to find game

### BetMGM ⚠️
- Deep linking: **Generic link only**
- Takes user to sportsbook homepage
- User must navigate to find game

### BetRivers ⚠️
- Deep linking: **Generic link only**
- Takes user to sportsbook homepage
- User must navigate to find game

## Affiliate Integration

### Setting Up Affiliate Codes

Edit `/app/services/sportsbook_links_service.py`:

```python
AFFILIATE_CODES = {
    Sportsbook.FANDUEL: "your_fanduel_affiliate_code",
    Sportsbook.DRAFTKINGS: "your_draftkings_affiliate_code",
    Sportsbook.CAESARS: "your_caesars_affiliate_code",
    Sportsbook.BETMGM: "your_betmgm_affiliate_code",
    Sportsbook.BETRIVERS: "your_betrivers_affiliate_code",
}
```

### Affiliate Programs

1. **FanDuel Affiliate Program**: https://fanduel.com/affiliates
2. **DraftKings Affiliate Program**: https://www.draftkings.com/affiliates
3. **Caesars Affiliate Program**: Contact Caesars directly
4. **BetMGM Affiliate Program**: https://www.betmgmaffiliates.com
5. **BetRivers Affiliate Program**: Contact BetRivers directly

## Future Enhancements

### 1. FanDuel Bet Slip API (Advanced)
FanDuel has a partner API that allows creating pre-filled bet slips:

```
POST https://api.fanduel.com/betslip/create
```

This requires:
- Partnership agreement with FanDuel
- API credentials
- Backend bet slip creation

### 2. Universal Bet Slip Format
Some sportsbooks support universal bet slip formats that can be shared via URL parameters.

### 3. Smart Link Routing
Detect user's location and preferred sportsbook to route them to the best option.

## Example Component

```typescript
import { sportsAPI } from '@/lib/api';
import { ExternalLink } from 'lucide-react';

function BetButton({ game, betType, selection }) {
  const handleBet = async () => {
    const response = await sportsAPI.getSportsbookLink({
      sportsbook: 'fanduel',
      sport_key: game.sport_key,
      home_team: game.home_team,
      away_team: game.away_team,
      bet_type: betType,
      bet_selection: selection
    });

    if (response.status === 'success') {
      window.open(response.link, '_blank');
    }
  };

  return (
    <button
      onClick={handleBet}
      className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
    >
      <ExternalLink className="w-4 h-4 inline mr-2" />
      Bet on FanDuel
    </button>
  );
}
```

## Tracking & Analytics

All generated links include UTM parameters for tracking:

- `utm_source=yetai`
- `utm_medium=referral`
- `utm_campaign=bet_placement`

You can track clicks and conversions using:
1. Google Analytics
2. Affiliate network dashboards
3. Custom analytics in your database

## Legal Considerations

⚠️ **Important**: Make sure to:
1. Comply with gambling advertising regulations in your jurisdiction
2. Include responsible gambling messaging
3. Verify user age and location before showing sportsbook links
4. Display appropriate disclaimers
5. Follow affiliate program terms and conditions

## Testing

Test the sportsbook linking functionality:

```bash
# Test FanDuel link generation
curl -X POST http://localhost:8000/api/v1/sportsbook-link \
  -H "Content-Type: application/json" \
  -d '{
    "sportsbook": "fanduel",
    "sport_key": "americanfootball_nfl",
    "home_team": "Atlanta Falcons",
    "away_team": "Buffalo Bills",
    "bet_type": "h2h"
  }'
```

Expected response includes a valid FanDuel URL with tracking parameters.
