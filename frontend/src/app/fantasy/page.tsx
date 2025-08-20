'use client';

import { useEffect, useState } from 'react';
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
  TrendingDown
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
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center">
                          <img 
                            src="https://play-lh.googleusercontent.com/JLW6o2Mmj5T4J0lGx5a3vRmwGILpWTweL8rmineEhIA9MZ_S-uMoqV4mzX19sIKPsVA" 
                            alt="Sleeper" 
                            className="w-8 h-8 rounded-lg"
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