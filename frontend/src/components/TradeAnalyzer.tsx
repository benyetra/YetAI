/**
 * Trade Analyzer Component - Comprehensive fantasy trade analysis and recommendation system
 */
'use client';

import { useState, useEffect, useCallback } from 'react';
import { getApiUrl, apiRequest } from '@/lib/api-config';
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
  trade_rationale: string;
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
  id: number;
  name: string;
  platform: string;
  platform_league_id?: string;
  league_id?: string; // Alternative field name that might be used
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

interface TradeAnalyzerProps {
  leagues: League[];
  initialLeagueId?: number;
  teams: StandingsTeam[];
}

// Helper function to calculate realistic trade value on frontend
const calculateFrontendTradeValue = (position: string, age: number = 27) => {
  const baseValues = {
    "QB": [20, 45],
    "RB": [15, 40],
    "WR": [12, 38],
    "TE": [8, 25],
    "K": [2, 6],
    "DEF": [3, 8]
  };

  const [min, max] = baseValues[position] || [8, 15];
  let ageMultiplier = 1.0;

  if (age <= 24) ageMultiplier = 1.1;
  else if (age <= 27) ageMultiplier = 1.0;
  else if (age <= 30) ageMultiplier = 0.95;
  else ageMultiplier = 0.8;

  const baseValue = min + Math.random() * (max - min);
  return Math.round(baseValue * ageMultiplier * 10) / 10;
};

// Helper function for Sleeper player data
const calculateTradeValue = (player: any) => {
  const position = player.position || 'UNKNOWN';
  const age = player.age || 27;
  return calculateFrontendTradeValue(position, age);
};

export default function TradeAnalyzer({ leagues, initialLeagueId, teams: standingsTeams }: TradeAnalyzerProps) {
  // State management - validate initialLeagueId exists in leagues
  const getValidInitialLeague = () => {
    if (!initialLeagueId || !leagues) return null;
    const isValidLeague = leagues.some(l => l.id === initialLeagueId);
    if (isValidLeague) {
      return initialLeagueId;
    }
    // If invalid, use first available league
    return leagues.length > 0 ? leagues[0].id : null;
  };
  
  const [selectedLeague, setSelectedLeague] = useState<number | null>(() => getValidInitialLeague());
  const [selectedTeam, setSelectedTeam] = useState<number | null>(null);
  const [teams, setTeams] = useState<LeagueTeam[]>([]);
  const [teamAnalysis, setTeamAnalysis] = useState<TeamAnalysis | null>(null);
  const [recommendations, setRecommendations] = useState<TradeRecommendation[]>([]);
  const [activeTab, setActiveTab] = useState<'analyzer' | 'recommendations' | 'builder'>('analyzer');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  // Trigger team analysis and recommendations only after roster is loaded
  useEffect(() => {
    if (selectedTeam && selectedLeague && rosterLoaded) {
      loadTeamAnalysis(selectedTeam, selectedLeague);
      loadTradeRecommendations(selectedTeam, selectedLeague);
    }
  }, [selectedTeam, selectedLeague, rosterLoaded]);

  // Update selectedLeague when leagues change or if current selection is invalid
  useEffect(() => {
    if (leagues && leagues.length > 0) {
      if (!selectedLeague || !leagues.some(l => l.id === selectedLeague)) {
        console.log('Current league selection invalid, switching to first available league');
        setSelectedLeague(leagues[0].id);
      }
    }
  }, [leagues]);

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
  const loadTeamsFromAPI = async (leagueId: number) => {
    try {
      const league = leagues?.find(l => l.id === leagueId);
      if (!league) {
        console.error('League not found for teams loading:', leagueId);
        return;
      }

      const platformLeagueId = league.platform_league_id || league.league_id;
      if (!platformLeagueId) {
        console.error('No platform league ID found for league:', league);
        return;
      }

      console.log('Loading teams directly from Sleeper for league:', platformLeagueId);

      // Get users data from Sleeper API to get real team names
      const usersResponse = await fetch(`https://api.sleeper.app/v1/league/${platformLeagueId}/users`);

      if (usersResponse.ok) {
        const users = await usersResponse.json();
        console.log('Successfully loaded', users?.length, 'users from Sleeper API');

        if (users && users.length > 0) {
          const realTeams = users.map((user: any, index: number) => ({
            id: index + 1, // Use index-based ID for consistency
            name: user.metadata?.team_name || user.display_name || `Team ${index + 1}`,
            owner_name: user.display_name || `Owner ${index + 1}`
          }));

          setTeams(realTeams);
          console.log('Loaded real teams from API:', realTeams.map(t => ({ id: t.id, name: t.name })));
          return;
        }
      } else {
        console.error('Failed to fetch users from Sleeper API:', usersResponse.status);
      }
    } catch (error) {
      console.error('Failed to load teams from API:', error);
    }

    // Only create mock teams as absolute fallback
    console.log('Creating mock teams as fallback');
    const mockTeams = [
      { id: 1, name: "Team Alpha", owner_name: "Owner 1" },
      { id: 2, name: "Team Beta", owner_name: "Owner 2" },
      { id: 3, name: "Team Gamma", owner_name: "Owner 3" },
      { id: 4, name: "Team Delta", owner_name: "Owner 4" },
      { id: 5, name: "Team Epsilon", owner_name: "Owner 5" },
      { id: 6, name: "Team Zeta", owner_name: "Owner 6" },
      { id: 7, name: "Team Eta", owner_name: "Owner 7" },
      { id: 8, name: "Team Theta", owner_name: "Owner 8" },
      { id: 9, name: "Team Iota", owner_name: "Owner 9" },
      { id: 10, name: "Team Kappa", owner_name: "Owner 10" },
      { id: 11, name: "Team Lambda", owner_name: "Owner 11" },
      { id: 12, name: "Team Mu", owner_name: "Owner 12" }
    ];
    setTeams(mockTeams);
    console.log('Created mock teams as final fallback:', mockTeams.map(t => ({ id: t.id, name: t.name })));
  };

  // API calls
  const loadTeamRoster = async (teamId: number, leagueId: number) => {
    try {
      setRosterLoading(true);
      setRosterLoaded(false);
      if (!leagues || !teams) {
        console.log('Missing leagues or teams data');
        return;
      }
      
      // Find the league by internal ID
      const league = leagues.find(l => l.id === leagueId);
      if (!league) {
        console.error('League not found:', leagueId);
        console.log('Available leagues:', leagues.map(l => ({ id: l.id, name: l.name })));
        // Reset to first available league if current selection is invalid
        if (leagues.length > 0) {
          console.log('Switching to first available league:', leagues[0].id);
          setSelectedLeague(leagues[0].id);
        }
        return;
      }

      // Use the platform league ID for the backend API call
      const platformLeagueId = league.platform_league_id || league.league_id;
      if (!platformLeagueId) {
        console.error('No platform league ID found for league:', league);
        return;
      }
      
      console.log('Loading roster for team', teamId, 'in league', platformLeagueId);

      // Use fallback approach directly since we need to load any team's roster, not just current user's
      await loadTeamRosterFallback(platformLeagueId, teamId);
    } catch (error) {
      console.error('Failed to load team roster:', error);
      // Try fallback if main approach fails
      const league = leagues?.find(l => l.id === leagueId);
      if (league?.platform_league_id) {
        await loadTeamRosterFallback(league.platform_league_id, teamId);
      }
    } finally {
      setRosterLoading(false);
    }
  };

  // Fallback function to load roster directly from Sleeper API
  const loadTeamRosterFallback = async (platformLeagueId: string, teamId?: number) => {
    try {
      console.log('Using fallback roster loading for league:', platformLeagueId, 'team:', teamId);
      
      // Get both rosters and users data to do proper matching
      const [rostersResponse, usersResponse] = await Promise.all([
        fetch(`https://api.sleeper.app/v1/league/${platformLeagueId}/rosters`),
        fetch(`https://api.sleeper.app/v1/league/${platformLeagueId}/users`)
      ]);
      
      if (rostersResponse.ok && usersResponse.ok) {
        const rosters = await rostersResponse.json();
        const users = await usersResponse.json();
        console.log('Fallback: Successfully loaded', rosters?.length, 'rosters and', users?.length, 'users');
        
        if (teamId) {
          // Find the team name based on teamId - handle all type conversions
          console.log('Looking for selected team with ID:', teamId, 'type:', typeof teamId);

          const selectedTeam = teams.find(t => {
            // Try exact match first
            if (t.id === teamId) return true;
            // Try number conversion
            if (typeof teamId === 'string' && t.id === parseInt(teamId)) return true;
            if (typeof t.id === 'string' && parseInt(t.id) === teamId) return true;
            // Try string conversion
            if (t.id.toString() === teamId.toString()) return true;
            return false;
          });

          if (!selectedTeam) {
            console.error('Selected team not found with ID:', teamId, 'type:', typeof teamId);
            console.error('Available teams:', teams.map(t => ({ id: t.id, name: t.name, type: typeof t.id })));
            setSelectedTeamPlayers([]);
            return;
          }
          
          console.log('Looking for roster for selected team:', selectedTeam.name, 'owner:', selectedTeam.owner_name);
          
          // Find the user that matches the selected team owner
          const matchingUser = users.find(user => 
            user.display_name === selectedTeam.owner_name || 
            user.metadata?.team_name === selectedTeam.name ||
            user.display_name.toLowerCase() === selectedTeam.owner_name.toLowerCase()
          );
          
          if (!matchingUser) {
            console.warn('No matching user found for selected team:', selectedTeam.name, 'owner:', selectedTeam.owner_name);
            console.log('Available users:', users.map(u => ({ display_name: u.display_name, team_name: u.metadata?.team_name })));
            // Fallback to roster index mapping
            const availableRosters = rosters.filter(r => r.players && r.players.length > 0);
            const rosterIndex = ((teamId - 1) % availableRosters.length);
            const selectedRoster = availableRosters[rosterIndex];
            console.log('Fallback: Using roster at index:', rosterIndex, 'roster_id:', selectedRoster?.roster_id);
            
            if (selectedRoster && selectedRoster.players && selectedRoster.players.length > 0) {
              const playersData = await fetchPlayerDetails(selectedRoster.players);
              setSelectedTeamPlayers(playersData);
              setRosterLoaded(true);
              console.log('Fallback: Loaded', playersData?.length, 'players via fallback');
            } else {
              setRosterLoaded(true);
            }
            return;
          }
          
          // Find the roster that belongs to this user
          const selectedRoster = rosters.find(roster => roster.owner_id === matchingUser.user_id);
          if (!selectedRoster) {
            console.error('No roster found for user:', matchingUser.display_name);
            setSelectedTeamPlayers([]);
            return;
          }
          
          console.log('Found matching roster:', selectedRoster.roster_id, 'for user:', matchingUser.display_name);
          
          if (selectedRoster && selectedRoster.players && selectedRoster.players.length > 0) {
            const playersData = await fetchPlayerDetails(selectedRoster.players);
            setSelectedTeamPlayers(playersData);
            setRosterLoaded(true);
            console.log('Fallback: Loaded', playersData?.length, 'players');
          } else {
            console.log('Fallback: Selected roster has no players');
            setSelectedTeamPlayers([]);
            setRosterLoaded(true);
          }
        } else {
          console.log('Fallback: No rosters found in API response');
          setSelectedTeamPlayers([]);
          setRosterLoaded(true);
        }
      } else {
        console.error('Fallback: Failed to fetch rosters:', response.status);
        setSelectedTeamPlayers([]);
        setRosterLoaded(true);
      }
    } catch (error) {
      console.error('Fallback: Failed to load team roster:', error);
      setSelectedTeamPlayers([]);
      setRosterLoaded(true);
    }
  };

  const loadTargetTeamRoster = async (teamId: number, leagueId: number) => {
    try {
      console.log(`Loading target team roster for team ID: ${teamId}, league ID: ${leagueId}`);
      
      if (!leagues || !teams) {
        console.log('Missing leagues or teams data');
        return;
      }
      
      // Find the league by internal ID
      const league = leagues.find(l => l.id === leagueId);
      if (!league) {
        console.error('Target team: League not found:', leagueId);
        console.log('Available leagues:', leagues.map(l => ({ id: l.id, name: l.name })));
        return;
      }

      // Use the platform league ID for the backend API call
      const platformLeagueId = league.platform_league_id || league.league_id;
      if (!platformLeagueId) {
        console.error('Target team: No platform league ID found for league:', league);
        return;
      }
      
      console.log('Loading target roster for team', teamId, 'in league', platformLeagueId);
      
      // For target team, we'll use the fallback approach since we need different roster logic
      // The backend roster endpoint returns the current user's roster, but we need a different team's roster
      await loadTargetTeamRosterFallback(platformLeagueId, teamId);
      
    } catch (error) {
      console.error('Failed to load target team roster:', error);
      const league = leagues?.find(l => l.id === leagueId);
      if (league?.platform_league_id) {
        await loadTargetTeamRosterFallback(league.platform_league_id, teamId);
      }
    }
  };

  // Fallback function to load target team roster directly from Sleeper API
  const loadTargetTeamRosterFallback = async (platformLeagueId: string, teamId: number) => {
    try {
      console.log('Loading target team roster from Sleeper for league:', platformLeagueId, 'team:', teamId);
      
      // Get both rosters and users data to do proper matching
      const [rostersResponse, usersResponse] = await Promise.all([
        fetch(`https://api.sleeper.app/v1/league/${platformLeagueId}/rosters`),
        fetch(`https://api.sleeper.app/v1/league/${platformLeagueId}/users`)
      ]);
      
      if (rostersResponse.ok && usersResponse.ok) {
        const rosters = await rostersResponse.json();
        const users = await usersResponse.json();
        console.log('Successfully loaded', rosters?.length, 'rosters and', users?.length, 'users');
        
        // Find the team name based on teamId - handle all type conversions
        console.log('Looking for target team with ID:', teamId, 'type:', typeof teamId);
        console.log('Available teams:', teams.map(t => ({ id: t.id, name: t.name, type: typeof t.id })));

        const targetTeam = teams.find(t => {
          // Try exact match first
          if (t.id === teamId) return true;
          // Try number conversion
          if (typeof teamId === 'string' && t.id === parseInt(teamId)) return true;
          if (typeof t.id === 'string' && parseInt(t.id) === teamId) return true;
          // Try string conversion
          if (t.id.toString() === teamId.toString()) return true;
          return false;
        });

        if (!targetTeam) {
          console.error('Target team not found with ID:', teamId, 'type:', typeof teamId);
          console.error('Available teams:', teams.map(t => ({ id: t.id, name: t.name, type: typeof t.id })));
          setTargetTeamPlayers([]);
          return;
        }
        
        console.log('Looking for roster for team:', targetTeam.name, 'owner:', targetTeam.owner_name);
        
        // Find the user that matches the target team owner
        const matchingUser = users.find(user => 
          user.display_name === targetTeam.owner_name || 
          user.metadata?.team_name === targetTeam.name ||
          user.display_name.toLowerCase() === targetTeam.owner_name.toLowerCase()
        );
        
        if (!matchingUser) {
          console.warn('No matching user found for team:', targetTeam.name, 'owner:', targetTeam.owner_name);
          console.log('Available users:', users.map(u => ({ display_name: u.display_name, team_name: u.metadata?.team_name })));
          // Fallback to roster index mapping
          const availableRosters = rosters.filter(r => r.players && r.players.length > 0);
          const rosterIndex = (teamId + 1) % availableRosters.length;
          const targetRoster = availableRosters[rosterIndex];
          console.log('Using fallback roster at index:', rosterIndex, 'roster_id:', targetRoster?.roster_id);
          
          if (targetRoster && targetRoster.players && targetRoster.players.length > 0) {
            const playersData = await fetchPlayerDetails(targetRoster.players);
            setTargetTeamPlayers(playersData);
            console.log('Loaded', playersData?.length, 'target players via fallback');
          }
          return;
        }
        
        // Find the roster that belongs to this user
        const targetRoster = rosters.find(roster => roster.owner_id === matchingUser.user_id);
        if (!targetRoster) {
          console.error('No roster found for user:', matchingUser.display_name);
          setTargetTeamPlayers([]);
          return;
        }
        
        console.log('Found matching roster:', targetRoster.roster_id, 'for user:', matchingUser.display_name);
        
        if (targetRoster && targetRoster.players && targetRoster.players.length > 0) {
          const playersData = await fetchPlayerDetails(targetRoster.players);
          setTargetTeamPlayers(playersData);
          console.log('Loaded', playersData?.length, 'target players');
        } else {
          console.log('Target roster has no players');
          setTargetTeamPlayers([]);
        }
      } else {
        console.log('No target rosters found in API response');
        setTargetTeamPlayers([]);
      }
    } catch (error) {
      console.error('Failed to load target team roster:', error);
      setTargetTeamPlayers([]);
    }
  };

  const fetchPlayerDetails = async (playerIds: string[]): Promise<Player[]> => {
    try {
      console.log('Fetching player details for IDs:', playerIds);
      
      // Get all NFL players from Sleeper API
      const response = await fetch('https://api.sleeper.app/v1/players/nfl');
      if (response.ok) {
        const allPlayers = await response.json();
        console.log('Got player database, processing', playerIds.length, 'players');
        
        // Get trade values for all players at once
        const playerNames = playerIds.map(playerId => {
          const player = allPlayers[playerId];
          return player ? `${player.first_name || ''} ${player.last_name || ''}`.trim() : '';
        }).filter(name => name);
        
        let tradeValues: { [key: string]: number } = {};
        try {
          const valueResponse = await apiRequest(`/api/v1/fantasy/trade-analyzer/player-values?limit=200`, { method: 'GET' });
          if (valueResponse.ok) {
            const valueData = await valueResponse.json();
            if (valueData.success) {
              // Create lookup map by player name
              valueData.players.forEach((p: any) => {
                tradeValues[p.name] = p.trade_value;
              });
            }
          }
        } catch (e) {
          console.log('Failed to fetch trade values, using fallbacks');
        }
        
        // Filter and format players
        const formattedPlayers = playerIds.map((playerId, index) => {
          const player = allPlayers[playerId];
          // Create a safe numeric ID - use playerId hash or index as fallback
          const numericId = playerId && !isNaN(parseInt(playerId)) ? parseInt(playerId) : 
                          playerId ? playerId.split('').reduce((a, b) => a + b.charCodeAt(0), 0) : 
                          1000000 + index; // Ensure unique fallback ID
          
          if (player) {
            const playerName = `${player.first_name || ''} ${player.last_name || ''}`.trim();
            const trade_value = tradeValues[playerName] || calculateTradeValue(player); // Use API value or calculate realistic value
            
            return {
              id: numericId,
              name: playerName,
              position: player.position || 'Unknown',
              team: player.team || 'Unknown',
              age: player.age || 0,
              trade_value: trade_value
            };
          }
          return {
            id: numericId,
            name: `Player ${playerId || 'Unknown'}`,
            position: 'Unknown',
            team: 'Unknown',
            age: 0,
            trade_value: 5
          };
        }).filter(p => p.name !== `Player ${p.id}` && p.name !== 'Player Unknown'); // Filter out unknown players
        
        console.log('Formatted players:', formattedPlayers);
        return formattedPlayers;
      } else {
        console.error('Failed to fetch players API:', response.status);
      }
    } catch (error) {
      console.error('Failed to fetch player details:', error);
    }
    return [];
  };

  const loadTeamAnalysis = async (teamId: number, leagueId: number) => {
    try {
      setLoading(true);
      
      // Get the league from leagues data
      const league = leagues?.find(l => l.id === leagueId);
      if (!league) {
        console.log('League not found for team analysis');
        setError('League not found');
        return;
      }

      // Use the real platform league ID
      const platformLeagueId = league.platform_league_id || '1257417114529054720';
      
      console.log(`Loading team analysis for team ${teamId} in league ${platformLeagueId}`);
      
      // Try backend API first, fall back to direct calculation if needed
      try {
        const token = localStorage.getItem('auth_token');
        // Use internal league ID for backend API call and correct URL structure
        const response = await apiRequest(`/api/v1/fantasy/trade-analyzer/team-analysis/${teamId}?league_id=${leagueId}`, {
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          }
        });
        
        if (response.ok) {
          const data = await response.json();
          if (data.success && data.team_analysis) {
            setTeamAnalysis(data.team_analysis);
            setError(null);
            console.log('Successfully loaded team analysis from backend');
            return;
          }
        } else {
          console.log('Backend team analysis API failed with status:', response.status);
        }
      } catch (apiError) {
        console.log('Backend API failed, generating analysis from roster data:', apiError);
      }

      // Fallback: Generate analysis from current roster data
      if (selectedTeamPlayers && selectedTeamPlayers.length > 0) {
        const teamName = teams?.find(t => t.id === teamId)?.name || `Team ${teamId}`;
        
        // Calculate position strengths based on roster
        const positionCounts = { QB: 0, RB: 0, WR: 0, TE: 0, K: 0, DEF: 0 };
        selectedTeamPlayers.forEach(player => {
          if (player.position && Object.prototype.hasOwnProperty.call(positionCounts, player.position)) {
            (positionCounts as any)[player.position]++;
          }
        });

        const generatedAnalysis = {
          team_info: {
            team_name: teamName,
            record: { wins: 0, losses: 0 }, // Would need standings data
            points_for: 0, // Would need scoring data
            team_rank: 0,
            competitive_tier: 'unknown'
          },
          roster_analysis: {
            position_strengths: {
              QB: positionCounts.QB * 20,
              RB: positionCounts.RB * 15,
              WR: positionCounts.WR * 12,
              TE: positionCounts.TE * 18,
              K: positionCounts.K * 10,
              DEF: positionCounts.DEF * 16
            },
            position_needs: {
              QB: positionCounts.QB < 2 ? 3 : 1,
              RB: positionCounts.RB < 3 ? 3 : 1,
              WR: positionCounts.WR < 4 ? 3 : 1,
              TE: positionCounts.TE < 2 ? 3 : 1,
              K: positionCounts.K < 1 ? 3 : 1,
              DEF: positionCounts.DEF < 1 ? 3 : 1
            },
            surplus_positions: Object.entries(positionCounts)
              .filter(([pos, count]) => count > (pos === 'WR' ? 4 : pos === 'RB' ? 3 : 2))
              .map(([pos]) => pos)
          },
          tradeable_assets: {
            surplus_players: selectedTeamPlayers.slice(0, 5).map(p => ({
              ...p,
              trade_value: p.trade_value || 15
            })),
            expendable_players: selectedTeamPlayers.slice(5, 8).map(p => ({
              ...p,
              trade_value: p.trade_value || 8
            })),
            valuable_players: selectedTeamPlayers.slice(0, 3).map(p => ({
              ...p,
              trade_value: p.trade_value || calculateFrontendTradeValue(p.position, p.age)
            })),
            tradeable_picks: [
              { pick_id: 1, season: 2025, round: 1, description: '2025 1st Round Pick', trade_value: 35 },
              { pick_id: 2, season: 2025, round: 2, description: '2025 2nd Round Pick', trade_value: 18 },
              { pick_id: 3, season: 2025, round: 3, description: '2025 3rd Round Pick', trade_value: 8 }
            ]
          },
          trade_strategy: {
            competitive_analysis: {},
            trade_preferences: {},
            recommended_approach: 'Analysis based on current roster composition. Consider strengthening weak positions.'
          }
        };

        setTeamAnalysis(generatedAnalysis);
        setError(null);
        console.log('Generated team analysis from roster data');
      } else {
        setError('No roster data available for analysis');
        console.log('No roster data available for team analysis');
      }
      
    } catch (error) {
      console.error('Failed to load team analysis:', error);
      setError('Failed to load team analysis');
    } finally {
      setLoading(false);
    }
  };

  const loadTradeRecommendations = async (teamId: number, leagueId: number) => {
    console.log('loadTradeRecommendations called with teamId:', teamId, 'leagueId:', leagueId);
    try {
      // Get the league from leagues data
      const league = leagues?.find(l => l.id === leagueId);
      if (!league) {
        console.log('League not found for trade recommendations, available leagues:', leagues?.map(l => l.id));
        return;
      }

      // Use the real platform league ID
      const platformLeagueId = league.platform_league_id || '1257417114529054720';
      
      console.log(`Loading trade recommendations for team ${teamId} in league ${platformLeagueId}`);
      
      // Try backend API first
      try {
        const token = localStorage.getItem('auth_token');
        // Use internal league ID for backend API call and correct URL structure
        const response = await apiRequest(`/api/v1/fantasy/trade-analyzer/recommendations`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            team_id: teamId,
            league_id: leagueId,
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
          } else {
            console.log('API succeeded but no recommendations in response:', data);
          }
        } else {
          const errorText = await response.text();
          console.log('Backend recommendations API failed with status:', response.status, 'error:', errorText);
        }
      } catch (apiError) {
        console.log('Backend API failed, generating basic recommendations:', apiError);
      }

      // Fallback: Generate basic recommendations based on available teams
      if (teams && teams.length > 1) {
        const availableTeams = teams.filter(t => t.id !== teamId);
        const basicRecommendations = availableTeams.slice(0, 3).map((team, index) => ({
          target_team_id: team.id,
          we_get: { players: [], picks: [], faab: 0 },
          we_give: { players: [], picks: [], faab: 0 },
          recommendation_type: ['position_need', 'consolidation', 'buy_low'][index] || 'general',
          trade_rationale: `Consider trading with ${team.name} to address roster needs and strengthen playoff positioning.`,
          priority_score: 75 - (index * 5),
          estimated_likelihood: 0.6 - (index * 0.1)
        }));
        
        setRecommendations(basicRecommendations);
        console.log('Generated basic trade recommendations');
      } else {
        console.log('No teams available for recommendations');
        setRecommendations([]);
      }
    } catch (error) {
      console.error('Failed to load recommendations:', error);
      setRecommendations([]);
    }
  };

  const analyzeQuickTrade = async () => {
    if (!selectedLeague || !selectedTeam || !targetTeam) return;
    
    try {
      setLoading(true);
      const token = localStorage.getItem('auth_token');
      const response = await apiRequest('/api/v1/fantasy/trade-analyzer/quick-analysis', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          league_id: selectedLeague,
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
          setTradeEvaluation({
            trade_id: data.analysis.trade_id || 0,
            grades: {
              team1_grade: data.analysis.fairness?.verdict || 'N/A',
              team2_grade: data.analysis.fairness?.verdict || 'N/A'
            },
            values: {
              team1_total: data.analysis.team1_gives?.total_value || 0,
              team2_total: data.analysis.team2_gives?.total_value || 0,
              difference: data.analysis.fairness?.value_difference || 0
            },
            analysis: {
              team1_analysis: data.analysis.team1_gives || {},
              team2_analysis: data.analysis.team2_gives || {}
            },
            fairness_score: data.analysis.fairness?.percentage || 0,
            ai_summary: `Trade Analysis: ${data.analysis.fairness?.verdict || 'Unknown'}`,
            key_factors: data.analysis.insights || [],
            confidence: data.analysis.fairness?.percentage || 0
          });
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

                    <p className="text-sm text-gray-600 mb-3">{rec.trade_rationale}</p>

                    <div className="flex items-center justify-between">
                      <button 
                        className="text-blue-600 hover:text-blue-700 text-sm font-medium"
                        onClick={() => {
                          const recId = `${type}-${index}`;
                          setExpandedRecommendation(expandedRecommendation === recId ? null : recId);
                        }}
                      >
                        {expandedRecommendation === `${type}-${index}` ? 'Hide Details' : 'View Details'}
                      </button>
                      <button className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700">
                        Propose Trade
                      </button>
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

          <div className="flex items-center justify-between pt-4 border-t">
            <div className="flex items-center space-x-2">
              <span className="text-sm text-gray-600">Confidence:</span>
              <span className="text-sm font-medium text-gray-900">
                {tradeEvaluation.confidence.toFixed(0)}%
              </span>
            </div>
            <button className="bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700">
              Propose Trade
            </button>
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
        </div>

        {/* League and Team Selection */}
        <div className="bg-white rounded-lg border p-6 mb-8">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">League</label>
              <select
                value={selectedLeague || ''}
                onChange={(e) => setSelectedLeague(e.target.value ? parseInt(e.target.value) : null)}
                className="w-full p-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="">Select league</option>
                {leagues.map(league => (
                  <option key={league.id} value={league.id}>{league.name}</option>
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