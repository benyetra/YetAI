# Data Population Strategy for YetAI Sports Betting MVP

## Current State Analysis

### Database Coverage
- **Player Analytics**: Only 306 players (out of ~2000+ NFL players)
- **Seasons**: Only 2024 season data
- **Weeks**: Only weeks 8-12 of 2024 (5 weeks total)
- **Data Type**: Currently using mock/generated data

### Required Data Coverage
- **Players**: All NFL players (active and recent historical)
- **Seasons**: 2020-2024 (5 years of historical data)
- **Weeks**: All 18 weeks per season (regular season)
- **Metrics**: Real statistics, not generated data

## Available Data Sources

### 1. Free APIs (Limited but Good for MVP)

#### ESPN Fantasy API (Unofficial)
- **Pros**: Free, comprehensive player stats, fantasy projections
- **Cons**: Unofficial, may change without notice
- **Endpoint Examples**:
  ```
  https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
  https://fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/players
  ```

#### Pro Football Reference (Web Scraping)
- **Pros**: Most comprehensive historical data
- **Cons**: Requires scraping, rate limiting needed
- **URL Pattern**: `https://www.pro-football-reference.com/years/{year}/fantasy.htm`

#### nfl-data-py (Python Package)
- **Pros**: Easy to use, aggregates multiple sources
- **Installation**: `pip install nfl-data-py`
- **Features**: Play-by-play data, player stats, team stats

### 2. Premium APIs (For Production)

#### SportRadar API
- **Cost**: $1,000+/month
- **Features**: Real-time data, historical stats, official NFL data

#### MySportsFeeds
- **Cost**: $99-499/month
- **Features**: Historical data back to 2009, real-time updates

#### The Odds API
- **Cost**: Free tier available (500 requests/month)
- **Features**: Betting odds, game scores

## Implementation Plan

### Phase 1: Immediate MVP Solution (Using nfl-data-py)

```python
# Install required packages
pip install nfl-data-py pandas sqlalchemy psycopg2-binary

# Sample implementation
import nfl_data_py as nfl
import pandas as pd
from sqlalchemy import create_engine

# Fetch player stats for multiple seasons
years = [2020, 2021, 2022, 2023, 2024]
weekly_data = pd.DataFrame()

for year in years:
    # Get weekly player stats
    year_data = nfl.import_weekly_data([year])
    weekly_data = pd.concat([weekly_data, year_data])

# Get player IDs and info
player_ids = nfl.import_ids()
```

### Phase 2: ESPN API Integration

```python
import requests
import json

class ESPNDataFetcher:
    def __init__(self):
        self.base_url = "https://fantasy.espn.com/apis/v3/games/ffl"
        
    def get_players(self, season, week):
        url = f"{self.base_url}/seasons/{season}/segments/0/leagues/0"
        params = {
            "scoringPeriodId": week,
            "view": "kona_player_info"
        }
        
        headers = {
            'x-fantasy-filter': json.dumps({
                "players": {
                    "limit": 2000,
                    "sortPercOwned": {
                        "sortAsc": False,
                        "sortPriority": 1
                    }
                }
            })
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
```

### Phase 3: Database Population Script

```python
# This will be implemented in backend/scripts/populate_historical_data.py
```

## Data Fields to Populate

### player_analytics table
- `player_id`: Internal ID
- `week`: Game week (1-18)
- `season`: Year (2020-2024)
- `opponent`: Opposing team
- `total_snaps`: Total offensive snaps
- `snap_percentage`: Percentage of team snaps
- `targets`: Passing targets (WR/TE/RB)
- `target_share`: Share of team targets
- `receptions`: Completed catches
- `receiving_yards`: Yards from receptions
- `rushing_attempts`: Carry attempts (RB/QB)
- `rushing_yards`: Yards from rushing
- `touchdowns`: Total TDs
- `red_zone_targets`: Targets inside 20
- `red_zone_touches`: Total RZ opportunities
- `ppr_points`: Fantasy points (PPR)
- `air_yards`: Intended passing yards
- `yards_after_catch`: YAC
- `boom_rate`: % games > 20 pts
- `bust_rate`: % games < 5 pts

### player_trends table
- Weekly trend calculations
- Rolling averages
- Season-over-season comparisons

### player_projections table
- Future week projections
- Season projections
- Career projections

## Execution Steps

1. **Install Dependencies**
   ```bash
   cd backend
   pip install nfl-data-py pandas requests beautifulsoup4
   ```

2. **Create Population Scripts**
   - `populate_nfl_data.py` - Using nfl-data-py
   - `populate_espn_data.py` - ESPN API integration
   - `populate_analytics.py` - Calculate derived metrics

3. **Run Initial Population**
   ```bash
   python scripts/populate_nfl_data.py --years 2020-2024
   ```

4. **Set Up Scheduled Updates**
   - Weekly cron job for current season
   - Daily updates during season

## Data Quality Checks

1. Verify player ID mappings
2. Check for missing weeks/games
3. Validate statistical accuracy
4. Compare with known sources

## Next Steps

1. Choose primary data source
2. Implement fetching script
3. Map external IDs to internal IDs
4. Populate historical data
5. Set up automated updates