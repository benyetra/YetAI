'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { fantasyAPI } from '@/lib/api';
import { 
  Trophy, 
  Users, 
  TrendingUp, 
  Star, 
  Plus, 
  RefreshCw, 
  AlertCircle, 
  CheckCircle, 
  ExternalLink,
  Trash2,
  Target,
  TrendingDown,
  Settings,
  Search,
  Filter,
  BarChart3,
  Eye,
  X
} from 'lucide-react';

// Interfaces
interface FantasyAccount {
  id: string;
  platform: string;
  username: string;
  user_id: string;
  is_active: boolean;
  last_sync: string;
  created_at: string;
}

interface FantasyLeague {
  id: string;
  league_id: string;
  name: string;
  platform: string;
  season: string;
  total_teams: number;
  settings: any;
  last_sync: string;
  is_active: boolean;
  user_team?: {
    id: string;
    name: string;
    wins: number;
    losses: number;
    points_for: number;
    waiver_position: number;
  };
}

interface Player {
  player_id: string;
  name: string;
  position: string;
  team: string;
  age: number;
  status: string;
}

interface StandingsTeam {
  team_id: number;
  platform_team_id: string;
  name: string;
  owner_name: string;
  is_user_team: boolean;
  wins: number;
  losses: number;
  ties: number;
  win_percentage: number;
  points_for: number;
  points_against: number;
  points_per_game: number;
  points_against_per_game: number;
  point_differential: number;
  waiver_position: number;
  rank: number;
}

interface Matchup {
  matchup_id: string;
  week: number;
  team1: {
    id: number;
    name: string;
    owner_name: string;
    is_user_team: boolean;
    score: number;
    starters: any[];
  };
  team2: {
    id: number;
    name: string;
    owner_name: string;
    is_user_team: boolean;
    score: number;
    starters: any[];
  };
  status: string;
  user_involved: boolean;
}

interface WaiverRecommendation {
  league_id: number;
  league_name: string;
  player_id: string;
  player_name: string;
  position: string;
  team: string;
  priority_score: number;
  trend_count: number;
  reason: string;
  suggested_fab_percentage: number;
  age?: number;
  experience?: number;
  fantasy_positions: string[];
}

interface StartSitRecommendation {
  league_id: number;
  league_name: string;
  player_id: string;
  player_name: string;
  position: string;
  team: string;
  recommendation: "START" | "SIT";
  projected_points: number;
  confidence: number;
  reasoning: string;
  rank_in_position: number;
  total_in_position: number;
  week: number;
  is_questionable: boolean;
  opponent?: string;
}

interface LeagueRules {
  league_id: string;
  league_name: string;
  platform: string;
  season: number;
  league_type: string;
  team_count: number;
  roster_settings: {
    total_spots: number;
    starting_spots: number;
    bench_spots: number;
    positions: Record<string, number>;
    position_requirements: string[];
  };
  scoring_settings: {
    type: string;
    passing: {
      touchdowns: number;
      yards_per_point: number;
      interceptions: number;
    };
    rushing: {
      touchdowns: number;
      yards_per_point: number;
      fumbles: number;
    };
    receiving: {
      touchdowns: number;
      yards_per_point: number;
      receptions: number;
    };
    special_scoring: string[];
    raw_settings: Record<string, any>;
  };
  features: {
    trades_enabled: boolean;
    waivers_enabled: boolean;
    playoffs: {
      teams: number;
      weeks: number;
    };
  };
  ai_context: {
    prioritize_volume: boolean;
    rb_premium: boolean;
    flex_strategy: boolean;
    superflex: boolean;
    position_scarcity: Record<string, number>;
  };
}

interface Player {
  player_id: string;
  name: string;
  position: string;
  team: string;
  age?: number;
  experience?: number;
  injury_status: string;
  trending_status: string;
  availability: string;
  fantasy_positions: string[];
  height?: string;
  weight?: number;
  college?: string;
  depth_chart_order?: number;
  search_rank: number;
  league_metrics: {
    scoring_type?: string;
    position_value?: string;
    league_boost?: string;
  };
  metadata: {
    rotowire_id?: string;
    sportradar_id?: string;
    yahoo_id?: string;
  };
}

interface SearchFilters {
  query: string;
  position: string;
  team: string;
  age_min: number | null;
  age_max: number | null;
  experience_min: number | null;
  experience_max: number | null;
  availability: string;
  injury_status: string;
  trending: string;
  league_id: string;
}

export default function FantasyPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();

  // State management
  const [accounts, setAccounts] = useState<FantasyAccount[]>([]);
  const [leagues, setLeagues] = useState<FantasyLeague[]>([]);
  const [trendingPlayers, setTrendingPlayers] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [connectPlatform, setConnectPlatform] = useState('sleeper');
  const [username, setUsername] = useState('');
  const [isConnecting, setIsConnecting] = useState(false);
  const [isSyncing, setIsSyncing] = useState<string | null>(null);
  const [selectedLeague, setSelectedLeague] = useState<string | null>(null);
  const [roster, setRoster] = useState<Player[]>([]);
  const [isLoadingRoster, setIsLoadingRoster] = useState(false);
  const [rosterTeamName, setRosterTeamName] = useState('');
  const [standings, setStandings] = useState<StandingsTeam[]>([]);
  const [isLoadingStandings, setIsLoadingStandings] = useState(false);
  const [showStandings, setShowStandings] = useState(false);
  const [matchups, setMatchups] = useState<Matchup[]>([]);
  const [isLoadingMatchups, setIsLoadingMatchups] = useState(false);
  const [showMatchups, setShowMatchups] = useState(false);
  const [selectedWeek, setSelectedWeek] = useState(1);
  const [waiverRecommendations, setWaiverRecommendations] = useState<WaiverRecommendation[]>([]);
  const [isLoadingWaiver, setIsLoadingWaiver] = useState(false);
  const [showWaiverRecommendations, setShowWaiverRecommendations] = useState(false);
  const [startSitRecommendations, setStartSitRecommendations] = useState<StartSitRecommendation[]>([]);
  const [isLoadingStartSit, setIsLoadingStartSit] = useState(false);
  const [showStartSitRecommendations, setShowStartSitRecommendations] = useState(false);
  const [leagueRules, setLeagueRules] = useState<LeagueRules | null>(null);
  const [isLoadingRules, setIsLoadingRules] = useState(false);
  const [showLeagueRules, setShowLeagueRules] = useState(false);
  
  // Player Search States
  const [showPlayerSearch, setShowPlayerSearch] = useState(false);
  const [searchResults, setSearchResults] = useState<Player[]>([]);
  const [isLoadingSearch, setIsLoadingSearch] = useState(false);
  const [searchFilters, setSearchFilters] = useState<SearchFilters>({
    query: '',
    position: '',
    team: '',
    age_min: null,
    age_max: null,
    experience_min: null,
    experience_max: null,
    availability: '',
    injury_status: '',
    trending: '',
    league_id: ''
  });
  const [showFilters, setShowFilters] = useState(false);
  const [selectedPlayers, setSelectedPlayers] = useState<string[]>([]);
  const [showComparison, setShowComparison] = useState(false);
  const [comparisonData, setComparisonData] = useState<any>(null);
  const lastActionRef = useRef<{playerId: string, timestamp: number} | null>(null);

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (isAuthenticated) {
      loadFantasyData();
    }
  }, [isAuthenticated]);

  const loadFantasyData = async () => {
    setIsLoading(true);
    setError(null);
    
    try {
      const [accountsResponse, leaguesResponse, trendingResponse] = await Promise.all([
        fantasyAPI.getAccounts(),
        fantasyAPI.getLeagues(),
        fantasyAPI.getTrendingPlayers()
      ]);

      if (accountsResponse.status === 'success') {
        setAccounts(accountsResponse.accounts || []);
      }

      if (leaguesResponse.status === 'success') {
        setLeagues(leaguesResponse.leagues || []);
      }

      if (trendingResponse.status === 'success') {
        setTrendingPlayers(trendingResponse.trending || []);
      }
    } catch (err) {
      setError('Failed to load fantasy data. Please try again.');
      console.error('Load fantasy data error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleConnectAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsConnecting(true);
    setError(null);

    try {
      const response = await fantasyAPI.connectAccount(connectPlatform, { username });
      
      if (response.status === 'success') {
        setShowConnectModal(false);
        setUsername('');
        await loadFantasyData();
      } else {
        setError(response.message || 'Failed to connect account');
      }
    } catch (err) {
      setError('Failed to connect account. Please try again.');
      console.error('Connect account error:', err);
    } finally {
      setIsConnecting(false);
    }
  };

  const handleViewWaiverRecommendations = async () => {
    setIsLoadingWaiver(true);
    setShowWaiverRecommendations(true);
    setShowStartSitRecommendations(false);
    setShowStandings(false);
    setShowMatchups(false);
    setSelectedLeague(null);
    setError(null);

    try {
      const response = await fantasyAPI.getWaiverWireRecommendations(selectedWeek);
      
      if (response.status === 'success') {
        setWaiverRecommendations(response.recommendations || []);
      } else {
        setError(response.message || 'Failed to load waiver recommendations');
        setWaiverRecommendations([]);
      }
    } catch (err) {
      setError('Failed to load waiver recommendations. Please try again.');
      console.error('Load waiver recommendations error:', err);
      setWaiverRecommendations([]);
    } finally {
      setIsLoadingWaiver(false);
    }
  };

  const handleViewStartSitRecommendations = async () => {
    setIsLoadingStartSit(true);
    setShowStartSitRecommendations(true);
    setShowWaiverRecommendations(false);
    setShowStandings(false);
    setShowMatchups(false);
    setSelectedLeague(null);
    setError(null);

    try {
      const response = await fantasyAPI.getStartSitRecommendations(selectedWeek);
      
      if (response.status === 'success') {
        setStartSitRecommendations(response.recommendations || []);
      } else {
        setError(response.message || 'Failed to load start/sit recommendations');
        setStartSitRecommendations([]);
      }
    } catch (err) {
      setError('Failed to load start/sit recommendations. Please try again.');
      console.error('Load start/sit recommendations error:', err);
      setStartSitRecommendations([]);
    } finally {
      setIsLoadingStartSit(false);
    }
  };

  const handleViewStandings = async (leagueId: string) => {
    setIsLoadingStandings(true);
    setShowStandings(true);
    setShowWaiverRecommendations(false);
    setShowStartSitRecommendations(false);
    setShowMatchups(false);
    setSelectedLeague(leagueId);
    setError(null);

    try {
      const response = await fantasyAPI.getLeagueStandings(leagueId);
      
      if (response.status === 'success') {
        setStandings(response.standings || []);
      } else {
        setError(response.message || 'Failed to load league standings');
        setStandings([]);
      }
    } catch (err) {
      setError('Failed to load league standings. Please try again.');
      console.error('Load standings error:', err);
      setStandings([]);
    } finally {
      setIsLoadingStandings(false);
    }
  };

  const handleViewLeagueRules = async (leagueId: string) => {
    setIsLoadingRules(true);
    setShowLeagueRules(true);
    setShowStandings(false);
    setShowMatchups(false);
    setShowWaiverRecommendations(false);
    setShowStartSitRecommendations(false);
    setSelectedLeague(leagueId);
    setError(null);

    try {
      const response = await fantasyAPI.getLeagueRules(leagueId);
      
      if (response.status === 'success') {
        setLeagueRules(response.rules || null);
      } else {
        setError(response.message || 'Failed to load league rules');
        setLeagueRules(null);
      }
    } catch (err) {
      setError('Failed to load league rules. Please try again.');
      console.error('Load league rules error:', err);
      setLeagueRules(null);
    } finally {
      setIsLoadingRules(false);
    }
  };

  const handlePlayerSearch = async () => {
    console.log('handlePlayerSearch called with filters:', searchFilters);
    setIsLoadingSearch(true);
    setError(null);

    try {
      console.log('About to call fantasyAPI.searchPlayers...');
      const response = await fantasyAPI.searchPlayers({
        ...searchFilters,
        limit: 50,
        offset: 0
      });
      
      console.log('Search response:', response);
      
      if (response.status === 'success') {
        setSearchResults(response.players || []);
        console.log('Search results set:', response.players?.length || 0, 'players');
      } else {
        setError(response.message || 'Failed to search players');
        setSearchResults([]);
        console.error('Search failed:', response.message);
      }
    } catch (err) {
      setError('Failed to search players. Please try again.');
      console.error('Player search error:', err);
      setSearchResults([]);
    } finally {
      setIsLoadingSearch(false);
    }
  };

  const handlePlayerSelect = (playerId: string) => {
    const now = Date.now();
    console.log('handlePlayerSelect called with playerId:', playerId);
    
    // Debounce: prevent multiple rapid calls for the same player
    if (lastActionRef.current && 
        lastActionRef.current.playerId === playerId && 
        now - lastActionRef.current.timestamp < 100) {
      console.log('Debouncing duplicate call for playerId:', playerId);
      return;
    }
    
    lastActionRef.current = { playerId, timestamp: now };
    
    setSelectedPlayers(prev => {
      console.log('Previous selectedPlayers:', prev);
      
      if (prev.includes(playerId)) {
        // Remove player
        const newSelection = prev.filter(id => id !== playerId);
        console.log('Removing player, new selection:', newSelection);
        return newSelection;
      } else if (prev.length < 4) {
        // Add player
        const newSelection = [...prev, playerId];
        console.log('Adding player, new selection:', newSelection);
        return newSelection;
      }
      
      console.log('Max players reached, keeping:', prev);
      return prev;
    });
  };

  const handleCompareSelected = async () => {
    console.log('handleCompareSelected called with players:', selectedPlayers);
    
    if (selectedPlayers.length < 2) {
      setError('Please select at least 2 players to compare');
      return;
    }

    setIsLoadingSearch(true);
    setError(null);

    try {
      console.log('About to call fantasyAPI.comparePlayers...');
      const response = await fantasyAPI.comparePlayers(selectedPlayers, searchFilters.league_id || undefined);
      
      console.log('Compare response:', response);
      
      if (response.status === 'success') {
        setComparisonData(response.comparison);
        setShowComparison(true);
        console.log('Comparison data set, showing comparison');
      } else {
        setError(response.message || 'Failed to compare players');
        console.error('Compare failed:', response.message);
      }
    } catch (err) {
      setError('Failed to compare players. Please try again.');
      console.error('Player comparison error:', err);
    } finally {
      setIsLoadingSearch(false);
    }
  };

  const resetSearch = () => {
    setSearchFilters({
      query: '',
      position: '',
      team: '',
      age_min: null,
      age_max: null,
      experience_min: null,
      experience_max: null,
      availability: '',
      injury_status: '',
      trending: '',
      league_id: ''
    });
    setSearchResults([]);
    setSelectedPlayers([]);
    setShowFilters(false);
  };

  if (loading) {
    return (
      <Layout>
        <div className="min-h-screen flex items-center justify-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
      </Layout>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold text-gray-900">Fantasy Sports</h1>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-center space-x-2">
            <AlertCircle className="w-5 h-5 text-red-600" />
            <span className="text-red-800">{error}</span>
          </div>
        )}

        {isLoading ? (
          <div className="text-center py-12">
            <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-4 text-blue-600" />
            <p className="text-gray-600">Loading fantasy data...</p>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Connected Accounts Section */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-semibold">Connected Accounts</h2>
                <button
                  onClick={() => setShowConnectModal(true)}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center space-x-2"
                >
                  <Plus className="w-4 h-4" />
                  <span>Connect Account</span>
                </button>
              </div>

              {accounts.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <Users className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                  <p>No fantasy accounts connected</p>
                  <p className="text-sm">Connect your Sleeper account to get started</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {accounts.map((account) => (
                    <div key={account.id} className="flex items-center justify-between p-4 border border-gray-200 rounded-lg">
                      <div className="flex items-center space-x-3">
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-purple-100">
                          <img 
                            src="/sleeper.png" 
                            alt="Sleeper" 
                            className="w-8 h-8 rounded-lg"
                            onError={(e) => {
                              // Fallback to a simple text icon if image fails to load
                              e.currentTarget.style.display = 'none';
                              e.currentTarget.parentElement!.innerHTML = '<div class="w-8 h-8 rounded-lg bg-purple-600 text-white flex items-center justify-center text-sm font-bold">S</div>';
                            }}
                          />
                        </div>
                        <div>
                          <div className="font-medium">{account.platform}</div>
                          <div className="text-sm text-gray-500">@{account.username}</div>
                        </div>
                      </div>
                      <div className="flex items-center space-x-2">
                        <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded">Active</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Quick Actions Section */}
            {leagues.length > 0 && (
              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <h2 className="text-xl font-semibold mb-4">Fantasy Tools</h2>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <button
                    onClick={() => {
                      setShowPlayerSearch(true);
                      setShowStandings(false);
                      setShowMatchups(false);
                      setShowWaiverRecommendations(false);
                      setShowStartSitRecommendations(false);
                      setShowLeagueRules(false);
                    }}
                    className="flex items-center justify-center gap-3 p-4 border-2 border-blue-200 rounded-lg hover:border-blue-400 hover:bg-blue-50 transition-colors"
                  >
                    <Search className="w-6 h-6 text-blue-600" />
                    <div className="text-left">
                      <div className="font-semibold text-gray-900">Player Search</div>
                      <div className="text-sm text-gray-500">Advanced player lookup & analysis</div>
                    </div>
                  </button>
                  
                  <button
                    onClick={() => {
                      setShowComparison(true);
                      setShowPlayerSearch(false);
                      setShowStandings(false);
                      setShowMatchups(false);
                      setShowWaiverRecommendations(false);
                      setShowStartSitRecommendations(false);
                      setShowLeagueRules(false);
                    }}
                    className="flex items-center justify-center gap-3 p-4 border-2 border-purple-200 rounded-lg hover:border-purple-400 hover:bg-purple-50 transition-colors"
                  >
                    <BarChart3 className="w-6 h-6 text-purple-600" />
                    <div className="text-left">
                      <div className="font-semibold text-gray-900">Player Compare</div>
                      <div className="text-sm text-gray-500">Side-by-side player analysis</div>
                    </div>
                  </button>
                  
                  <button
                    className="flex items-center justify-center gap-3 p-4 border-2 border-gray-200 rounded-lg opacity-50 cursor-not-allowed"
                    disabled
                  >
                    <Eye className="w-6 h-6 text-gray-400" />
                    <div className="text-left">
                      <div className="font-semibold text-gray-500">Watchlist</div>
                      <div className="text-sm text-gray-400">Coming soon</div>
                    </div>
                  </button>
                </div>
              </div>
            )}

            {/* Fantasy Leagues Section */}
            {leagues.length > 0 && (
              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <h2 className="text-xl font-semibold mb-4">Fantasy Leagues</h2>
                <div className="space-y-4">
                  {leagues.map((league) => (
                    <div key={league.id} className="border border-gray-200 rounded-lg p-4">
                      <div className="flex items-center justify-between mb-3">
                        <div>
                          <h3 className="font-semibold">{league.name}</h3>
                          <p className="text-sm text-gray-500">{league.platform} • {league.season}</p>
                          <p className="text-sm text-gray-500">{league.total_teams} teams</p>
                        </div>
                        <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded">Synced</span>
                      </div>
                      {league.user_team && (
                        <div className="text-sm text-gray-600 mb-3">
                          <strong>{league.user_team.name}</strong> • {league.user_team.wins}-{league.user_team.losses} • {league.user_team.points_for} pts
                        </div>
                      )}
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleViewStandings(league.league_id)}
                          disabled={isLoadingStandings}
                          className="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1"
                        >
                          {isLoadingStandings && selectedLeague === league.league_id ? (
                            <RefreshCw className="w-3 h-3 animate-spin" />
                          ) : (
                            <Trophy className="w-3 h-3" />
                          )}
                          Standings
                        </button>
                        <button
                          onClick={() => handleViewLeagueRules(league.league_id)}
                          disabled={isLoadingRules}
                          className="px-3 py-1 bg-gray-600 text-white text-sm rounded hover:bg-gray-700 disabled:opacity-50 flex items-center gap-1"
                        >
                          {isLoadingRules && selectedLeague === league.league_id ? (
                            <RefreshCw className="w-3 h-3 animate-spin" />
                          ) : (
                            <Settings className="w-3 h-3" />
                          )}
                          Rules
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Trending Players Section */}
            {trendingPlayers.length > 0 && (
              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <h2 className="text-xl font-semibold mb-4">Trending Players</h2>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {trendingPlayers.slice(0, 6).map((player, index) => (
                    <div key={index} className="flex items-center justify-between p-3 border border-gray-200 rounded-lg">
                      <div>
                        <div className="font-medium">{player.first_name} {player.last_name}</div>
                        <div className="text-sm text-gray-500">{player.position} • {player.team}</div>
                      </div>
                      <div className="flex items-center space-x-1 text-green-600">
                        <TrendingUp className="w-4 h-4" />
                        <span className="text-sm font-medium">{player.count}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* AI Features */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <div className="mb-4">
                  <h2 className="text-xl font-semibold mb-3">AI Start/Sit Recommendations</h2>
                  <div className="flex items-center space-x-2">
                    <select 
                      value={selectedWeek} 
                      onChange={(e) => setSelectedWeek(Number(e.target.value))}
                      className="px-3 py-1 border border-gray-300 rounded-md text-sm"
                    >
                      {[...Array(18)].map((_, i) => (
                        <option key={i + 1} value={i + 1}>Week {i + 1}</option>
                      ))}
                    </select>
                    <button
                      onClick={handleViewStartSitRecommendations}
                      disabled={isLoadingStartSit || leagues.length === 0}
                      className="px-3 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center space-x-2 text-sm"
                    >
                      {isLoadingStartSit ? (
                        <RefreshCw className="w-4 h-4 animate-spin" />
                      ) : (
                        <Target className="w-4 h-4" />
                      )}
                      <span>{isLoadingStartSit ? 'Loading...' : 'Get Recommendations'}</span>
                    </button>
                  </div>
                </div>
                <div className="text-center py-8 text-gray-500">
                  <Target className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                  <p>AI-powered lineup optimization</p>
                  <p className="text-sm">Get personalized start/sit advice for your roster</p>
                </div>
              </div>

              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <div className="mb-4">
                  <h2 className="text-xl font-semibold mb-3">Waiver Wire Targets</h2>
                  <button
                    onClick={handleViewWaiverRecommendations}
                    disabled={isLoadingWaiver || leagues.length === 0}
                    className="px-3 py-2 bg-purple-600 text-white text-sm rounded-lg hover:bg-purple-700 disabled:opacity-50 flex items-center gap-2"
                  >
                    {isLoadingWaiver ? (
                      <>
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                        Loading...
                      </>
                    ) : (
                      <>
                        <TrendingUp className="w-4 h-4" />
                        Get Recommendations
                      </>
                    )}
                  </button>
                </div>
                <div className="text-center py-8 text-gray-500">
                  <TrendingUp className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                  <p>Click above to get smart pickup recommendations</p>
                  <p className="text-sm">Based on trending players and your roster needs</p>
                </div>
              </div>
            </div>

            {/* Start/Sit Recommendations View */}
            {showStartSitRecommendations && (
              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xl font-semibold">AI Start/Sit Recommendations - Week {selectedWeek}</h2>
                  <button
                    onClick={() => {
                      setShowStartSitRecommendations(false);
                      setStartSitRecommendations([]);
                    }}
                    className="text-gray-400 hover:text-gray-600"
                  >
                    ✕
                  </button>
                </div>

                {isLoadingStartSit ? (
                  <div className="text-center py-8">
                    <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-4 text-blue-600" />
                    <p className="text-gray-600">Analyzing your lineups...</p>
                  </div>
                ) : startSitRecommendations.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    <Target className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                    <p>No start/sit recommendations available for Week {selectedWeek}</p>
                    <p className="text-sm">Make sure you have connected leagues with active rosters</p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="flex items-center gap-4 mb-4 text-sm text-gray-600">
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 bg-green-500 rounded-full"></div>
                        <span>START</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 bg-red-500 rounded-full"></div>
                        <span>SIT</span>
                      </div>
                    </div>

                    {startSitRecommendations.map((rec, index) => (
                      <div key={index} className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center space-x-3">
                            <div className={`w-3 h-3 rounded-full ${
                              rec.recommendation === 'START' ? 'bg-green-500' : 'bg-red-500'
                            }`}></div>
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="font-semibold">{rec.player_name}</span>
                                <span className="px-2 py-1 bg-gray-100 text-gray-700 text-xs rounded">
                                  {rec.position}
                                </span>
                                <span className="text-sm text-gray-500">{rec.team}</span>
                                {rec.opponent && (
                                  <span className="text-sm text-gray-500">vs {rec.opponent}</span>
                                )}
                                {rec.is_questionable && (
                                  <span className="px-2 py-1 bg-yellow-100 text-yellow-700 text-xs rounded">
                                    Q
                                  </span>
                                )}
                              </div>
                              <div className="text-sm text-gray-600 mt-1">
                                {rec.league_name}
                              </div>
                            </div>
                          </div>
                          <div className="text-right">
                            <div className={`text-lg font-bold ${
                              rec.recommendation === 'START' ? 'text-green-600' : 'text-red-600'
                            }`}>
                              {rec.recommendation}
                            </div>
                            <div className="text-sm text-gray-600">
                              {rec.projected_points.toFixed(1)} pts projected
                            </div>
                            <div className="text-xs text-gray-500">
                              {rec.confidence}% confidence
                            </div>
                            <div className="text-xs text-gray-500">
                              #{rec.rank_in_position} of {rec.total_in_position} at {rec.position}
                            </div>
                          </div>
                        </div>
                        <div className="mt-3 p-3 bg-gray-50 rounded-md">
                          <p className="text-sm text-gray-700">{rec.reasoning}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* League Standings View */}
            {showStandings && (
              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xl font-semibold">League Standings</h2>
                  <button
                    onClick={() => {
                      setShowStandings(false);
                      setStandings([]);
                      setSelectedLeague(null);
                    }}
                    className="text-gray-400 hover:text-gray-600"
                  >
                    ✕
                  </button>
                </div>

                {isLoadingStandings ? (
                  <div className="text-center py-8">
                    <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-4 text-blue-600" />
                    <p className="text-gray-600">Loading standings...</p>
                  </div>
                ) : standings.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    <Trophy className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                    <p>No standings available</p>
                    <p className="text-sm">Check back later for updated standings</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b border-gray-200 text-left">
                          <th className="pb-2 font-medium text-gray-900">Rank</th>
                          <th className="pb-2 font-medium text-gray-900">Team</th>
                          <th className="pb-2 font-medium text-gray-900">Record</th>
                          <th className="pb-2 font-medium text-gray-900">Points For</th>
                          <th className="pb-2 font-medium text-gray-900">Points Against</th>
                          <th className="pb-2 font-medium text-gray-900">Waiver</th>
                        </tr>
                      </thead>
                      <tbody>
                        {standings.map((team, index) => (
                          <tr key={team.team_id} className={`border-b border-gray-100 ${
                            team.is_user_team ? 'bg-blue-50' : ''
                          }`}>
                            <td className="py-3 font-medium">{team.rank}</td>
                            <td className="py-3">
                              <div>
                                <div className={`font-medium ${
                                  team.is_user_team ? 'text-blue-700' : 'text-gray-900'
                                }`}>
                                  {team.name}
                                </div>
                                <div className="text-sm text-gray-500">{team.owner_name}</div>
                              </div>
                            </td>
                            <td className="py-3">
                              <div className="text-sm">
                                <div>{team.wins}-{team.losses}{team.ties > 0 ? `-${team.ties}` : ''}</div>
                                <div className="text-gray-500">({(team.win_percentage * 100).toFixed(1)}%)</div>
                              </div>
                            </td>
                            <td className="py-3">
                              <div className="text-sm">
                                <div>{team.points_for.toFixed(1)}</div>
                                <div className="text-gray-500">({team.points_per_game.toFixed(1)}/game)</div>
                              </div>
                            </td>
                            <td className="py-3">
                              <div className="text-sm">
                                <div>{team.points_against.toFixed(1)}</div>
                                <div className="text-gray-500">({team.points_against_per_game.toFixed(1)}/game)</div>
                              </div>
                            </td>
                            <td className="py-3 text-sm">{team.waiver_position}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Waiver Recommendations View */}
            {showWaiverRecommendations && (
              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xl font-semibold">Smart Waiver Wire Recommendations</h2>
                  <button
                    onClick={() => {
                      setShowWaiverRecommendations(false);
                      setWaiverRecommendations([]);
                    }}
                    className="text-gray-400 hover:text-gray-600"
                  >
                    ✕
                  </button>
                </div>

                {isLoadingWaiver ? (
                  <div className="text-center py-8">
                    <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-4 text-blue-600" />
                    <p className="text-gray-600">Finding the best pickup targets...</p>
                  </div>
                ) : waiverRecommendations.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    <TrendingUp className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                    <p>No waiver recommendations available</p>
                    <p className="text-sm">Check back later for trending pickup targets</p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {waiverRecommendations.map((rec, index) => (
                      <div key={index} className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center space-x-3">
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="font-semibold">{rec.player_name}</span>
                                <span className="px-2 py-1 bg-blue-100 text-blue-700 text-xs rounded">
                                  {rec.position}
                                </span>
                                <span className="text-sm text-gray-500">{rec.team}</span>
                              </div>
                              <div className="text-sm text-gray-600 mt-1">
                                {rec.league_name}
                              </div>
                              <div className="text-sm text-gray-600 mt-1">
                                {rec.reason}
                              </div>
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="text-lg font-bold text-red-500">
                              HIGH
                            </div>
                            <div className="text-sm font-medium text-gray-900">
                              {rec.priority_score.toFixed(1)}
                            </div>
                            <div className="text-xs text-gray-500">
                              FAAB: {rec.suggested_fab_percentage}%
                            </div>
                            {rec.trend_count > 0 && (
                              <div className="text-xs text-gray-500 flex items-center gap-1 mt-1">
                                <TrendingUp className="w-3 h-3" />
                                {rec.trend_count} adds
                              </div>
                            )}
                          </div>
                        </div>
                        {rec.fantasy_positions && rec.fantasy_positions.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {rec.fantasy_positions.map((pos, i) => (
                              <span key={i} className="px-2 py-1 bg-purple-100 text-purple-700 text-xs rounded">
                                {pos}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* League Rules View */}
        {showLeagueRules && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold">League Rules & Settings</h2>
              <button
                onClick={() => {
                  setShowLeagueRules(false);
                  setLeagueRules(null);
                  setSelectedLeague(null);
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>

            {isLoadingRules ? (
              <div className="text-center py-8">
                <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-4 text-blue-600" />
                <p className="text-gray-600">Loading league rules...</p>
              </div>
            ) : !leagueRules ? (
              <div className="text-center py-8 text-gray-500">
                <Settings className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                <p>No league rules available</p>
                <p className="text-sm">Unable to load league settings</p>
              </div>
            ) : (
              <div className="space-y-6">
                {/* League Overview */}
                <div className="bg-gray-50 rounded-lg p-4">
                  <h3 className="text-lg font-medium mb-3">League Overview</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <span className="text-gray-500">League Type:</span>
                      <div className="font-medium">{leagueRules.league_type}</div>
                    </div>
                    <div>
                      <span className="text-gray-500">Teams:</span>
                      <div className="font-medium">{leagueRules.team_count}</div>
                    </div>
                    <div>
                      <span className="text-gray-500">Platform:</span>
                      <div className="font-medium capitalize">{leagueRules.platform}</div>
                    </div>
                    <div>
                      <span className="text-gray-500">Season:</span>
                      <div className="font-medium">{leagueRules.season}</div>
                    </div>
                  </div>
                </div>

                {/* Scoring Settings */}
                <div className="bg-blue-50 rounded-lg p-4">
                  <h3 className="text-lg font-medium mb-3 text-blue-900">Scoring System</h3>
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-blue-800">Scoring Type:</span>
                      <span className="px-3 py-1 bg-blue-200 text-blue-800 rounded-full text-sm font-medium">
                        {leagueRules.scoring_settings.type}
                      </span>
                    </div>
                    
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                      <div className="bg-white p-3 rounded">
                        <h4 className="font-medium mb-2">Passing</h4>
                        <div className="space-y-1 text-xs">
                          <div>TDs: {leagueRules.scoring_settings.passing.touchdowns} pts</div>
                          <div>Yards: {leagueRules.scoring_settings.passing.yards_per_point > 0 ? `1 pt per ${Math.round(1/leagueRules.scoring_settings.passing.yards_per_point)} yds` : 'No pts'}</div>
                          <div>INTs: {leagueRules.scoring_settings.passing.interceptions} pts</div>
                        </div>
                      </div>
                      
                      <div className="bg-white p-3 rounded">
                        <h4 className="font-medium mb-2">Rushing</h4>
                        <div className="space-y-1 text-xs">
                          <div>TDs: {leagueRules.scoring_settings.rushing.touchdowns} pts</div>
                          <div>Yards: {leagueRules.scoring_settings.rushing.yards_per_point > 0 ? `1 pt per ${Math.round(1/leagueRules.scoring_settings.rushing.yards_per_point)} yds` : 'No pts'}</div>
                          <div>Fumbles: {leagueRules.scoring_settings.rushing.fumbles} pts</div>
                        </div>
                      </div>
                      
                      <div className="bg-white p-3 rounded">
                        <h4 className="font-medium mb-2">Receiving</h4>
                        <div className="space-y-1 text-xs">
                          <div>TDs: {leagueRules.scoring_settings.receiving.touchdowns} pts</div>
                          <div>Yards: {leagueRules.scoring_settings.receiving.yards_per_point > 0 ? `1 pt per ${Math.round(1/leagueRules.scoring_settings.receiving.yards_per_point)} yds` : 'No pts'}</div>
                          <div>Receptions: {leagueRules.scoring_settings.receiving.receptions} pts</div>
                        </div>
                      </div>
                    </div>

                    {leagueRules.scoring_settings.special_scoring.length > 0 && (
                      <div className="bg-white p-3 rounded">
                        <h4 className="font-medium mb-2">Bonus Scoring</h4>
                        <div className="space-y-1 text-xs">
                          {leagueRules.scoring_settings.special_scoring.map((bonus, index) => (
                            <div key={index} className="text-green-700">{bonus}</div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Roster Settings */}
                <div className="bg-green-50 rounded-lg p-4">
                  <h3 className="text-lg font-medium mb-3 text-green-900">Roster Configuration</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <span className="text-green-700">Total Roster:</span>
                      <div className="font-medium">{leagueRules.roster_settings.total_spots} players</div>
                    </div>
                    <div>
                      <span className="text-green-700">Starting:</span>
                      <div className="font-medium">{leagueRules.roster_settings.starting_spots} spots</div>
                    </div>
                    <div>
                      <span className="text-green-700">Bench:</span>
                      <div className="font-medium">{leagueRules.roster_settings.bench_spots} spots</div>
                    </div>
                    <div>
                      <span className="text-green-700">Superflex:</span>
                      <div className="font-medium">{leagueRules.ai_context.superflex ? 'Yes' : 'No'}</div>
                    </div>
                  </div>
                  
                  <div className="mt-3">
                    <h4 className="font-medium mb-2 text-green-800">Position Requirements</h4>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(leagueRules.roster_settings.positions).map(([position, count]) => (
                        <span key={position} className="px-2 py-1 bg-green-200 text-green-800 text-xs rounded">
                          {position}: {count}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                {/* AI Strategy Context */}
                <div className="bg-purple-50 rounded-lg p-4">
                  <h3 className="text-lg font-medium mb-3 text-purple-900">AI Strategy Context</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-purple-700">Volume Strategy:</span>
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          leagueRules.ai_context.prioritize_volume 
                            ? 'bg-green-200 text-green-800' 
                            : 'bg-red-200 text-red-800'
                        }`}>
                          {leagueRules.ai_context.prioritize_volume ? 'Target-Heavy WRs' : 'Efficiency Focus'}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-purple-700">RB Premium:</span>
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          leagueRules.ai_context.rb_premium 
                            ? 'bg-green-200 text-green-800' 
                            : 'bg-yellow-200 text-yellow-800'
                        }`}>
                          {leagueRules.ai_context.rb_premium ? 'High' : 'Standard'}
                        </span>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-purple-700">Flex Strategy:</span>
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          leagueRules.ai_context.flex_strategy 
                            ? 'bg-blue-200 text-blue-800' 
                            : 'bg-gray-200 text-gray-800'
                        }`}>
                          {leagueRules.ai_context.flex_strategy ? 'Flex Available' : 'No Flex'}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-purple-700">QB Strategy:</span>
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          leagueRules.ai_context.superflex 
                            ? 'bg-red-200 text-red-800' 
                            : 'bg-blue-200 text-blue-800'
                        }`}>
                          {leagueRules.ai_context.superflex ? 'QB Premium' : 'Standard QB'}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* League Features */}
                <div className="bg-yellow-50 rounded-lg p-4">
                  <h3 className="text-lg font-medium mb-3 text-yellow-900">League Features</h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                    <div>
                      <span className="text-yellow-700">Trades:</span>
                      <div className={`font-medium ${leagueRules.features.trades_enabled ? 'text-green-600' : 'text-red-600'}`}>
                        {leagueRules.features.trades_enabled ? 'Enabled' : 'Disabled'}
                      </div>
                    </div>
                    <div>
                      <span className="text-yellow-700">Waivers:</span>
                      <div className={`font-medium ${leagueRules.features.waivers_enabled ? 'text-green-600' : 'text-red-600'}`}>
                        {leagueRules.features.waivers_enabled ? 'Enabled' : 'Disabled'}
                      </div>
                    </div>
                    <div>
                      <span className="text-yellow-700">Playoff Teams:</span>
                      <div className="font-medium">{leagueRules.features.playoffs.teams}</div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Advanced Player Search Interface */}
        {showPlayerSearch && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold">Player Search & Analysis</h2>
              <button
                onClick={() => {
                  setShowPlayerSearch(false);
                  resetSearch();
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            {/* Search Controls */}
            <div className="space-y-4 mb-6">
              <div className="flex flex-col md:flex-row gap-4">
                <div className="flex-1">
                  <input
                    type="text"
                    placeholder="Search players by name..."
                    value={searchFilters.query}
                    onChange={(e) => setSearchFilters(prev => ({ ...prev, query: e.target.value }))}
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setShowFilters(!showFilters)}
                    className={`px-4 py-2 border rounded-lg flex items-center gap-2 ${
                      showFilters ? 'bg-blue-600 text-white border-blue-600' : 'border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <Filter className="w-4 h-4" />
                    Filters
                  </button>
                  <button
                    onClick={handlePlayerSearch}
                    disabled={isLoadingSearch}
                    className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
                  >
                    {isLoadingSearch ? (
                      <RefreshCw className="w-4 h-4 animate-spin" />
                    ) : (
                      <Search className="w-4 h-4" />
                    )}
                    Search
                  </button>
                </div>
              </div>

              {/* Advanced Filters */}
              {showFilters && (
                <div className="bg-gray-50 rounded-lg p-4 space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Position</label>
                      <select
                        value={searchFilters.position}
                        onChange={(e) => setSearchFilters(prev => ({ ...prev, position: e.target.value }))}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">All Positions</option>
                        <option value="QB">QB</option>
                        <option value="RB">RB</option>
                        <option value="WR">WR</option>
                        <option value="TE">TE</option>
                        <option value="K">K</option>
                        <option value="DEF">DEF</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Team</label>
                      <select
                        value={searchFilters.team}
                        onChange={(e) => setSearchFilters(prev => ({ ...prev, team: e.target.value }))}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">All Teams</option>
                        <option value="ARI">Cardinals</option>
                        <option value="ATL">Falcons</option>
                        <option value="BAL">Ravens</option>
                        <option value="BUF">Bills</option>
                        <option value="CAR">Panthers</option>
                        <option value="CHI">Bears</option>
                        <option value="CIN">Bengals</option>
                        <option value="CLE">Browns</option>
                        <option value="DAL">Cowboys</option>
                        <option value="DEN">Broncos</option>
                        <option value="DET">Lions</option>
                        <option value="GB">Packers</option>
                        <option value="HOU">Texans</option>
                        <option value="IND">Colts</option>
                        <option value="JAX">Jaguars</option>
                        <option value="KC">Chiefs</option>
                        <option value="LV">Raiders</option>
                        <option value="LAC">Chargers</option>
                        <option value="LAR">Rams</option>
                        <option value="MIA">Dolphins</option>
                        <option value="MIN">Vikings</option>
                        <option value="NE">Patriots</option>
                        <option value="NO">Saints</option>
                        <option value="NYG">Giants</option>
                        <option value="NYJ">Jets</option>
                        <option value="PHI">Eagles</option>
                        <option value="PIT">Steelers</option>
                        <option value="SF">49ers</option>
                        <option value="SEA">Seahawks</option>
                        <option value="TB">Buccaneers</option>
                        <option value="TEN">Titans</option>
                        <option value="WAS">Commanders</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Injury Status</label>
                      <select
                        value={searchFilters.injury_status}
                        onChange={(e) => setSearchFilters(prev => ({ ...prev, injury_status: e.target.value }))}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">All</option>
                        <option value="healthy">Healthy</option>
                        <option value="questionable">Questionable</option>
                        <option value="doubtful">Doubtful</option>
                        <option value="out">Out</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Trending</label>
                      <select
                        value={searchFilters.trending}
                        onChange={(e) => setSearchFilters(prev => ({ ...prev, trending: e.target.value }))}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">All</option>
                        <option value="hot">Trending Up</option>
                        <option value="cold">Trending Down</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">League Context</label>
                      <select
                        value={searchFilters.league_id}
                        onChange={(e) => setSearchFilters(prev => ({ ...prev, league_id: e.target.value }))}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">No League Context</option>
                        {leagues.map((league) => (
                          <option key={league.id} value={league.id}>
                            {league.name} ({league.scoring_type})
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="flex gap-2">
                      <div className="flex-1">
                        <label className="block text-sm font-medium text-gray-700 mb-1">Min Age</label>
                        <input
                          type="number"
                          min="20"
                          max="40"
                          value={searchFilters.age_min || ''}
                          onChange={(e) => setSearchFilters(prev => ({ 
                            ...prev, 
                            age_min: e.target.value ? parseInt(e.target.value) : null 
                          }))}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                      <div className="flex-1">
                        <label className="block text-sm font-medium text-gray-700 mb-1">Max Age</label>
                        <input
                          type="number"
                          min="20"
                          max="40"
                          value={searchFilters.age_max || ''}
                          onChange={(e) => setSearchFilters(prev => ({ 
                            ...prev, 
                            age_max: e.target.value ? parseInt(e.target.value) : null 
                          }))}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                    </div>

                    <div className="flex gap-2">
                      <div className="flex-1">
                        <label className="block text-sm font-medium text-gray-700 mb-1">Min Experience</label>
                        <input
                          type="number"
                          min="0"
                          max="20"
                          value={searchFilters.experience_min || ''}
                          onChange={(e) => setSearchFilters(prev => ({ 
                            ...prev, 
                            experience_min: e.target.value ? parseInt(e.target.value) : null 
                          }))}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                      <div className="flex-1">
                        <label className="block text-sm font-medium text-gray-700 mb-1">Max Experience</label>
                        <input
                          type="number"
                          min="0"
                          max="20"
                          value={searchFilters.experience_max || ''}
                          onChange={(e) => setSearchFilters(prev => ({ 
                            ...prev, 
                            experience_max: e.target.value ? parseInt(e.target.value) : null 
                          }))}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-end">
                    <button
                      onClick={resetSearch}
                      className="px-4 py-2 text-gray-600 hover:text-gray-800"
                    >
                      Reset Filters
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Selection and Compare Actions */}
            {selectedPlayers.length > 0 && (
              <div className="bg-blue-50 rounded-lg p-4 mb-6">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-medium">{selectedPlayers.length} player(s) selected</span>
                    {selectedPlayers.length >= 2 && (
                      <span className="text-sm text-gray-600 ml-2">Ready to compare</span>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setSelectedPlayers([])}
                      className="px-3 py-1 text-gray-600 hover:text-gray-800"
                    >
                      Clear
                    </button>
                    {selectedPlayers.length >= 2 && (
                      <button
                        onClick={handleCompareSelected}
                        disabled={isLoadingSearch}
                        className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                      >
                        Compare Players
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Search Results */}
            {searchResults.length > 0 && (
              <div className="space-y-4">
                <h3 className="text-lg font-medium">Search Results ({searchResults.length})</h3>
                <div className="grid gap-4">
                  {searchResults.map((player) => (
                    <div
                      key={player.player_id}
                      className={`border rounded-lg p-4 cursor-pointer transition-colors ${
                        selectedPlayers.includes(player.player_id)
                          ? 'border-blue-500 bg-blue-50'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                      onClick={() => handlePlayerSelect(player.player_id)}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-4">
                          <div className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              checked={selectedPlayers.includes(player.player_id)}
                              onChange={() => handlePlayerSelect(player.player_id)}
                              className="w-4 h-4 text-blue-600"
                            />
                            <div>
                              <div className="font-semibold">{player.name}</div>
                              <div className="text-sm text-gray-500">
                                {player.position} • {player.team}
                                {player.age && ` • Age ${player.age}`}
                                {player.experience !== undefined && ` • ${player.experience} yrs`}
                              </div>
                            </div>
                          </div>
                        </div>
                        
                        <div className="flex items-center gap-4">
                          {/* Injury Status */}
                          <div className={`px-2 py-1 rounded text-xs font-medium ${
                            player.injury_status === 'Healthy' 
                              ? 'bg-green-100 text-green-700'
                              : player.injury_status === 'Questionable'
                              ? 'bg-yellow-100 text-yellow-700'
                              : 'bg-red-100 text-red-700'
                          }`}>
                            {player.injury_status}
                          </div>

                          {/* Trending Status */}
                          {player.trending_status !== 'normal' && (
                            <div className={`px-2 py-1 rounded text-xs font-medium ${
                              player.trending_status === 'hot'
                                ? 'bg-orange-100 text-orange-700'
                                : 'bg-blue-100 text-blue-700'
                            }`}>
                              {player.trending_status === 'hot' ? '🔥 Hot' : '❄️ Cold'}
                            </div>
                          )}

                          {/* League Context */}
                          {player.league_metrics.position_value && (
                            <div className="text-xs text-gray-500">
                              {player.league_metrics.position_value}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* No Results */}
            {!isLoadingSearch && searchResults.length === 0 && searchFilters.query && (
              <div className="text-center py-8 text-gray-500">
                <Search className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                <p>No players found matching your search criteria</p>
                <p className="text-sm">Try adjusting your filters or search terms</p>
              </div>
            )}

            {/* Player Comparison Results */}
            {showComparison && comparisonData && (
              <div className="mt-8 space-y-6">
                <div className="flex items-center justify-between">
                  <h3 className="text-xl font-semibold">Player Comparison</h3>
                  <button
                    onClick={() => {
                      setShowComparison(false);
                      setComparisonData(null);
                    }}
                    className="text-gray-500 hover:text-gray-700"
                  >
                    ✕ Close
                  </button>
                </div>

                {/* Players Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {comparisonData.players.map((player: any, index: number) => (
                    <div key={player.player_id} className="bg-white border rounded-lg p-6">
                      <div className="flex items-center justify-between mb-4">
                        <h4 className="text-lg font-semibold">{player.name}</h4>
                        <div className="text-sm text-gray-500">
                          {player.position} • {player.team}
                        </div>
                      </div>

                      <div className="space-y-3">
                        <div className="grid grid-cols-2 gap-4 text-sm">
                          <div>
                            <span className="font-medium text-gray-600">Age:</span>
                            <span className="ml-2">{player.age}</span>
                          </div>
                          <div>
                            <span className="font-medium text-gray-600">Experience:</span>
                            <span className="ml-2">{player.experience} yrs</span>
                          </div>
                          <div>
                            <span className="font-medium text-gray-600">Height:</span>
                            <span className="ml-2">{player.physical_stats?.height || 'N/A'}</span>
                          </div>
                          <div>
                            <span className="font-medium text-gray-600">Weight:</span>
                            <span className="ml-2">{player.physical_stats?.weight ? `${player.physical_stats.weight} lbs` : 'N/A'}</span>
                          </div>
                          <div>
                            <span className="font-medium text-gray-600">College:</span>
                            <span className="ml-2">{player.career_info?.college || 'N/A'}</span>
                          </div>
                          <div>
                            <span className="font-medium text-gray-600">Depth Chart:</span>
                            <span className="ml-2">#{player.team_context?.depth_chart_order || 'N/A'}</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-2 pt-2">
                          <div className={`px-2 py-1 rounded text-xs font-medium ${
                            player.injury_status === 'Healthy' 
                              ? 'bg-green-100 text-green-700'
                              : player.injury_status === 'Questionable'
                              ? 'bg-yellow-100 text-yellow-700'
                              : 'bg-red-100 text-red-700'
                          }`}>
                            {player.injury_status}
                          </div>
                          
                          {player.trending?.type !== 'normal' && (
                            <div className={`px-2 py-1 rounded text-xs font-medium ${
                              player.trending.type === 'hot'
                                ? 'bg-orange-100 text-orange-700'
                                : 'bg-blue-100 text-blue-700'
                            }`}>
                              {player.trending.type === 'hot' ? '🔥 Hot' : '❄️ Cold'}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Comparison Insights */}
                {comparisonData.insights && comparisonData.insights.length > 0 && (
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                    <h4 className="font-semibold text-blue-900 mb-2">Comparison Insights</h4>
                    <ul className="space-y-1">
                      {comparisonData.insights.map((insight: string, index: number) => (
                        <li key={index} className="text-sm text-blue-800">
                          • {insight}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Comparison Date */}
                {comparisonData.comparison_date && (
                  <div className="text-xs text-gray-500 text-center">
                    Comparison generated on {new Date(comparisonData.comparison_date).toLocaleDateString()}
                  </div>
                )}
              </div>
            )}

            {/* Initial State */}
            {!isLoadingSearch && searchResults.length === 0 && !searchFilters.query && !showComparison && (
              <div className="text-center py-12 text-gray-500">
                <Search className="w-16 h-16 mx-auto mb-4 text-gray-300" />
                <h3 className="text-lg font-medium mb-2">Search NFL Players</h3>
                <p className="mb-4">Use the search bar and filters to find players</p>
                <ul className="text-sm space-y-1">
                  <li>• Search by name, position, or team</li>
                  <li>• Filter by age, experience, injury status</li>
                  <li>• Select multiple players to compare</li>
                  <li>• Get league-specific insights</li>
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Connect Account Modal */}
        {showConnectModal && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-lg max-w-md w-full p-6">
              <h2 className="text-xl font-semibold mb-4">Connect Fantasy Account</h2>
              
              <form onSubmit={handleConnectAccount} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Platform
                  </label>
                  <select
                    value={connectPlatform}
                    onChange={(e) => setConnectPlatform(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="sleeper">Sleeper</option>
                    <option value="yahoo" disabled>Yahoo (Coming Soon)</option>
                    <option value="espn" disabled>ESPN (Coming Soon)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Username
                  </label>
                  <input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="Enter your Sleeper username"
                    required
                  />
                </div>

                <div className="flex space-x-3">
                  <button
                    type="button"
                    onClick={() => setShowConnectModal(false)}
                    className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isConnecting}
                    className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
                  >
                    {isConnecting ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin mr-2" />
                        Connecting...
                      </>
                    ) : (
                      'Connect'
                    )}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}