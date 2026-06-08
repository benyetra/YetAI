/**
 * Trade Analyzer Component - Comprehensive fantasy trade analysis and recommendation system
 */
'use client';

import { useState, useEffect } from 'react';
import { apiRequest } from '@/lib/api-config';
import type { LeagueRules } from '@/lib/fantasy-league-rules';
import { calculateDeterministicTradeValue } from '@/lib/fantasy-trade-value';
import {
  buildTradeAssetsFromBuilder,
  buildTradeAssetsFromRecommendation,
  proposeTrade,
} from '@/lib/fantasy-trade-proposal';
import { 
  Users, 
  TrendingUp, 
  TrendingDown, 
  BarChart3, 
  Star,
  AlertCircle,
  CheckCircle,
  Clock,
  Target,
  Shuffle,
  Brain,
  Trophy,
  Lightbulb
} from 'lucide-react';

interface Player {
  id: number;
  name: string;
  position: string;
  team: string;
  age?: number;
  trade_value?: number;
}

interface DraftPick {
  pick_id: number;
  season: number;
  round: number;
  description: string;
  trade_value: number;
}

interface TradeAssets {
  players: number[];
  picks: number[];
  faab: number;
}

interface RecommendationTradeAssets {
  players: Player[];
  picks: number[];
  faab: number;
}

interface TradeEvaluation {
  trade_id: number;
  grades: {
    team1_grade: string;
    team2_grade: string;
  };
  values: {
    team1_value_given: number;
    team1_value_received: number;
    team2_value_given: number;
    team2_value_received: number;
  };
  analysis: {
    team1_analysis: any;
    team2_analysis: any;
  };
  fairness_score: number;
  ai_summary: string;
  key_factors: Array<{
    category: string;
    description: string;
    impact: string;
  }>;
  confidence: number;
}

interface TradeRecommendation {
  target_team_id: number;
  we_get: RecommendationTradeAssets;
  we_give: RecommendationTradeAssets;
  recommendation_type: string;
  title?: string;
  trade_rationale?: string;
  reasoning?: string;
  priority_score: number;
  estimated_likelihood: number;
  target_player_info?: any;
  trade_partner?: string; // Team name from backend
}

interface TeamAnalysis {
  team_info: {
    team_name: string;
    record: { wins: number; losses: number };
    points_for: number;
    team_rank: number;
    competitive_tier: string;
  };
  roster_analysis: {
    position_strengths: Record<string, number>;
    position_needs: Record<string, number>;
    surplus_positions: string[];
  };
  tradeable_assets: {
    surplus_players: Player[];
    expendable_players: Player[];
    valuable_players: Player[];
    tradeable_picks: DraftPick[];
  };
  trade_strategy: {
    competitive_analysis: any;
    trade_preferences: any;
    recommended_approach: string;
  };
}

interface LeagueTeam {
  id: number;
  name: string;
  owner_name: string;
}

interface League {
  id: string | number;
  name: string;
  platform: string;
  platform_league_id?: string;
  league_id?: string;
}

interface StandingsTeam {
  team_id: number;
  platform_team_id?: string;
  name: string;
  team_name?: string;
  owner_name: string;
  is_user_team?: boolean;
  wins: number;
  losses: number;
  ties?: number;
  win_percentage?: number;
  points_for: number;
  points_against?: number;
  points_per_game?: number;
  points_against_per_game?: number;
  point_differential?: number;
  waiver_position?: number;
  rank?: number;
}

interface TradeAnalyzerProps {
  leagues: League[];
  initialLeagueId?: string | number;
  teams: StandingsTeam[];
  leagueRules?: LeagueRules | null;
  isLoadingRules?: boolean;
  onLeagueChange?: (leagueId: string) => void;
}

function resolveLeagueKey(league: League): string {
  return String(league.league_id || league.id);
}

function findLeagueByKey(leagues: League[] | undefined, leagueKey: string | number | null) {
  if (!leagues || leagueKey == null) {
    return undefined;
  }
  const target = String(leagueKey);
  return leagues.find(
    (league) =>
      resolveLeagueKey(league) === target ||
      String(league.id) === target ||
      String(league.league_id) === target
  );
}

function getPlatformLeagueId(league: League | undefined): string | null {
  if (!league) {
    return null;
  }
  return league.platform_league_id || league.league_id || null;
}

type ApiRosterPlayer = {
  id: number;
  player_id?: string;
  name: string;
  position: string;
  team: string;
  age?: number;
  trade_value?: number;
};

function mapApiRosterToPlayers(roster: ApiRosterPlayer[] | undefined): Player[] {
  return (roster ?? [])
    .filter((player) => player?.name)
    .map((player) => ({
      id:
        typeof player.id === 'number' && !Number.isNaN(player.id)
          ? player.id
          : parseInt(String(player.player_id ?? ''), 10) || 0,
      name: player.name,
      position: player.position || 'UNKNOWN',
      team: player.team || 'UNKNOWN',
      age: player.age,
      trade_value: player.trade_value,
    }))
    .filter((player) => player.id > 0);
}

async function fetchTeamAnalysisFromBackend(
  teamId: number,
  leagues: League[],
  leagueKey: string
): Promise<{ team_analysis: TeamAnalysis; roster: Player[] } | null> {
  const league = findLeagueByKey(leagues, leagueKey);
  const platformLeagueId = getPlatformLeagueId(league);
  if (!platformLeagueId) {
    return null;
  }

  const response = await apiRequest(
    `/api/v1/fantasy/trade-analyzer/team-analysis/${teamId}?league_id=${encodeURIComponent(platformLeagueId)}`,
    { method: 'GET' }
  );
  if (!response.ok) {
    return null;
  }

  const data = await response.json();
  if (!data.success || !data.team_analysis) {
    return null;
  }

  return {
    team_analysis: data.team_analysis,
    roster: mapApiRosterToPlayers(data.roster),
  };
}

function calculateTradeValue(player: Player, leagueRules?: LeagueRules | null) {
  return calculateDeterministicTradeValue(player, leagueRules);
}

function formatScoringLabel(leagueRules?: LeagueRules | null): string | null {
  if (!leagueRules) {
    return null;
  }
  const scoringType =
    leagueRules.scoring_type || leagueRules.scoring_settings?.type || 'standard';
  if (scoringType === 'ppr') return 'Full PPR';
  if (scoringType === 'half_ppr') return 'Half PPR';
  return 'Standard';
}

function mapAnalysisResponseToTradeEvaluation(
  analysis: Record<string, any>,
  leagueRules?: LeagueRules | null
): TradeEvaluation {
  const team1Total = analysis.team1_gives?.total_value || 0;
  const team2Total = analysis.team2_gives?.total_value || 0;
  const scoringLabel = formatScoringLabel(leagueRules);

  return {
    trade_id: analysis.trade_id || 0,
    grades: {
      team1_grade: analysis.fairness?.verdict || 'N/A',
      team2_grade: analysis.fairness?.verdict || 'N/A',
    },
    values: {
      team1_value_given: team1Total,
      team1_value_received: team2Total,
      team2_value_given: team2Total,
      team2_value_received: team1Total,
    },
    analysis: {
      team1_analysis: analysis.team1_gives || {},
      team2_analysis: analysis.team2_gives || {},
    },
    fairness_score: analysis.fairness?.percentage || 0,
    ai_summary: scoringLabel
      ? `Trade Analysis (${scoringLabel}): ${analysis.fairness?.verdict || 'Unknown'}`
      : `Trade Analysis: ${analysis.fairness?.verdict || 'Unknown'}`,
    key_factors: (analysis.insights || []).map(
      (insight: string | { category?: string; description?: string; impact?: string }) =>
        typeof insight === 'string'
          ? { category: 'insight', description: insight, impact: 'medium' }
          : {
              category: insight.category || 'insight',
              description: insight.description || '',
              impact: insight.impact || 'medium',
            }
    ),
    confidence: analysis.fairness?.percentage || 0,
  };
}

export default function TradeAnalyzer({
  leagues,
  initialLeagueId,
  teams: standingsTeams,
  leagueRules,
  isLoadingRules = false,
  onLeagueChange,
}: TradeAnalyzerProps) {
  const getValidInitialLeague = (): string | null => {
    if (!initialLeagueId || !leagues?.length) {
      return null;
    }
    const match = findLeagueByKey(leagues, initialLeagueId);
    if (match) {
      return resolveLeagueKey(match);
    }
    return resolveLeagueKey(leagues[0]);
  };

  const [selectedLeague, setSelectedLeague] = useState<string | null>(() =>
    getValidInitialLeague()
  );
  const [selectedTeam, setSelectedTeam] = useState<number | null>(null);
  const [teams, setTeams] = useState<LeagueTeam[]>([]);
  const [teamAnalysis, setTeamAnalysis] = useState<TeamAnalysis | null>(null);
  const [recommendations, setRecommendations] = useState<TradeRecommendation[]>([]);
  const [activeTab, setActiveTab] = useState<'analyzer' | 'recommendations' | 'builder'>('analyzer');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [teamsLoading, setTeamsLoading] = useState(false);
  const [teamsError, setTeamsError] = useState<string | null>(null);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [rosterLoaded, setRosterLoaded] = useState(false);

  // Trade builder state
  const [targetTeam, setTargetTeam] = useState<number | null>(null);
  const [team1Gives, setTeam1Gives] = useState<TradeAssets>({ players: [], picks: [], faab: 0 });
  const [team2Gives, setTeam2Gives] = useState<TradeAssets>({ players: [], picks: [], faab: 0 });
  const [tradeEvaluation, setTradeEvaluation] = useState<TradeEvaluation | null>(null);
  
  // Available players state (removed unused variables)
  const [selectedTeamPlayers, setSelectedTeamPlayers] = useState<Player[]>([]);
  const [targetTeamPlayers, setTargetTeamPlayers] = useState<Player[]>([]);
  const [expandedRecommendation, setExpandedRecommendation] = useState<string | null>(null);
  const [proposingRecId, setProposingRecId] = useState<string | null>(null);
  const [recProposeMessages, setRecProposeMessages] = useState<
    Record<string, { type: 'success' | 'error'; text: string }>
  >({});
  const [proposingEvaluation, setProposingEvaluation] = useState(false);
  const [evalProposeMessage, setEvalProposeMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);

  useEffect(() => {
    if (initialLeagueId && leagues?.length) {
      const match = findLeagueByKey(leagues, initialLeagueId);
      if (match) {
        setSelectedLeague(resolveLeagueKey(match));
      }
    }
  }, [initialLeagueId, leagues]);

  useEffect(() => {
    if (selectedLeague && standingsTeams && standingsTeams.length > 0) {
      // Convert standings teams to the format expected by the component
      const formattedTeams = standingsTeams.map(team => ({
        id: parseInt(team.team_id.toString()), // Ensure ID is always a number
        name: team.name,
        owner_name: team.owner_name
      }));
      setTeams(formattedTeams);
      console.log('✅ Using REAL teams from standings:', formattedTeams.map(t => ({ id: t.id, name: t.name })));
    }
  }, [selectedLeague, standingsTeams]);

  // Load recommendations after selected team roster + analysis are loaded
  useEffect(() => {
    if (selectedTeam && selectedLeague && rosterLoaded) {
      loadTradeRecommendations(selectedTeam, selectedLeague);
    }
  }, [selectedTeam, selectedLeague, rosterLoaded]);

  // Update selectedLeague when leagues change or if current selection is invalid
  useEffect(() => {
    if (leagues && leagues.length > 0) {
      if (
        !selectedLeague ||
        !leagues.some((l) => resolveLeagueKey(l) === selectedLeague)
      ) {
        console.log('Current league selection invalid, switching to first available league');
        setSelectedLeague(resolveLeagueKey(leagues[0]));
      }
    }
  }, [leagues, selectedLeague]);

  useEffect(() => {
    if (selectedTeam && selectedLeague && leagues && teams && teams.length > 0) {
      console.log('Loading roster for selected team:', selectedTeam);
      setRosterLoaded(false);
      loadTeamRoster(selectedTeam, selectedLeague);
    }
  }, [selectedTeam, selectedLeague, leagues, teams]);

  useEffect(() => {
    if (targetTeam && selectedLeague && leagues && teams && teams.length > 0) {
      console.log('Loading roster for target team:', targetTeam);
      loadTargetTeamRoster(targetTeam, selectedLeague);
    }
  }, [targetTeam, selectedLeague, leagues, teams]);

  // Load real teams from API if no standings teams are available
  useEffect(() => {
    if (selectedLeague && (!standingsTeams || standingsTeams.length === 0)) {
      console.log('No standings teams available, attempting to load teams from API for league:', selectedLeague);
      loadTeamsFromAPI(selectedLeague);
    }
  }, [selectedLeague, standingsTeams]);

  // Helper function to load teams from API when standings data is not available
  const loadTeamsFromAPI = async (leagueKey: string) => {
    setTeamsLoading(true);
    setTeamsError(null);

    try {
      const league = findLeagueByKey(leagues, leagueKey);
      if (!league) {
        setTeams([]);
        setTeamsError('League not found. Select a connected league and try again.');
        return;
      }

      const platformLeagueId = league.platform_league_id || league.league_id;
      if (!platformLeagueId) {
        setTeams([]);
        setTeamsError('Missing Sleeper league ID for this league.');
        return;
      }

      console.log('Loading teams directly from Sleeper for league:', platformLeagueId);

      const [usersResponse, rostersResponse] = await Promise.all([
        fetch(`https://api.sleeper.app/v1/league/${platformLeagueId}/users`),
        fetch(`https://api.sleeper.app/v1/league/${platformLeagueId}/rosters`),
      ]);

      if (!usersResponse.ok || !rostersResponse.ok) {
        setTeams([]);
        setTeamsError(
          `Could not load league teams (Sleeper ${usersResponse.status}/${rostersResponse.status}). Try again.`
        );
        return;
      }

      const users = await usersResponse.json();
      const rosters = await rostersResponse.json();

      if (!Array.isArray(rosters) || rosters.length === 0) {
        setTeams([]);
        setTeamsError('No teams found for this league.');
        return;
      }

      const userById = Object.fromEntries(
        (users || []).map((user: { user_id: string }) => [user.user_id, user])
      );

      const realTeams = rosters.map((roster: { roster_id: number; owner_id: string }) => {
        const user = userById[roster.owner_id];
        return {
          id: roster.roster_id,
          name:
            user?.metadata?.team_name ||
            user?.display_name ||
            `Team ${roster.roster_id}`,
          owner_name: user?.display_name || `Owner ${roster.roster_id}`,
        };
      });

      setTeams(realTeams);
      console.log(
        'Loaded real teams from Sleeper:',
        realTeams.map((t: { id: number; name: string }) => ({ id: t.id, name: t.name }))
      );
    } catch (loadError) {
      console.error('Failed to load teams from API:', loadError);
      setTeams([]);
      setTeamsError('Failed to load league teams. Check your connection and retry.');
    } finally {
      setTeamsLoading(false);
    }
  };

  const loadTeamRoster = async (teamId: number, leagueKey: string) => {
    if (!leagues) {
      return;
    }

    setRosterLoading(true);
    setRosterLoaded(false);
    setError(null);

    try {
      const result = await fetchTeamAnalysisFromBackend(teamId, leagues, leagueKey);
      if (result) {
        setSelectedTeamPlayers(result.roster);
        setTeamAnalysis(result.team_analysis);
        setRosterLoaded(true);
        console.log(
          'Loaded team roster and analysis from backend:',
          result.roster.length,
          'players'
        );
        return;
      }

      setSelectedTeamPlayers([]);
      setTeamAnalysis(null);
      setError('Failed to load team roster from server');
      setRosterLoaded(true);
    } catch (loadError) {
      console.error('Failed to load team roster:', loadError);
      setSelectedTeamPlayers([]);
      setTeamAnalysis(null);
      setError('Failed to load team roster from server');
      setRosterLoaded(true);
    } finally {
      setRosterLoading(false);
    }
  };

  const loadTargetTeamRoster = async (teamId: number, leagueKey: string) => {
    if (!leagues) {
      return;
    }

    try {
      const result = await fetchTeamAnalysisFromBackend(teamId, leagues, leagueKey);
      setTargetTeamPlayers(result?.roster ?? []);
      console.log(
        'Loaded target team roster from backend:',
        result?.roster?.length ?? 0,
        'players'
      );
    } catch (loadError) {
      console.error('Failed to load target team roster:', loadError);
      setTargetTeamPlayers([]);
    }
  };

  const loadTradeRecommendations = async (teamId: number, leagueKey: string) => {
    console.log('loadTradeRecommendations called with teamId:', teamId, 'leagueId:', leagueKey);
    try {
      const league = findLeagueByKey(leagues, leagueKey);
      if (!league) {
        console.log(
          'League not found for trade recommendations, available leagues:',
          leagues?.map((l) => resolveLeagueKey(l))
        );
        return;
      }

      const platformLeagueId = league.platform_league_id || league.league_id;
      if (!platformLeagueId) {
        console.log('League missing platform ID for trade recommendations');
        return;
      }
      
      console.log(`Loading trade recommendations for team ${teamId} in league ${platformLeagueId}`);
      
      try {
        const token = localStorage.getItem('auth_token');
        const response = await apiRequest(`/api/v1/fantasy/trade-analyzer/recommendations`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            team_id: teamId,
            league_id: platformLeagueId,
            recommendation_type: 'all',
            max_recommendations: 10
          })
        });
        
        if (response.ok) {
          const data = await response.json();
          console.log('Trade recommendations API response:', data);
          if (data.success && data.recommendations) {
            setRecommendations(data.recommendations);
            console.log('Successfully loaded', data.recommendations.length, 'trade recommendations from backend');
            return;
          }
          console.log('API succeeded but no recommendations in response:', data);
        } else {
          const errorText = await response.text();
          console.log('Backend recommendations API failed with status:', response.status, 'error:', errorText);
        }
      } catch (apiError) {
        console.log('Backend recommendations API failed:', apiError);
      }

      setRecommendations([]);
    } catch (error) {
      console.error('Failed to load recommendations:', error);
      setRecommendations([]);
    }
  };

  const analyzeQuickTrade = async () => {
    if (!selectedLeague || !selectedTeam || !targetTeam || !leagues) return;
    
    try {
      setLoading(true);
      const league = findLeagueByKey(leagues, selectedLeague);
      const platformLeagueId = getPlatformLeagueId(league);
      if (!platformLeagueId) {
        setError('League is missing a platform ID');
        return;
      }

      const token = localStorage.getItem('auth_token');
      const response = await apiRequest('/api/v1/fantasy/trade-analyzer/quick-analysis', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          league_id: platformLeagueId,
          team1_id: selectedTeam,
          team2_id: targetTeam,
          team1_gives: team1Gives,
          team2_gives: team2Gives
        })
      });
      
      if (response.ok) {
        const data = await response.json();
        console.log('Quick analysis response:', data);

        if (data.success && data.analysis) {
          setTradeEvaluation(mapAnalysisResponseToTradeEvaluation(data.analysis, leagueRules));
        } else {
          console.error('Invalid API response:', data);
          setError('Invalid trade analysis response');
        }
      }
    } catch (error) {
      console.error('Failed to analyze trade:', error);
      setError('Failed to analyze trade');
    } finally {
      setLoading(false);
    }
  };

  const handleProposeFromRecommendation = async (
    rec: TradeRecommendation,
    recKey: string
  ) => {
    if (!selectedLeague || !selectedTeam || !leagues) {
      setRecProposeMessages((prev) => ({
        ...prev,
        [recKey]: { type: 'error', text: 'Select your team and league first' },
      }));
      return;
    }

    const league = findLeagueByKey(leagues, selectedLeague);
    const platformLeagueId = getPlatformLeagueId(league);
    if (!platformLeagueId) {
      setRecProposeMessages((prev) => ({
        ...prev,
        [recKey]: { type: 'error', text: 'League is missing a platform ID' },
      }));
      return;
    }

    setProposingRecId(recKey);
    setRecProposeMessages((prev) => {
      const next = { ...prev };
      delete next[recKey];
      return next;
    });

    try {
      const result = await proposeTrade({
        league_id: platformLeagueId,
        team1_id: selectedTeam,
        team2_id: rec.target_team_id,
        team1_gives: buildTradeAssetsFromRecommendation(rec.we_give),
        team2_gives: buildTradeAssetsFromRecommendation(rec.we_get),
        trade_reason: rec.title || rec.recommendation_type,
        persist: false,
      });

      if (!result.ok) {
        setRecProposeMessages((prev) => ({
          ...prev,
          [recKey]: { type: 'error', text: result.message },
        }));
        return;
      }

      setRecProposeMessages((prev) => ({
        ...prev,
        [recKey]: {
          type: 'success',
          text: result.data.validated
            ? 'Trade validated successfully'
            : 'Trade proposed successfully',
        },
      }));
    } catch (err) {
      console.error('Failed to propose trade from recommendation:', err);
      setRecProposeMessages((prev) => ({
        ...prev,
        [recKey]: { type: 'error', text: 'Failed to propose trade' },
      }));
    } finally {
      setProposingRecId(null);
    }
  };

  const handleProposeFromEvaluation = async () => {
    if (!selectedLeague || !selectedTeam || !targetTeam || !leagues) {
      setEvalProposeMessage({
        type: 'error',
        text: 'Select both teams and a league before proposing',
      });
      return;
    }

    const league = findLeagueByKey(leagues, selectedLeague);
    const platformLeagueId = getPlatformLeagueId(league);
    if (!platformLeagueId) {
      setEvalProposeMessage({ type: 'error', text: 'League is missing a platform ID' });
      return;
    }

    setProposingEvaluation(true);
    setEvalProposeMessage(null);

    try {
      const result = await proposeTrade({
        league_id: platformLeagueId,
        team1_id: selectedTeam,
        team2_id: targetTeam,
        team1_gives: buildTradeAssetsFromBuilder(team1Gives),
        team2_gives: buildTradeAssetsFromBuilder(team2Gives),
        persist: false,
      });

      if (!result.ok) {
        setEvalProposeMessage({ type: 'error', text: result.message });
        return;
      }

      if (result.data.evaluation) {
        setTradeEvaluation(
          mapAnalysisResponseToTradeEvaluation(
            result.data.evaluation as Record<string, any>,
            leagueRules
          )
        );
      }

      setEvalProposeMessage({
        type: 'success',
        text: result.data.validated
          ? 'Trade validated and ready to send'
          : 'Trade proposed successfully',
      });
    } catch (err) {
      console.error('Failed to propose trade from evaluation:', err);
      setEvalProposeMessage({ type: 'error', text: 'Failed to propose trade' });
    } finally {
      setProposingEvaluation(false);
    }
  };

  // Component renderers
  const renderTeamAnalysis = () => {
    if (!teamAnalysis) return null;

    const { team_info, roster_analysis, tradeable_assets, trade_strategy } = teamAnalysis;

    return (
      <div className="space-y-6">
        {/* Team Overview */}
        <div className="bg-white rounded-lg border p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xl font-semibold text-gray-900">{team_info.team_name}</h3>
            <div className="flex items-center space-x-4">
              <span className="text-sm text-gray-600">
                {team_info.record.wins}-{team_info.record.losses}
              </span>
              <span className="text-sm text-gray-600">
                Rank #{team_info.team_rank}
              </span>
              <span className={`px-2 py-1 rounded text-xs font-medium ${
                team_info.competitive_tier === 'championship' ? 'bg-green-100 text-green-800' :
                team_info.competitive_tier === 'competitive' ? 'bg-blue-100 text-blue-800' :
                team_info.competitive_tier === 'bubble' ? 'bg-yellow-100 text-yellow-800' :
                'bg-gray-100 text-gray-800'
              }`}>
                {team_info.competitive_tier}
              </span>
            </div>
          </div>
          
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-gray-900">
                {team_info.points_for.toFixed(1)}
              </div>
              <div className="text-sm text-gray-600">Points For</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-gray-900">
                {Object.keys(roster_analysis.position_strengths).length}
              </div>
              <div className="text-sm text-gray-600">Positions</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-gray-900">
                {tradeable_assets.surplus_players.length + tradeable_assets.expendable_players.length}
              </div>
              <div className="text-sm text-gray-600">Tradeable</div>
            </div>
          </div>

          <div className="border-t pt-4">
            <h4 className="font-medium text-gray-900 mb-2">Recommended Strategy</h4>
            <p className="text-sm text-gray-600">{trade_strategy.recommended_approach}</p>
          </div>
        </div>

        {/* Position Analysis */}
        <div className="grid grid-cols-2 gap-6">
          <div className="bg-white rounded-lg border p-6">
            <h4 className="font-medium text-gray-900 mb-4">Position Strengths</h4>
            <div className="space-y-3">
              {Object.entries(roster_analysis.position_strengths).map(([position, strength]) => (
                <div key={position} className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">{position}</span>
                  <div className="flex items-center space-x-2">
                    <div className="w-20 bg-gray-200 rounded-full h-2">
                      <div 
                        className="bg-blue-500 h-2 rounded-full"
                        style={{ width: `${Math.min(100, (strength as number / 25) * 100)}%` }}
                      />
                    </div>
                    <span className="text-sm text-gray-600 w-8 text-right">
                      {(strength as number).toFixed(1)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-white rounded-lg border p-6">
            <h4 className="font-medium text-gray-900 mb-4">Position Needs</h4>
            <div className="space-y-3">
              {Object.entries(roster_analysis.position_needs).map(([position, need]) => (
                <div key={position} className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">{position}</span>
                  <div className="flex items-center space-x-2">
                    <div className={`px-2 py-1 rounded text-xs font-medium ${
                      (need as number) >= 4 ? 'bg-red-100 text-red-800' :
                      (need as number) >= 3 ? 'bg-orange-100 text-orange-800' :
                      (need as number) >= 2 ? 'bg-yellow-100 text-yellow-800' :
                      'bg-green-100 text-green-800'
                    }`}>
                      Level {need}
                    </div>
                    {(need as number) >= 4 && <AlertCircle className="h-4 w-4 text-red-500" />}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Tradeable Assets */}
        <div className="bg-white rounded-lg border p-6">
          <h4 className="font-medium text-gray-900 mb-4">Tradeable Assets</h4>
          <div className="grid grid-cols-3 gap-6">
            <div>
              <h5 className="text-sm font-medium text-gray-700 mb-2">Valuable Players</h5>
              <div className="space-y-2">
                {tradeable_assets.valuable_players.slice(0, 5).filter(player => player.id && !isNaN(player.id)).map((player) => (
                  <div key={`valuable-${player.id}`} className="flex items-center justify-between text-sm">
                    <span>{player.name} ({player.position})</span>
                    <span className="text-green-600 font-medium">
                      {player.trade_value?.toFixed(1)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <h5 className="text-sm font-medium text-gray-700 mb-2">Expendable Players</h5>
              <div className="space-y-2">
                {tradeable_assets.expendable_players.slice(0, 5).filter(player => player.id && !isNaN(player.id)).map((player) => (
                  <div key={`expendable-${player.id}`} className="flex items-center justify-between text-sm">
                    <span>{player.name} ({player.position})</span>
                    <span className="text-blue-600 font-medium">
                      {player.trade_value?.toFixed(1)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <h5 className="text-sm font-medium text-gray-700 mb-2">Draft Picks</h5>
              <div className="space-y-2">
                {tradeable_assets.tradeable_picks.slice(0, 5).map((pick) => (
                  <div key={pick.pick_id} className="flex items-center justify-between text-sm">
                    <span>{pick.description}</span>
                    <span className="text-purple-600 font-medium">
                      {pick.trade_value.toFixed(1)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderRecommendations = () => {
    console.log('Rendering recommendations, count:', recommendations.length);
    
    if (recommendations.length === 0) {
      return (
        <div className="bg-white rounded-lg border p-6 text-center">
          <div className="text-gray-500 mb-4">
            <Lightbulb className="h-12 w-12 mx-auto mb-2 text-gray-300" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No Trade Recommendations</h3>
            <p>Loading trade recommendations or no recommendations available for this team.</p>
          </div>
        </div>
      );
    }
    
    const groupedRecommendations = recommendations.reduce((acc, rec) => {
      if (!acc[rec.recommendation_type]) {
        acc[rec.recommendation_type] = [];
      }
      acc[rec.recommendation_type].push(rec);
      return acc;
    }, {} as Record<string, TradeRecommendation[]>);

    return (
      <div className="space-y-6">
        {Object.entries(groupedRecommendations).map(([type, recs]) => (
          <div key={type} className="bg-white rounded-lg border p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900 capitalize flex items-center space-x-2">
                {type === 'position_need' && <Target className="h-5 w-5 text-red-500" />}
                {type === 'buy_low' && <TrendingDown className="h-5 w-5 text-green-500" />}
                {type === 'sell_high' && <TrendingUp className="h-5 w-5 text-orange-500" />}
                {type === 'consolidation' && <Shuffle className="h-5 w-5 text-blue-500" />}
                {type === 'depth' && <Users className="h-5 w-5 text-purple-500" />}
                <span>{type.replace('_', ' ')}</span>
              </h3>
              <span className="text-sm text-gray-500">{recs.length} recommendations</span>
            </div>

            <div className="space-y-4">
              {recs.slice(0, 3).map((rec, index) => {
                // Use trade_partner from API response or fallback to team lookup
                const apiResponse = rec as any; // Cast to access all API fields
                let targetTeamName = apiResponse.trade_partner;

                // If no trade_partner, try to look up team by ID
                if (!targetTeamName) {
                  const foundTeam = teams.find(t =>
                    String(t.id) === String(rec.target_team_id) ||
                    t.id === parseInt(String(rec.target_team_id))
                  );
                  targetTeamName = foundTeam?.name || `Team ${rec.target_team_id}`;
                }

                return (
                  <div key={index} className="border rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="font-medium text-gray-900">Trade with {targetTeamName}</h4>
                      <div className="flex items-center space-x-2">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          rec.priority_score >= 75 ? 'bg-green-100 text-green-800' :
                          rec.priority_score >= 50 ? 'bg-yellow-100 text-yellow-800' :
                          'bg-gray-100 text-gray-800'
                        }`}>
                          Priority: {rec.priority_score.toFixed(0)}
                        </span>
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          rec.estimated_likelihood >= 0.7 ? 'bg-green-100 text-green-800' :
                          rec.estimated_likelihood >= 0.4 ? 'bg-yellow-100 text-yellow-800' :
                          'bg-red-100 text-red-800'
                        }`}>
                          {Math.round(rec.estimated_likelihood * 100)}% likely
                        </span>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4 mb-3">
                      <div>
                        <h5 className="text-sm font-medium text-gray-700 mb-1">You Give:</h5>
                        <div className="text-sm text-gray-600">
                          {rec.we_give.players.length > 0 && (
                            <div>
                              <div className="font-medium">Players:</div>
                              {rec.we_give.players.map((player: Player, idx: number) => (
                                <div key={idx} className="ml-2">
                                  {player.name} ({player.position})
                                </div>
                              ))}
                            </div>
                          )}
                          {rec.we_give.picks.length > 0 && (
                            <div>Picks: {rec.we_give.picks.length}</div>
                          )}
                          {rec.we_give.faab > 0 && (
                            <div>FAAB: ${rec.we_give.faab}</div>
                          )}
                        </div>
                      </div>

                      <div>
                        <h5 className="text-sm font-medium text-gray-700 mb-1">You Get:</h5>
                        <div className="text-sm text-gray-600">
                          {rec.we_get.players.length > 0 && (
                            <div>
                              <div className="font-medium">Players:</div>
                              {rec.we_get.players.map((player: Player, idx: number) => (
                                <div key={idx} className="ml-2">
                                  {player.name} ({player.position})
                                </div>
                              ))}
                            </div>
                          )}
                          {rec.we_get.picks.length > 0 && (
                            <div>Picks: {rec.we_get.picks.length}</div>
                          )}
                          {rec.we_get.faab > 0 && (
                            <div>FAAB: ${rec.we_get.faab}</div>
                          )}
                        </div>
                      </div>
                    </div>

                    <p className="text-sm text-gray-600 mb-3">{rec.reasoning || rec.trade_rationale}</p>

                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <button 
                        className="text-blue-600 hover:text-blue-700 text-sm font-medium"
                        onClick={() => {
                          const recId = `${type}-${index}`;
                          setExpandedRecommendation(expandedRecommendation === recId ? null : recId);
                        }}
                      >
                        {expandedRecommendation === `${type}-${index}` ? 'Hide Details' : 'View Details'}
                      </button>
                      <div className="flex flex-col items-end gap-1">
                        <button
                          className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                          disabled={!selectedTeam || proposingRecId === `${type}-${index}`}
                          onClick={() => handleProposeFromRecommendation(rec, `${type}-${index}`)}
                        >
                          {proposingRecId === `${type}-${index}` ? 'Proposing...' : 'Propose Trade'}
                        </button>
                        {recProposeMessages[`${type}-${index}`] && (
                          <span
                            className={`text-xs ${
                              recProposeMessages[`${type}-${index}`].type === 'success'
                                ? 'text-green-700'
                                : 'text-red-700'
                            }`}
                          >
                            {recProposeMessages[`${type}-${index}`].text}
                          </span>
                        )}
                      </div>
                    </div>
                    
                    {expandedRecommendation === `${type}-${index}` && (
                      <div className="mt-4 pt-4 border-t border-gray-200">
                        <div className="grid grid-cols-2 gap-6">
                          <div>
                            <h6 className="font-medium text-gray-900 mb-2">Detailed Trade Breakdown - You Give:</h6>
                            {rec.we_give.players.map((player: Player, idx: number) => (
                              <div key={idx} className="bg-red-50 border border-red-200 rounded p-3 mb-2">
                                <div className="font-medium text-red-900">{player.name}</div>
                                <div className="text-sm text-red-700">
                                  {player.position} • {player.team} • Age: {player.age}
                                </div>
                                <div className="text-sm text-red-600">
                                  Trade Value: {player.trade_value}
                                </div>
                              </div>
                            ))}
                          </div>
                          <div>
                            <h6 className="font-medium text-gray-900 mb-2">Detailed Trade Breakdown - You Get:</h6>
                            {rec.we_get.players.map((player: Player, idx: number) => (
                              <div key={idx} className="bg-green-50 border border-green-200 rounded p-3 mb-2">
                                <div className="font-medium text-green-900">{player.name}</div>
                                <div className="text-sm text-green-700">
                                  {player.position} • {player.team} • Age: {player.age}
                                </div>
                                <div className="text-sm text-green-600">
                                  Trade Value: {player.trade_value}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div className="mt-4 bg-blue-50 border border-blue-200 rounded p-3">
                          <div className="font-medium text-blue-900 mb-1">Trade Analysis</div>
                          <div className="text-sm text-blue-700">
                            <div>Priority Score: {rec.priority_score}</div>
                            <div>Estimated Likelihood: {(rec.estimated_likelihood * 100).toFixed(0)}%</div>
                            <div>Trade Type: {rec.recommendation_type}</div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    );
  };

  const renderTradeBuilder = () => (
    <div className="space-y-6">
      {/* Team Selection */}
      <div className="bg-white rounded-lg border p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Build Custom Trade</h3>
        
        <div className="grid grid-cols-2 gap-6 mb-6">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Your Team</label>
            <select
              value={selectedTeam || ''}
              onChange={(e) => setSelectedTeam(e.target.value ? parseInt(e.target.value) : null)}
              className="w-full p-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="">Select your team</option>
              {teams.map(team => (
                <option key={team.id} value={team.id}>{team.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Target Team</label>
            <select
              value={targetTeam || ''}
              onChange={(e) => setTargetTeam(e.target.value ? parseInt(e.target.value) : null)}
              className="w-full p-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="">Select target team</option>
              {teams.filter(t => t.id !== selectedTeam && t.id !== parseInt(selectedTeam?.toString() || '0')).map(team => (
                <option key={team.id} value={team.id}>{team.name}</option>
              ))}
            </select>
          </div>
        </div>

        {targetTeam && (
          <div className="grid grid-cols-2 gap-6 mb-6">
            <div className="space-y-4">
              <h4 className="font-medium text-gray-900">You Give:</h4>
              <div className="border border-gray-300 rounded-lg p-4 max-h-60 overflow-y-auto">
                {selectedTeamPlayers.length > 0 ? (
                  <div className="space-y-2">
                    {selectedTeamPlayers.filter(player => player.id && !isNaN(player.id)).map(player => (
                      <div key={`selected-${player.id}`} className="flex items-center justify-between p-2 hover:bg-gray-50 rounded">
                        <div className="flex items-center space-x-3">
                          <input
                            type="checkbox"
                            checked={team1Gives.players.includes(player.id)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setTeam1Gives(prev => ({
                                  ...prev,
                                  players: [...prev.players, player.id]
                                }));
                              } else {
                                setTeam1Gives(prev => ({
                                  ...prev,
                                  players: prev.players.filter(p => p !== player.id)
                                }));
                              }
                            }}
                            className="rounded border-gray-300"
                          />
                          <div>
                            <div className="font-medium text-sm">{player.name}</div>
                            <div className="text-xs text-gray-500">{player.position} - {player.team}</div>
                          </div>
                        </div>
                        <div className="text-sm text-gray-600">
                          {player.trade_value?.toFixed(1)}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center text-gray-500 py-8">
                    {selectedTeam ? 'Loading roster...' : 'Select your team first'}
                  </div>
                )}
              </div>
            </div>

            <div className="space-y-4">
              <h4 className="font-medium text-gray-900">You Get:</h4>
              <div className="border border-gray-300 rounded-lg p-4 max-h-60 overflow-y-auto">
                {targetTeamPlayers.length > 0 ? (
                  <div className="space-y-2">
                    {targetTeamPlayers.filter(player => player.id && !isNaN(player.id)).map(player => (
                      <div key={`target-${player.id}`} className="flex items-center justify-between p-2 hover:bg-gray-50 rounded">
                        <div className="flex items-center space-x-3">
                          <input
                            type="checkbox"
                            checked={team2Gives.players.includes(player.id)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setTeam2Gives(prev => ({
                                  ...prev,
                                  players: [...prev.players, player.id]
                                }));
                              } else {
                                setTeam2Gives(prev => ({
                                  ...prev,
                                  players: prev.players.filter(p => p !== player.id)
                                }));
                              }
                            }}
                            className="rounded border-gray-300"
                          />
                          <div>
                            <div className="font-medium text-sm">{player.name}</div>
                            <div className="text-xs text-gray-500">{player.position} - {player.team}</div>
                          </div>
                        </div>
                        <div className="text-sm text-gray-600">
                          {player.trade_value?.toFixed(1)}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center text-gray-500 py-8">
                    {targetTeam ? 'Loading roster...' : 'Select target team first'}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="flex justify-center space-x-4">
          <button
            onClick={analyzeQuickTrade}
            disabled={!targetTeam || loading}
            className="bg-blue-600 text-white px-6 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Analyzing...' : 'Analyze Trade'}
          </button>
        </div>
      </div>

      {/* Trade Evaluation Results */}
      {tradeEvaluation && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center space-x-2">
            <Brain className="h-5 w-5 text-blue-500" />
            <span>AI Trade Analysis</span>
            {formatScoringLabel(leagueRules) && (
              <span className="text-xs font-normal text-gray-500">
                ({formatScoringLabel(leagueRules)} roster context)
              </span>
            )}
          </h3>

          <div className="grid grid-cols-3 gap-6 mb-6">
            <div className="text-center">
              <div className="text-3xl font-bold text-blue-600 mb-1">
                {tradeEvaluation.grades.team1_grade}
              </div>
              <div className="text-sm text-gray-600">Your Grade</div>
            </div>

            <div className="text-center">
              <div className="text-3xl font-bold text-green-600 mb-1">
                {tradeEvaluation.fairness_score.toFixed(0)}
              </div>
              <div className="text-sm text-gray-600">Fairness Score</div>
            </div>

            <div className="text-center">
              <div className="text-3xl font-bold text-purple-600 mb-1">
                {tradeEvaluation.grades.team2_grade}
              </div>
              <div className="text-sm text-gray-600">Their Grade</div>
            </div>
          </div>

          <div className="mb-6">
            <h4 className="font-medium text-gray-900 mb-2">AI Summary</h4>
            <p className="text-gray-600">{tradeEvaluation.ai_summary}</p>
          </div>

          <div className="mb-6">
            <h4 className="font-medium text-gray-900 mb-3">Key Factors</h4>
            <div className="space-y-2">
              {tradeEvaluation.key_factors.map((factor, index) => (
                <div key={index} className="flex items-center space-x-3 p-3 bg-gray-50 rounded-lg">
                  <div className={`w-2 h-2 rounded-full ${
                    factor.impact === 'high' ? 'bg-red-500' :
                    factor.impact === 'medium' ? 'bg-yellow-500' :
                    'bg-green-500'
                  }`} />
                  <div className="flex-1">
                    <span className="text-sm font-medium text-gray-900 capitalize">
                      {factor.category.replace('_', ' ')}:
                    </span>
                    <span className="text-sm text-gray-600 ml-1">
                      {factor.description}
                    </span>
                  </div>
                  <span className={`text-xs px-2 py-1 rounded ${
                    factor.impact === 'high' ? 'bg-red-100 text-red-800' :
                    factor.impact === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                    'bg-green-100 text-green-800'
                  }`}>
                    {factor.impact}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-2 pt-4 border-t sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center space-x-2">
              <span className="text-sm text-gray-600">Confidence:</span>
              <span className="text-sm font-medium text-gray-900">
                {tradeEvaluation.confidence.toFixed(0)}%
              </span>
            </div>
            <div className="flex flex-col items-end gap-1">
              <button
                className="bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={proposingEvaluation || !selectedTeam || !targetTeam}
                onClick={handleProposeFromEvaluation}
              >
                {proposingEvaluation ? 'Proposing...' : 'Propose Trade'}
              </button>
              {evalProposeMessage && (
                <span
                  className={`text-xs ${
                    evalProposeMessage.type === 'success' ? 'text-green-700' : 'text-red-700'
                  }`}
                >
                  {evalProposeMessage.text}
                </span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Trade Analyzer</h1>
          <p className="text-gray-600">
            AI-powered fantasy trade analysis and recommendations
          </p>
          {isLoadingRules && (
            <p className="mt-2 text-sm text-blue-600">Loading league scoring and roster rules…</p>
          )}
          {!isLoadingRules && leagueRules && (
            <div className="mt-3 flex flex-wrap gap-2 text-sm">
              <span className="rounded-full bg-blue-50 px-3 py-1 text-blue-800">
                {formatScoringLabel(leagueRules)} scoring
              </span>
              <span className="rounded-full bg-gray-100 px-3 py-1 text-gray-700">
                {leagueRules.roster_settings.starting_spots} starters
              </span>
              {leagueRules.ai_context.superflex && (
                <span className="rounded-full bg-purple-50 px-3 py-1 text-purple-800">
                  Superflex
                </span>
              )}
              {!leagueRules.features.trades_enabled && (
                <span className="rounded-full bg-red-50 px-3 py-1 text-red-700">
                  Trades disabled
                </span>
              )}
            </div>
          )}
          {!isLoadingRules && selectedLeague && !leagueRules && (
            <p className="mt-2 text-sm text-amber-700">
              League rules unavailable — analysis may use generic roster assumptions.
            </p>
          )}
        </div>

        {/* League and Team Selection */}
        <div className="bg-white rounded-lg border p-6 mb-8">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">League</label>
              <select
                value={selectedLeague || ''}
                onChange={(e) => {
                  const leagueKey = e.target.value || null;
                  setSelectedLeague(leagueKey);
                  if (leagueKey && onLeagueChange) {
                    onLeagueChange(leagueKey);
                  }
                }}
                className="w-full p-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="">Select league</option>
                {leagues.map((league) => (
                  <option key={resolveLeagueKey(league)} value={resolveLeagueKey(league)}>
                    {league.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Your Team</label>
              <select
                value={selectedTeam || ''}
                onChange={(e) => setSelectedTeam(e.target.value ? parseInt(e.target.value) : null)}
                className="w-full p-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                disabled={!selectedLeague}
              >
                <option value="">Select your team</option>
                {teams.map(team => (
                  <option key={team.id} value={team.id}>{team.name}</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {selectedTeam && selectedLeague && (
          <>
            {/* Tab Navigation */}
            <div className="bg-white rounded-lg border p-1 mb-8">
              <nav className="flex space-x-1">
                {[
                  { id: 'analyzer', label: 'Team Analysis', icon: BarChart3 },
                  { id: 'recommendations', label: 'Trade Recommendations', icon: Lightbulb },
                  { id: 'builder', label: 'Trade Builder', icon: Shuffle }
                ].map((tab) => {
                  const Icon = tab.icon;
                  return (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id as any)}
                      className={`flex items-center space-x-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                        activeTab === tab.id
                          ? 'bg-blue-600 text-white'
                          : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                      <span>{tab.label}</span>
                    </button>
                  );
                })}
              </nav>
            </div>

            {/* Tab Content */}
            <div>
              {teamsLoading && (
                <div className="flex items-center justify-center py-6 text-sm text-gray-600">
                  Loading league teams…
                </div>
              )}

              {teamsError && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-6">
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex items-center space-x-2">
                      <AlertCircle className="h-5 w-5 text-amber-600" />
                      <span className="text-amber-800">{teamsError}</span>
                    </div>
                    {selectedLeague && (
                      <button
                        type="button"
                        onClick={() => loadTeamsFromAPI(selectedLeague)}
                        className="text-sm font-medium text-amber-900 underline"
                      >
                        Retry
                      </button>
                    )}
                  </div>
                </div>
              )}

              {loading && (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                </div>
              )}

              {error && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
                  <div className="flex items-center space-x-2">
                    <AlertCircle className="h-5 w-5 text-red-500" />
                    <span className="text-red-700">{error}</span>
                  </div>
                </div>
              )}

              {!loading && !error && (
                <>
                  {activeTab === 'analyzer' && renderTeamAnalysis()}
                  {activeTab === 'recommendations' && renderRecommendations()}
                  {activeTab === 'builder' && renderTradeBuilder()}
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}