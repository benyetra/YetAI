import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// API Client for BetModal and other components
export const apiClient = {
  baseURL: API_BASE_URL,

  async get(endpoint: string, token?: string) {
    const headers: any = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${this.baseURL}${endpoint}`, {
      method: 'GET',
      headers
    });

    // Parse JSON response regardless of status
    const jsonResponse = await response.json();

    if (!response.ok) {
      // Return the error response for proper handling
      return {
        status: 'error',
        detail: jsonResponse.detail || response.statusText,
        ...jsonResponse
      };
    }

    return {
      status: 'success',
      ...jsonResponse
    };
  },

  async post(endpoint: string, data: any, token?: string) {
    const headers: any = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${this.baseURL}${endpoint}`, {
      method: 'POST',
      headers,
      body: JSON.stringify(data)
    });

    // Parse JSON response regardless of status
    const jsonResponse = await response.json();

    if (!response.ok) {
      // Return the error response for proper handling
      return {
        status: 'error',
        detail: jsonResponse.detail || response.statusText,
        ...jsonResponse
      };
    }

    return {
      status: 'success',
      ...jsonResponse
    };
  },

  async put(endpoint: string, data: any, token?: string) {
    const headers: any = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${this.baseURL}${endpoint}`, {
      method: 'PUT',
      headers,
      body: JSON.stringify(data)
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.statusText}`);
    }

    return response.json();
  },

  async delete(endpoint: string, token?: string) {
    const headers: any = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${this.baseURL}${endpoint}`, {
      method: 'DELETE',
      headers
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.statusText}`);
    }

    return response.json();
  }
};

// Enhanced error handling with retries and fallbacks
const withRetry = async <T>(
  operation: () => Promise<T>,
  maxRetries: number = 3,
  delay: number = 1000
): Promise<T> => {
  let lastError: Error;
  
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return await operation();
    } catch (error) {
      lastError = error as Error;
      
      if (attempt === maxRetries) {
        throw lastError;
      }
      
      // Wait before retrying with exponential backoff
      await new Promise(resolve => setTimeout(resolve, delay * Math.pow(2, attempt - 1)));
    }
  }
  
  throw lastError!;
};

// Circuit breaker pattern
class CircuitBreaker {
  private failures: number = 0;
  private lastFailTime: number = 0;
  private state: 'closed' | 'open' | 'half-open' = 'closed';
  
  constructor(
    private threshold: number = 5,
    private timeout: number = 60000 // 1 minute
  ) {}
  
  async execute<T>(operation: () => Promise<T>): Promise<T> {
    if (this.state === 'open') {
      if (Date.now() - this.lastFailTime < this.timeout) {
        throw new Error('Circuit breaker is open');
      }
      this.state = 'half-open';
    }
    
    try {
      const result = await operation();
      this.onSuccess();
      return result;
    } catch (error) {
      this.onFailure();
      throw error;
    }
  }
  
  private onSuccess() {
    this.failures = 0;
    this.state = 'closed';
  }
  
  private onFailure() {
    this.failures++;
    this.lastFailTime = Date.now();
    
    if (this.failures >= this.threshold) {
      this.state = 'open';
    }
  }
  
  getState() {
    return {
      state: this.state,
      failures: this.failures,
      lastFailTime: this.lastFailTime
    };
  }
}

// Global circuit breaker for API calls
const apiCircuitBreaker = new CircuitBreaker(5, 60000);

// Enhanced API client with error handling
export const enhancedApiClient = {
  ...apiClient,
  
  async getWithFallback<T>(
    endpoint: string,
    fallbackData: T,
    token?: string,
    useCache: boolean = true
  ): Promise<T> {
    try {
      const result = await apiCircuitBreaker.execute(async () => {
        const response = await withRetry(() => this.get(endpoint, token));

        // Check if the response indicates an error
        if (response && response.status === 'error') {
          throw new Error(response.detail || 'API request failed');
        }

        return response;
      });

      // Cache successful results
      if (useCache && typeof window !== 'undefined') {
        const cacheKey = `api_cache_${endpoint.replace(/[^a-zA-Z0-9]/g, '_')}`;
        localStorage.setItem(cacheKey, JSON.stringify({
          data: result,
          timestamp: Date.now(),
          ttl: 300000 // 5 minutes
        }));
      }

      return result;
    } catch (error) {
      console.warn(`API call failed for ${endpoint}, using fallback:`, error);

      // Try to use cached data first
      if (useCache && typeof window !== 'undefined') {
        const cacheKey = `api_cache_${endpoint.replace(/[^a-zA-Z0-9]/g, '_')}`;
        const cached = localStorage.getItem(cacheKey);

        if (cached) {
          try {
            const { data, timestamp, ttl } = JSON.parse(cached);
            if (Date.now() - timestamp < ttl && data && data.status === 'success') {
              console.info(`Using cached data for ${endpoint}`);
              return data;
            } else {
              console.warn(`Cached data for ${endpoint} is invalid or expired, using fallback`);
              // Clear invalid cache
              localStorage.removeItem(cacheKey);
            }
          } catch (cacheError) {
            console.warn('Failed to parse cached data:', cacheError);
            // Clear corrupted cache
            localStorage.removeItem(cacheKey);
          }
        }
      }

      console.info(`Using fallback data for ${endpoint}:`, fallbackData);
      return fallbackData;
    }
  }
};

// Sports Data API
export const sportsAPI = {
  // Get available sports
  getSports: async (useCache: boolean = true) => {
    const fallbackData = {
      status: 'success',
      count: 4,
      sports: [
        { key: 'americanfootball_nfl', title: 'NFL', category: 'Football', active: true },
        { key: 'basketball_nba', title: 'NBA', category: 'Basketball', active: true },
        { key: 'baseball_mlb', title: 'MLB', category: 'Baseball', active: true },
        { key: 'icehockey_nhl', title: 'NHL', category: 'Hockey', active: true }
      ],
      cached: false,
      last_updated: new Date().toISOString()
    };
    
    return enhancedApiClient.getWithFallback('/api/sports', fallbackData, undefined, useCache);
  },

  // Get live odds for a sport
  getOdds: async (sportKey: string, options: {
    regions?: string;
    markets?: string;
    oddsFormat?: string;
    bookmakers?: string;
    useCache?: boolean;
  } = {}) => {
    const {
      regions = 'us',
      markets = 'h2h,spreads,totals',
      oddsFormat = 'american',
      bookmakers,
      useCache = true
    } = options;
    
    const params = new URLSearchParams({
      regions,
      markets,
      odds_format: oddsFormat,
      ...(bookmakers && { bookmakers })
    });
    
    const fallbackData = {
      status: 'success',
      sport: sportKey,
      count: 0,
      games: [],
      cached: false,
      last_updated: new Date().toISOString(),
      message: 'No live games available'
    };
    
    return enhancedApiClient.getWithFallback(
      `/api/odds/${sportKey}?${params}`, 
      fallbackData, 
      undefined, 
      useCache
    );
  },

  // Get popular sports odds (legacy - uses odds-based popularity)
  getPopularOdds: async (useCache: boolean = true) => {
    const fallbackData = {
      status: 'success',
      count: 0,
      games: [],
      sports_included: ['NFL', 'NBA', 'MLB', 'NHL'],
      cached: false,
      last_updated: new Date().toISOString()
    };

    return enhancedApiClient.getWithFallback('/api/odds/popular', fallbackData, undefined, useCache);
  },

  // Get popular games based on national TV broadcast coverage (ESPN API)
  getPopularGames: async (sport?: string, useCache: boolean = true) => {
    const endpoint = sport ? `/api/popular-games/${sport}` : '/api/popular-games';
    const fallbackData = {
      status: 'success',
      popular_games: {
        nfl: [],
        nba: [],
        mlb: [],
        nhl: []
      },
      total_count: 0,
      message: 'No popular games available'
    };

    return enhancedApiClient.getWithFallback(endpoint, fallbackData, undefined, useCache);
  },

  // Generate sportsbook deep link
  getSportsbookLink: async (data: {
    sportsbook: string;
    sport_key: string;
    home_team: string;
    away_team: string;
    bet_type?: string;
    bet_selection?: string;
  }) => {
    try {
      const response = await apiClient.post('/api/v1/sportsbook-link', data);
      return response;
    } catch (error) {
      console.error('Error generating sportsbook link:', error);
      throw error;
    }
  },

  // Get live games
  getLiveGames: async (useCache: boolean = true) => {
    const fallbackData = {
      status: 'success',
      count: 0,
      games: [],
      description: 'No live games currently available',
      cached: false,
      last_updated: new Date().toISOString()
    };
    
    return enhancedApiClient.getWithFallback('/api/odds/live', fallbackData, undefined, useCache);
  },

  // Get scores for a sport
  getScores: async (sportKey: string, daysFrom: number = 3, useCache: boolean = true) => {
    const fallbackData = {
      status: 'success',
      sport: sportKey,
      days_from: daysFrom,
      count: 0,
      scores: [],
      cached: false,
      last_updated: new Date().toISOString()
    };
    
    return enhancedApiClient.getWithFallback(
      `/api/scores/${sportKey}?days_from=${daysFrom}`, 
      fallbackData, 
      undefined, 
      useCache
    );
  },

  // Get odds for specific event
  getEventOdds: async (sportKey: string, eventId: string, options: {
    regions?: string;
    markets?: string;
    oddsFormat?: string;
    bookmakers?: string;
    useCache?: boolean;
  } = {}) => {
    const {
      regions = 'us',
      markets = 'h2h,spreads,totals',
      oddsFormat = 'american',
      bookmakers,
      useCache = true
    } = options;
    
    const params = new URLSearchParams({
      regions,
      markets,
      odds_format: oddsFormat,
      ...(bookmakers && { bookmakers })
    });
    
    const fallbackData = {
      status: 'error',
      message: 'Event not found or unavailable',
      event_id: eventId,
      game: null
    };
    
    return enhancedApiClient.getWithFallback(
      `/api/odds/${sportKey}/event/${eventId}?${params}`, 
      fallbackData, 
      undefined, 
      useCache
    );
  },

  // Get user performance analytics
  getUserPerformance: async (days: number = 30, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    
    const fallbackData = {
      status: 'success',
      period_days: days,
      overview: {
        total_bets: 0,
        total_wagered: 0,
        total_profit: 0,
        win_rate: 0,
        roi: 0,
        won_bets: 0,
        lost_bets: 0,
        pending_bets: 0
      },
      sport_breakdown: [],
      bet_type_breakdown: [],
      performance_trend: {
        recent_period: { win_rate: 0, profit: 0, total_bets: 0 },
        previous_period: { win_rate: 0, profit: 0, total_bets: 0 },
        win_rate_change: 0,
        profit_change: 0,
        trend_direction: 'stable'
      },
      insights: []
    };

    try {
      const response = await enhancedApiClient.get(`/api/user/performance?days=${days}`, authToken);
      return response;
    } catch (error) {
      console.warn('Failed to fetch user performance data:', error);
      return fallbackData;
    }
  },

  // Get player props for an event
  getPlayerProps: async (sportKey: string, eventId: string, markets?: string[], token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);

    const params = new URLSearchParams();
    if (markets && markets.length > 0) {
      params.append('markets', markets.join(','));
    }

    const fallbackData = {
      status: 'error',
      data: {
        event_id: eventId,
        sport_key: sportKey,
        markets: {}
      },
      message: 'Player props not available'
    };

    try {
      const endpoint = `/api/player-props/${sportKey}/${eventId}${params.toString() ? '?' + params.toString() : ''}`;
      const response = await enhancedApiClient.get(endpoint, authToken);
      return response;
    } catch (error) {
      console.warn('Failed to fetch player props:', error);
      return fallbackData;
    }
  },

  // Get available player prop markets for a sport
  getPlayerPropMarkets: async (sportKey: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);

    const fallbackData = {
      status: 'error',
      sport: sportKey,
      markets: [],
      message: 'Markets not available'
    };

    try {
      const response = await enhancedApiClient.get(`/api/player-props/markets/${sportKey}`, authToken);
      return response;
    } catch (error) {
      console.warn('Failed to fetch player prop markets:', error);
      return fallbackData;
    }
  }
};

// Cache management
export const cacheAPI = {
  // Get cache status
  getCacheStatus: async () => {
    try {
      return await apiClient.get('/api/cache/status');
    } catch (error) {
      return {
        status: 'error',
        message: 'Cache status unavailable',
        cache_stats: {
          redis_available: false,
          memory_cache: { cache_type: 'unknown' }
        }
      };
    }
  },

  // Clear cache
  clearCache: async (token?: string) => {
    return apiClient.post('/api/cache/clear', {}, token);
  },

  // Clear sport-specific cache
  clearSportCache: async (sportKey: string, token?: string) => {
    return apiClient.post(`/api/cache/clear/${sportKey}`, {}, token);
  }
};

// Scheduler management
export const schedulerAPI = {
  // Get scheduler status
  getStatus: async () => {
    try {
      return await apiClient.get('/api/scheduler/status');
    } catch (error) {
      return {
        status: 'error',
        message: 'Scheduler status unavailable',
        scheduler_running: false,
        task_count: 0,
        tasks: {}
      };
    }
  },

  // Run task manually
  runTask: async (taskName: string, token?: string) => {
    return apiClient.post(`/api/scheduler/task/${taskName}/run`, {}, token);
  },

  // Enable/disable tasks
  enableTask: async (taskName: string, token?: string) => {
    return apiClient.post(`/api/scheduler/task/${taskName}/enable`, {}, token);
  },

  disableTask: async (taskName: string, token?: string) => {
    return apiClient.post(`/api/scheduler/task/${taskName}/disable`, {}, token);
  }
};

// Circuit breaker utilities
export const circuitBreakerAPI = {
  getState: () => apiCircuitBreaker.getState(),
  
  // Clear local cache
  clearLocalCache: () => {
    if (typeof window !== 'undefined') {
      const keys = Object.keys(localStorage).filter(key => key.startsWith('api_cache_'));
      keys.forEach(key => localStorage.removeItem(key));
    }
  }
};

// Odds data utilities
export const oddsUtils = {
  // Extract simplified odds from complex bookmaker data for BetModal compatibility
  extractSimpleOdds: (game: any) => {
    if (!game.bookmakers || game.bookmakers.length === 0) {
      return {
        home_odds: -110,
        away_odds: -110,
        spread: 0,
        total: 0
      };
    }

    // Use first available bookmaker
    const bookmaker = game.bookmakers[0];
    let homeOdds = -110;
    let awayOdds = -110;
    let spread = 0;
    let total = 0;

    // Extract moneyline odds
    const h2hMarket = bookmaker.markets?.find((m: any) => m.key === 'h2h');
    if (h2hMarket && h2hMarket.outcomes) {
      const homeOutcome = h2hMarket.outcomes.find((o: any) => o.name === game.home_team);
      const awayOutcome = h2hMarket.outcomes.find((o: any) => o.name === game.away_team);
      
      if (homeOutcome) homeOdds = homeOutcome.price;
      if (awayOutcome) awayOdds = awayOutcome.price;
    }

    // Extract spread (both home and away)
    let homeSpread = 0;
    let awaySpread = 0;
    const spreadMarket = bookmaker.markets?.find((m: any) => m.key === 'spreads');
    if (spreadMarket && spreadMarket.outcomes) {
      const homeOutcome = spreadMarket.outcomes.find((o: any) => o.name === game.home_team);
      const awayOutcome = spreadMarket.outcomes.find((o: any) => o.name === game.away_team);
      if (homeOutcome && homeOutcome.point) {
        homeSpread = parseFloat(homeOutcome.point);
      }
      if (awayOutcome && awayOutcome.point) {
        awaySpread = parseFloat(awayOutcome.point);
      }
    }

    // Extract total
    const totalMarket = bookmaker.markets?.find((m: any) => m.key === 'totals');
    if (totalMarket && totalMarket.outcomes) {
      const overOutcome = totalMarket.outcomes.find((o: any) => o.name === 'Over');
      if (overOutcome && overOutcome.point) {
        total = parseFloat(overOutcome.point);
      }
    }

    return { home_odds: homeOdds, away_odds: awayOdds, spread, home_spread: homeSpread, away_spread: awaySpread, total };
  },

  // Convert complex game to simple format for BetModal
  toSimpleGame: (game: any) => {
    const extractedOdds = oddsUtils.extractSimpleOdds(game);
    
    return {
      id: game.id,
      sport: game.sport_key || game.sport,
      home_team: game.home_team,
      away_team: game.away_team,
      commence_time: game.commence_time,
      ...extractedOdds
    };
  }
};

// Fantasy Sports API
export const fantasyAPI = {
  // Connect a fantasy platform account
  connectAccount: async (platform: string, credentials: any, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    return apiClient.post('/api/fantasy/connect', { platform, credentials }, authToken);
  },

  // Get connected fantasy accounts
  getAccounts: async (token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      return await apiClient.get('/api/fantasy/accounts', authToken);
    } catch (error) {
      return { status: 'error', accounts: [], message: 'Failed to fetch fantasy accounts' };
    }
  },

  // Get fantasy leagues
  getLeagues: async (token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      return await apiClient.get('/api/fantasy/leagues', authToken);
    } catch (error) {
      return { status: 'error', leagues: [], message: 'Failed to fetch fantasy leagues' };
    }
  },

  // Sync a specific league
  syncLeague: async (leagueId: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    return apiClient.post(`/api/fantasy/sync-league/${leagueId}`, {}, authToken);
  },

  // Get roster for a specific league
  getRoster: async (leagueId: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      return await apiClient.get(`/api/fantasy/roster/${leagueId}`, authToken);
    } catch (error) {
      return { status: 'error', roster: [], message: 'Failed to fetch roster' };
    }
  },

  // Disconnect fantasy account
  disconnectAccount: async (accountId: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    return apiClient.delete(`/api/fantasy/disconnect/${accountId}`, authToken);
  },

  // Disconnect and erase a specific league
  disconnectLeague: async (leagueId: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    return apiClient.delete(`/api/fantasy/leagues/${leagueId}`, authToken);
  },

  // Get start/sit recommendations
  getStartSitRecommendations: async (week: number = 1, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      return await apiClient.get(`/api/fantasy/recommendations/start-sit/${week}`, authToken);
    } catch (error) {
      return { status: 'error', recommendations: [], message: 'Failed to fetch start/sit recommendations' };
    }
  },

  // Get waiver wire recommendations
  getWaiverWireRecommendations: async (week: number = 1, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      return await apiClient.get(`/api/fantasy/recommendations/waiver-wire/${week}`, authToken);
    } catch (error) {
      return { status: 'error', recommendations: [], message: 'Failed to fetch waiver wire recommendations' };
    }
  },

  // Test Sleeper integration
  testSleeper: async (username: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      return await apiClient.get(`/api/fantasy/test/sleeper/${username}`, authToken);
    } catch (error) {
      return { status: 'error', message: 'Failed to test Sleeper integration' };
    }
  },

  // Get trending players
  getTrendingPlayers: async (token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      return await apiClient.get('/api/fantasy/test/sleeper-trending', authToken);
    } catch (error) {
      return { status: 'error', trending: [], message: 'Failed to fetch trending players' };
    }
  },

  // Get league standings
  getLeagueStandings: async (leagueId: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      const response = await apiClient.get(`/api/v1/fantasy/standings/${leagueId}`, authToken);
      
      // Handle different response formats
      if (response.success !== undefined) {
        // New format: { success: true, standings: [...] }
        return {
          status: response.success ? 'success' : 'error',
          standings: response.standings || [],
          league_name: response.league_name,
          season: response.season
        };
      } else {
        // Old format: { status: 'success', standings: [...] }
        return response;
      }
    } catch (error) {
      return { status: 'error', standings: [], message: 'Failed to fetch league standings' };
    }
  },

  // Get league matchups for a specific week
  getLeagueMatchups: async (leagueId: string, week: number, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      return await apiClient.get(`/api/fantasy/matchups/${leagueId}/${week}`, authToken);
    } catch (error) {
      return { status: 'error', matchups: [], message: 'Failed to fetch league matchups' };
    }
  },

  // Get detailed league rules and settings
  getLeagueRules: async (leagueId: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    
    // Try the legacy fantasy endpoint first (since most leagues are still using the old system)
    try {
      const fantasyResponse = await apiClient.get(`/api/fantasy/leagues/${leagueId}/rules`, authToken);
      if (fantasyResponse.status === 'success') {
        return fantasyResponse;
      }
    } catch (fantasyError) {
      console.log('Fantasy endpoint failed, trying Sleeper endpoint:', fantasyError);
    }
    
    // Fallback to the new Sleeper endpoint
    try {
      const sleeperResponse = await apiClient.get(`/api/sleeper/leagues/${leagueId}/rules`, authToken);
      if (sleeperResponse.status === 'success') {
        return sleeperResponse;
      }
    } catch (sleeperError) {
      console.log('Sleeper endpoint also failed:', sleeperError);
    }
    
    return { status: 'error', rules: null, message: 'Failed to fetch league rules' };
  },

  // Advanced player search
  searchPlayers: async (filters: {
    query?: string;
    position?: string;
    team?: string;
    age_min?: number;
    age_max?: number;
    experience_min?: number;
    experience_max?: number;
    availability?: string;
    injury_status?: string;
    trending?: string;
    league_id?: string;
    limit?: number;
    offset?: number;
  }, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          // Map 'query' to 'q' for backend compatibility
          const paramKey = key === 'query' ? 'q' : key;
          params.append(paramKey, value.toString());
        }
      });
      return await apiClient.get(`/api/fantasy/players/search?${params.toString()}`, authToken);
    } catch (error) {
      return { status: 'error', players: [], message: 'Failed to search players' };
    }
  },

  // Compare players
  comparePlayers: async (playerIds: string[], leagueId?: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      const payload = {
        player_ids: playerIds,
        league_id: leagueId
      };
      return await apiClient.post('/api/fantasy/players/compare', payload, authToken);
    } catch (error) {
      return { status: 'error', comparison: null, message: 'Failed to compare players' };
    }
  },

  // Player Analytics
  getPlayerAnalytics: async (playerId: number, weeks?: string, season: number = 2025, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      const params = new URLSearchParams();
      if (weeks) params.append('weeks', weeks);
      params.append('season', season.toString());
      
      return await apiClient.get(`/api/fantasy/analytics/${playerId}?${params.toString()}`, authToken);
    } catch (error) {
      return { status: 'error', analytics: [], message: 'Failed to get player analytics' };
    }
  },

  getPlayerTrends: async (playerId: number, weeks?: string, season: number = 2025, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      const params = new URLSearchParams();
      if (weeks) {
        params.append('weeks', weeks);
      }
      params.append('season', season.toString());
      
      return await apiClient.get(`/api/fantasy/analytics/${playerId}/trends?${params.toString()}`, authToken);
    } catch (error) {
      return { status: 'error', trends: {}, message: 'Failed to get player trends' };
    }
  },

  getPlayerEfficiency: async (playerId: number, weeks?: string, season: number = 2025, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      const params = new URLSearchParams();
      if (weeks) {
        params.append('weeks', weeks);
      }
      params.append('season', season.toString());
      
      return await apiClient.get(`/api/fantasy/analytics/${playerId}/efficiency?${params.toString()}`, authToken);
    } catch (error) {
      return { status: 'error', efficiency_metrics: {}, message: 'Failed to get player efficiency' };
    }
  },

  getBreakoutCandidates: async (position: string, season: number = 2025, minWeeks: number = 3, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      const params = new URLSearchParams();
      params.append('season', season.toString());
      params.append('min_weeks', minWeeks.toString());
      
      return await apiClient.get(`/api/fantasy/analytics/breakout-candidates/${position}?${params.toString()}`, authToken);
    } catch (error) {
      return { status: 'error', candidates: [], message: 'Failed to get breakout candidates' };
    }
  },

  getMatchupAnalytics: async (playerId: number, opponent: string, season: number = 2025, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      const params = new URLSearchParams();
      params.append('season', season.toString());
      
      return await apiClient.get(`/api/fantasy/analytics/${playerId}/matchup/${opponent}?${params.toString()}`, authToken);
    } catch (error) {
      return { status: 'error', matchup_analysis: {}, message: 'Failed to get matchup analytics' };
    }
  }
};

// Sleeper-specific API endpoints
export const sleeperAPI = {
  // Connect Sleeper account
  connectAccount: async (sleeperUsername: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    return apiClient.post('/api/sleeper/connect', { sleeper_username: sleeperUsername }, authToken);
  },

  // Sync all leagues
  syncLeagues: async (token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    return apiClient.post('/api/sleeper/sync/leagues', {}, authToken);
  },

  // Sync all rosters
  syncRosters: async (token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    return apiClient.post('/api/sleeper/sync/rosters', {}, authToken);
  },

  // Sync NFL players (admin only)
  syncPlayers: async (token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    return apiClient.post('/api/sleeper/sync/players', {}, authToken);
  },

  // Full sync workflow
  fullSync: async (sleeperUsername: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    return apiClient.post('/api/sleeper/sync/full', { sleeper_username: sleeperUsername }, authToken);
  },

  // Get sync status
  getStatus: async (token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      return await apiClient.get('/api/sleeper/status', authToken);
    } catch (error) {
      return { status: 'error', message: 'Failed to get Sleeper sync status' };
    }
  },

  // Get Sleeper leagues
  getLeagues: async (token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      return await apiClient.get('/api/sleeper/leagues', authToken);
    } catch (error) {
      return { status: 'error', leagues: [], message: 'Failed to fetch Sleeper leagues' };
    }
  },

  // Get league rosters
  getLeagueRosters: async (leagueId: string, token?: string) => {
    const authToken = token || (typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null);
    try {
      return await apiClient.get(`/api/sleeper/leagues/${leagueId}/rosters`, authToken);
    } catch (error) {
      return { status: 'error', rosters: [], message: 'Failed to fetch league rosters' };
    }
  }
};

// Test endpoints (keep for compatibility)
export const testAPI = {
  health: () => api.get('/health'),
  odds: () => api.get('/test/odds'),
  fantasy: () => api.get('/test/fantasy'),
};