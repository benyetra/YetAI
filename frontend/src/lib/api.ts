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

    if (!response.ok) {
      throw new Error(`API Error: ${response.statusText}`);
    }

    return response.json();
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
      return await apiCircuitBreaker.execute(async () => {
        const result = await withRetry(() => this.get(endpoint, token));
        
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
      });
    } catch (error) {
      console.warn(`API call failed for ${endpoint}, using fallback:`, error);
      
      // Try to use cached data first
      if (useCache && typeof window !== 'undefined') {
        const cacheKey = `api_cache_${endpoint.replace(/[^a-zA-Z0-9]/g, '_')}`;
        const cached = localStorage.getItem(cacheKey);
        
        if (cached) {
          try {
            const { data, timestamp, ttl } = JSON.parse(cached);
            if (Date.now() - timestamp < ttl) {
              console.info(`Using cached data for ${endpoint}`);
              return data;
            }
          } catch (cacheError) {
            console.warn('Failed to parse cached data:', cacheError);
          }
        }
      }
      
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

  // Get popular sports odds
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

    // Extract spread
    const spreadMarket = bookmaker.markets?.find((m: any) => m.key === 'spreads');
    if (spreadMarket && spreadMarket.outcomes) {
      const homeOutcome = spreadMarket.outcomes.find((o: any) => o.name === game.home_team);
      if (homeOutcome && homeOutcome.point) {
        spread = parseFloat(homeOutcome.point);
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

    return { home_odds: homeOdds, away_odds: awayOdds, spread, total };
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

// Test endpoints (keep for compatibility)
export const testAPI = {
  health: () => api.get('/health'),
  odds: () => api.get('/test/odds'),
  fantasy: () => api.get('/test/fantasy'),
};