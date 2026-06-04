'use client';

import { useEffect, useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import AppLoading from '@/components/yetai/AppLoading';
import PageHeader from '@/components/yetai/PageHeader';
import { useAuth } from '@/components/Auth';
import {
  Plus,
  Target,
  Layers,
  Save,
  Lock,
  Unlock,
  Crown,
  Trash2,
  Calendar,
  Trophy,
} from 'lucide-react';
import { sportsAPI } from '@/lib/api';
import AdminOwensBets from '@/components/yetai/AdminOwensBets';
import AdminYetaiBetsManage from '@/components/yetai/AdminYetaiBetsManage';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

/** Display label → Odds API sport key for game/prop fetches. */
const ADMIN_BET_SPORT_KEY_MAP: Record<string, string> = {
  NFL: 'americanfootball_nfl',
  NBA: 'basketball_nba',
  WNBA: 'basketball_wnba',
  MLB: 'baseball_mlb',
  NHL: 'icehockey_nhl',
  'NCAA Football': 'americanfootball_ncaaf',
  'NCAA Basketball': 'basketball_ncaab',
  Soccer: 'soccer_epl',
  Tennis: 'tennis_atp',
};

export default function AdminBetEntriesPage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  
  // Form states
  const [betType, setBetType] = useState<'straight' | 'parlay'>('straight');
  const [formData, setFormData] = useState({
    sport: '',
    game: '',
    game_id: '',           // Odds API event ID
    home_team: '',         // Home team name
    away_team: '',         // Away team name
    commence_time: '',     // ISO format timestamp
    bet_type: '',
    pick: '',
    odds: '',
    confidence: 80,
    reasoning: '',
    game_time: '',         // Display format (kept for UI)
    is_premium: true
  });
  
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<{type: 'success' | 'error', text: string} | null>(null);
  
  // Auto-fill states
  const [availableGames, setAvailableGames] = useState<any[]>([]);
  const [loadingGames, setLoadingGames] = useState(false);
  const [selectedGame, setSelectedGame] = useState<any>(null);

  // Player props states
  const [availablePlayerProps, setAvailablePlayerProps] = useState<any[]>([]);
  const [loadingPlayerProps, setLoadingPlayerProps] = useState(false);

  // Parlay states
  const [parlayLegs, setParlayLegs] = useState<any[]>([]);
  const [parlayName, setParlayName] = useState('');
  const [parlayReasoning, setParlayReasoning] = useState('');
  const [parlayConfidence, setParlayConfidence] = useState(80);

  // Featured Games states
  const [activeTab, setActiveTab] = useState<'bets' | 'featured' | 'owens'>('bets');
  const [featuredGames, setFeaturedGames] = useState<any[]>([]);
  const [newFeaturedGame, setNewFeaturedGame] = useState({
    game_id: '',
    home_team: '',
    away_team: '',
    start_time: '',
    sport_key: 'americanfootball_nfl',
    explanation: '',
    admin_notes: ''
  });
  const [isSavingFeatured, setIsSavingFeatured] = useState(false);

  // Game selection states
  const [availableTodaysGames, setAvailableTodaysGames] = useState<any[]>([]);
  const [loadingTodaysGames, setLoadingTodaysGames] = useState(false);
  const [selectedGameForFeatured, setSelectedGameForFeatured] = useState<any>(null);
  const [isCleaningUp, setIsCleaningUp] = useState(false);
  const [betListRefresh, setBetListRefresh] = useState(0);

  useEffect(() => {
    if (!loading && (!isAuthenticated || !user?.is_admin)) {
      router.push('/dashboard');
    }
  }, [isAuthenticated, loading, user, router]);

  // Featured Games Functions
  const loadFeaturedGames = async () => {
    try {
      const response = await fetch(getApiUrl('/api/admin/featured-games'));
      if (response.ok) {
        const data = await response.json();
        setFeaturedGames(data.featured_games || []);
      }
    } catch (error) {
      console.error('Error loading featured games:', error);
      setMessage({ type: 'error', text: 'Failed to load featured games' });
    }
  };

  const saveFeaturedGames = async () => {
    setIsSavingFeatured(true);
    try {
      const updatedGames = [...featuredGames, newFeaturedGame].filter(game =>
        game.game_id && game.home_team && game.away_team
      );

      const response = await fetch(getApiUrl('/api/admin/featured-games'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          featured_games: updatedGames
        })
      });

      if (response.ok) {
        setMessage({ type: 'success', text: 'Featured games updated successfully!' });
        setNewFeaturedGame({
          game_id: '',
          home_team: '',
          away_team: '',
          start_time: '',
          sport_key: 'americanfootball_nfl',
          explanation: '',
          admin_notes: ''
        });
        setSelectedGameForFeatured(null);
        await loadFeaturedGames();
      } else {
        setMessage({ type: 'error', text: 'Failed to save featured games' });
      }
    } catch (error) {
      console.error('Error saving featured games:', error);
      setMessage({ type: 'error', text: 'Failed to save featured games' });
    } finally {
      setIsSavingFeatured(false);
    }
  };

  const removeFeaturedGame = (index: number) => {
    const updated = featuredGames.filter((_, i) => i !== index);
    setFeaturedGames(updated);
  };

  const cleanupExpiredGames = async () => {
    setIsCleaningUp(true);
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(getApiUrl('/api/admin/featured-games/cleanup'), {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      if (response.ok) {
        const data = await response.json();
        setMessage({ type: 'success', text: data.message || 'Expired games cleaned up successfully!' });
        await loadFeaturedGames(); // Refresh the list
      } else {
        const errorData = await response.json();
        setMessage({ type: 'error', text: errorData.message || 'Failed to cleanup expired games' });
      }
    } catch (error) {
      console.error('Error cleaning up expired games:', error);
      setMessage({ type: 'error', text: 'Failed to cleanup expired games' });
    } finally {
      setIsCleaningUp(false);
    }
  };

  // Load featured games when tab switches
  useEffect(() => {
    if (activeTab === 'featured') {
      loadFeaturedGames();
      loadTodaysGames();
    }
  }, [activeTab]);

  // Load today's games from all sports
  const loadTodaysGames = async () => {
    setLoadingTodaysGames(true);
    try {
      const sports = [
        'americanfootball_nfl',
        'basketball_nba',
        'basketball_wnba',
        'baseball_mlb',
        'icehockey_nhl',
        'soccer_epl',
      ];
      const allGames: any[] = [];

      for (const sport of sports) {
        try {
          const result = await sportsAPI.getOdds(sport);
          if (result.status === 'success' && result.games) {
            // Add sport info to each game and filter for today's games
            const today = new Date();
            const todaysGames = result.games
              .filter((game: any) => {
                const gameDate = new Date(game.commence_time);
                return gameDate.toDateString() === today.toDateString();
              })
              .map((game: any) => ({
                ...game,
                sport_key: sport,
                sport_name: sport.replace('_', ' ').toUpperCase()
              }));
            allGames.push(...todaysGames);
          }
        } catch (error) {
          console.warn(`Failed to load games for ${sport}:`, error);
        }
      }

      // Sort by start time
      allGames.sort((a, b) => new Date(a.commence_time).getTime() - new Date(b.commence_time).getTime());
      setAvailableTodaysGames(allGames);
    } catch (error) {
      console.error('Error loading today\'s games:', error);
      setMessage({ type: 'error', text: 'Failed to load today\'s games' });
    } finally {
      setLoadingTodaysGames(false);
    }
  };

  // Handle game selection for featured games
  const handleGameSelectionForFeatured = (gameId: string) => {
    const game = availableTodaysGames.find(g => g.id === gameId);
    if (!game) return;

    setSelectedGameForFeatured(game);

    // Auto-fill the form with game details
    setNewFeaturedGame({
      game_id: game.id,
      home_team: game.home_team,
      away_team: game.away_team,
      start_time: new Date(game.commence_time).toISOString().slice(0, 16), // Format for datetime-local input
      sport_key: game.sport_key,
      explanation: '',
      admin_notes: ''
    });
  };

  if (loading) {
    return (
      <Layout requiresAuth fullWidth>
        <AppLoading label="Loading admin…" />
      </Layout>
    );
  }

  if (!isAuthenticated || !user?.is_admin) {
    return null;
  }

  // Parlay Management Functions
  const addLegToParlay = () => {
    if (!formData.game || !formData.bet_type || !formData.pick || !formData.odds) {
      setMessage({ type: 'error', text: 'Please fill out all bet fields before adding to parlay' });
      return;
    }

    const newLeg = {
      sport: formData.sport,
      game: formData.game,
      game_id: formData.game_id,
      home_team: formData.home_team,
      away_team: formData.away_team,
      commence_time: formData.commence_time,
      bet_type: formData.bet_type,
      pick: formData.pick,
      odds: formData.odds,
      game_time: formData.game_time,
      confidence: formData.confidence,
      reasoning: formData.reasoning,
      is_premium: formData.is_premium
    };

    setParlayLegs([...parlayLegs, newLeg]);

    // Reset form for next leg
    setFormData({
      sport: '',
      game: '',
      game_id: '',
      home_team: '',
      away_team: '',
      commence_time: '',
      bet_type: '',
      pick: '',
      odds: '',
      confidence: 80,
      reasoning: '',
      game_time: '',
      is_premium: true
    });
    setSelectedGame(null);
    setAvailableGames([]);
    setAvailablePlayerProps([]);

    setMessage({ type: 'success', text: `Leg ${parlayLegs.length + 1} added to parlay!` });
  };

  const removeLegFromParlay = (index: number) => {
    setParlayLegs(parlayLegs.filter((_, i) => i !== index));
    setMessage({ type: 'success', text: 'Leg removed from parlay' });
  };

  const calculateParlayOdds = (legs: any[]): string => {
    if (legs.length === 0) return '+0';

    let decimalOdds = 1;
    for (const leg of legs) {
      const oddsValue = parseInt(leg.odds.replace('+', '').replace('-', ''));
      if (leg.odds.startsWith('+')) {
        decimalOdds *= (1 + oddsValue / 100);
      } else {
        decimalOdds *= (1 + 100 / oddsValue);
      }
    }

    const americanOdds = Math.round((decimalOdds - 1) * 100);
    return americanOdds > 0 ? `+${americanOdds}` : `${americanOdds}`;
  };

  const handleSubmitParlay = async () => {
    if (parlayLegs.length < 2) {
      setMessage({ type: 'error', text: 'Parlay must have at least 2 legs' });
      return;
    }

    if (!parlayName || !parlayReasoning) {
      setMessage({ type: 'error', text: 'Please provide parlay name and reasoning' });
      return;
    }

    setIsSubmitting(true);
    setMessage(null);

    try {
      const token = localStorage.getItem('auth_token');
      const totalOdds = calculateParlayOdds(parlayLegs);

      const response = await fetch(getApiUrl('/api/admin/yetai-parlays'), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: parlayName,
          legs: parlayLegs,
          total_odds: totalOdds,
          confidence: parlayConfidence,
          reasoning: parlayReasoning,
          is_premium: true
        })
      });

      if (response.ok) {
        setMessage({ type: 'success', text: 'Parlay created successfully!' });
        setBetListRefresh((n) => n + 1);
        // Reset parlay
        setParlayLegs([]);
        setParlayName('');
        setParlayReasoning('');
        setParlayConfidence(80);
      } else {
        const error = await response.json();
        setMessage({ type: 'error', text: error.detail || 'Failed to create parlay' });
      }
    } catch (error) {
      console.error('Error creating parlay:', error);
      setMessage({ type: 'error', text: 'Network error. Please try again.' });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmitBet = async () => {
    setIsSubmitting(true);
    setMessage(null);
    
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(getApiUrl('/api/admin/yetai-bets'), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          ...formData,
          bet_type: formData.bet_type.toLowerCase()
        })
      });
      
      if (response.ok) {
        setMessage({ type: 'success', text: 'Bet created successfully!' });
        setBetListRefresh((n) => n + 1);
        // Reset form
        setFormData({
          sport: '',
          game: '',
          game_id: '',
          home_team: '',
          away_team: '',
          commence_time: '',
          bet_type: '',
          pick: '',
          odds: '',
          confidence: 80,
          reasoning: '',
          game_time: '',
          is_premium: true
        });
        setSelectedGame(null);
        setAvailableGames([]);
      } else {
        const error = await response.json();
        setMessage({ type: 'error', text: error.detail || 'Failed to create bet' });
      }
    } catch (error) {
      console.error('Error creating bet:', error);
      setMessage({ type: 'error', text: 'Network error occurred' });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Fetch games when sport is selected
  const handleSportChange = async (selectedSport: string) => {
    setFormData({
      ...formData,
      sport: selectedSport,
      game: '',
      game_id: '',
      home_team: '',
      away_team: '',
      commence_time: '',
      bet_type: '',
      pick: '',
      odds: '',
      game_time: ''
    });
    setSelectedGame(null);
    setAvailableGames([]);
    
    if (!selectedSport) return;
    
    setLoadingGames(true);
    try {
      const sportKey = ADMIN_BET_SPORT_KEY_MAP[selectedSport];
      if (!sportKey) {
        console.warn('Unsupported sport:', selectedSport);
        return;
      }
      
      const result = await sportsAPI.getOdds(sportKey);
      if (result.status === 'success' && result.games) {
        setAvailableGames(result.games);
      } else if (result.status === 'error') {
        const detail =
          (result as { message?: string }).message ||
          (result as { detail?: string }).detail ||
          'Odds API returned no games';
        setMessage({ type: 'error', text: `${selectedSport}: ${detail}` });
        setAvailableGames([]);
      }
    } catch (error) {
      console.error('Error fetching games:', error);
      setMessage({ type: 'error', text: 'Failed to fetch games for ' + selectedSport });
    } finally {
      setLoadingGames(false);
    }
  };

  // Handle game selection and auto-fill data
  const handleGameSelection = (gameId: string) => {
    const game = availableGames.find(g => g.id === gameId);
    if (!game) return;

    setSelectedGame(game);
    const gameDisplay = `${game.away_team} @ ${game.home_team}`;

    // Format game time as: MM/DD/YYYY @H:MMPM EST
    const gameDate = new Date(game.commence_time);
    const formattedDate = gameDate.toLocaleDateString('en-US', {
      month: '2-digit',
      day: '2-digit',
      year: 'numeric'
    });
    const formattedTime = gameDate.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short'
    });
    const gameTime = `${formattedDate} @${formattedTime}`;

    setFormData({
      ...formData,
      game: gameDisplay,
      game_id: game.id,                    // Store Odds API event ID
      home_team: game.home_team,           // Store home team
      away_team: game.away_team,           // Store away team
      commence_time: game.commence_time,   // Store ISO timestamp
      game_time: gameTime,
      bet_type: '', // Reset bet type so user can select
      pick: '',
      odds: ''
    });
  };

  // Handle bet type selection - don't auto-populate, let user choose all options
  const handleBetTypeSelection = async (betType: string) => {
    if (!selectedGame) return;

    // Reset pick and odds when bet type changes - user will select from dropdown
    setFormData(prev => ({
      ...prev,
      bet_type: betType,
      pick: '',
      odds: ''
    }));

    // Load player props if Player Props is selected
    if (betType === 'Player Props' && selectedGame) {
      await loadPlayerPropsForGame(selectedGame);
    } else {
      setAvailablePlayerProps([]);
    }
  };

  // Load player props for selected game
  const loadPlayerPropsForGame = async (game: any) => {
    setLoadingPlayerProps(true);
    try {
      const sportKey = ADMIN_BET_SPORT_KEY_MAP[formData.sport] || game.sport_key;
      if (!sportKey) return;

      const result = await sportsAPI.getPlayerProps(sportKey, game.id);

      if (result.status === 'success' && result.data?.markets) {
        // Flatten all markets into a single list of props with market info
        const allProps: any[] = [];
        Object.entries(result.data.markets).forEach(([marketKey, marketData]: [string, any]) => {
          marketData.players?.forEach((player: any) => {
            if (player.over !== null) {
              allProps.push({
                player_name: player.player_name,
                market_key: marketKey,
                market_display: getMarketDisplayName(marketKey),
                line: player.line,
                selection: 'over',
                odds: player.over,
                display: `${player.player_name} over ${player.line} ${getMarketDisplayName(marketKey)}`
              });
            }
            if (player.under !== null) {
              allProps.push({
                player_name: player.player_name,
                market_key: marketKey,
                market_display: getMarketDisplayName(marketKey),
                line: player.line,
                selection: 'under',
                odds: player.under,
                display: `${player.player_name} under ${player.line} ${getMarketDisplayName(marketKey)}`
              });
            }
          });
        });
        setAvailablePlayerProps(allProps);
      }
    } catch (error) {
      console.error('Error loading player props:', error);
      setMessage({ type: 'error', text: 'Failed to load player props' });
    } finally {
      setLoadingPlayerProps(false);
    }
  };

  // Market display names mapping (same as PlayerPropsCard)
  const getMarketDisplayName = (marketKey: string): string => {
    const replacements: Record<string, string> = {
      player_pass_tds: 'Passing TDs',
      player_pass_yds: 'Passing Yards',
      player_rush_yds: 'Rushing Yards',
      player_reception_yds: 'Receiving Yards',
      player_receptions: 'Receptions',
      player_points: 'Points',
      player_rebounds: 'Rebounds',
      player_assists: 'Assists',
      player_threes: '3-Pointers Made',
      player_pitcher_strikeouts: 'Pitcher Strikeouts',
      player_hits: 'Hits',
      player_home_runs: 'Home Runs',
      player_rbis: 'RBIs',
      player_total_bases: 'Total Bases',
      player_goals: 'Goals',
      player_assists_hockey: 'Assists',
      player_points_hockey: 'Points',
      player_shots_on_goal: 'Shots on Goal'
    };
    return replacements[marketKey] || marketKey.replace(/_/g, ' ').replace(/player /g, '');
  };

  // Handle bet option selection (works for all bet types)
  const handleBetOptionSelection = (selectedOption: string) => {
    if (!selectedGame || !selectedOption) return;

    const bookmaker = selectedGame.bookmakers?.[0];
    if (!bookmaker) return;

    let outcome: any = null;
    let formattedPick = selectedOption;

    if (formData.bet_type === 'Spread') {
      const spreadMarket = bookmaker.markets?.find((m: any) => m.key === 'spreads');
      // selectedOption is the team name, find the matching outcome
      outcome = spreadMarket?.outcomes?.find((o: any) => o.name === selectedOption);
      if (outcome) {
        formattedPick = `Spread ${outcome.name} ${outcome.point >= 0 ? '+' : ''}${outcome.point}`;
      }
    } else if (formData.bet_type === 'Moneyline') {
      const moneylineMarket = bookmaker.markets?.find((m: any) => m.key === 'h2h');
      outcome = moneylineMarket?.outcomes?.find((o: any) => o.name === selectedOption);
      if (outcome) {
        formattedPick = `Moneyline ${outcome.name}`;
      }
    } else if (formData.bet_type === 'Total (Over/Under)') {
      const totalMarket = bookmaker.markets?.find((m: any) => m.key === 'totals');
      const overUnder = selectedOption.split(' ')[0]; // 'Over' or 'Under'
      outcome = totalMarket?.outcomes?.find((o: any) => o.name === overUnder);
      if (outcome) {
        formattedPick = `Total ${outcome.name} ${outcome.point}`;
      }
    }
    
    if (outcome) {
      const formattedOdds = outcome.price > 0 ? `+${outcome.price}` : `${outcome.price}`;
      setFormData(prev => ({
        ...prev,
        pick: formattedPick,
        odds: formattedOdds
      }));
    }
  };

  return (
    <Layout requiresAuth fullWidth>
      <PageHeader
        title="Admin Bet Entries"
        subtitle="Create YetAI custom bets, manage featured games, and Owen’s Bets"
      />

      <div className="space-y-6">
        <Link
          href="/admin"
          className="inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Admin
        </Link>

        {/* Message Alert */}
        {message && (
          <div className={`p-4 rounded-lg ${
message.type === 'success' ? 'alert alert-success' : 'alert alert-error'
          }`}>
            {message.text}
          </div>
        )}

        <div className="chip-row admin-tabs">
          <button type="button" onClick={() => setActiveTab('bets')} className={`chip ${activeTab === 'bets' ? 'active' : ''}`}>
            <Plus className="w-4 h-4" />
            YetAI custom bets
          </button>
          <button type="button" onClick={() => setActiveTab('featured')} className={`chip ${activeTab === 'featured' ? 'active' : ''}`}>
            <Crown className="w-4 h-4" />
            Featured Games
          </button>
          <button type="button" onClick={() => setActiveTab('owens')} className={`chip ${activeTab === 'owens' ? 'active' : ''}`}>
            <Plus className="w-4 h-4" />
            Owen&apos;s Bets
          </button>
        </div>

        {activeTab === 'bets' && (
        <>
        <div className="card">
          <h2 className="text-xl font-semibold mb-4 flex items-center">
            <Plus className="w-5 h-5 mr-2" />
            Create New Bet
          </h2>

          {/* Bet Type Selector */}
          <div className="mb-6">
            <label className="block text-sm font-medium muted mb-2">Bet Type</label>
            <div className="flex space-x-4">
              <button
                onClick={() => setBetType('straight')}
                className={`chip ${betType === 'straight' ? 'active' : ''}`}
              >
                <Target className="w-4 h-4 mr-2" />
                Straight Bet
              </button>
              <button
                onClick={() => setBetType('parlay')}
                className={`chip ${betType === 'parlay' ? 'active' : ''}`}
              >
                <Layers className="w-4 h-4 mr-2" />
                Parlay Bet
              </button>
            </div>
          </div>

          {/* Parlay Summary (shown when in parlay mode) */}
          {betType === 'parlay' && parlayLegs.length > 0 && (
            <div className="mb-6 p-4 bg-blue-50 rounded-lg border border-blue-200">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semiboldflex items-center">
                  <Layers className="w-5 h-5 text-blue-600 mr-2" />
                  Parlay Legs ({parlayLegs.length})
                </h3>
                <div className="text-sm font-medium text-blue-600">
                  Combined Odds: {calculateParlayOdds(parlayLegs)}
                </div>
              </div>
              <div className="space-y-2">
                {parlayLegs.map((leg, index) => (
                  <div key={index} className="flex items-center justify-between bg-white p-3 rounded border border-[var(--border)]">
                    <div className="flex-1">
                      <div className="font-medium ">{leg.pick}</div>
                      <div className="text-sm muted">{leg.game} • {leg.odds}</div>
                    </div>
                    <button
                      onClick={() => removeLegFromParlay(index)}
                      className="ml-3 text-red-600 hover:text-red-800"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Bet Form Fields */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium muted mb-2">Sport</label>
              <select
                value={formData.sport}
                onChange={(e) => handleSportChange(e.target.value)}
                className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="">Select Sport</option>
                <option value="NFL">NFL</option>
                <option value="NBA">NBA</option>
                <option value="WNBA">WNBA</option>
                <option value="MLB">MLB</option>
                <option value="NHL">NHL</option>
                <option value="NCAA Football">NCAA Football</option>
                <option value="NCAA Basketball">NCAA Basketball</option>
                <option value="Soccer">Soccer</option>
                <option value="Tennis">Tennis</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium muted mb-2">
                Game {loadingGames && <span className="text-xs text-blue-600">(Loading...)</span>}
              </label>
              {availableGames.length > 0 ? (
                <select
                  value={selectedGame?.id || ''}
                  onChange={(e) => handleGameSelection(e.target.value)}
                  className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                >
                  <option value="">Select Game</option>
                  {availableGames.map((game) => (
                    <option key={game.id} value={game.id}>
                      {game.away_team} @ {game.home_team} ({new Date(game.commence_time).toLocaleDateString()})
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={formData.game}
                  onChange={(e) => setFormData({...formData, game: e.target.value})}
                  placeholder={formData.sport ? "Loading games..." : "Select a sport first"}
                  disabled={loadingGames || !formData.sport}
                  className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100"
                />
              )}
            </div>

            <div>
              <label className="block text-sm font-medium muted mb-2">Bet Type</label>
              <select
                value={formData.bet_type}
                onChange={(e) => handleBetTypeSelection(e.target.value)}
                disabled={!selectedGame}
                className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100"
              >
                <option value="">{selectedGame ? "Select Bet Type" : "Select a game first"}</option>
                <option value="Spread">Spread</option>
                <option value="Moneyline">Moneyline</option>
                <option value="Total (Over/Under)">Total (Over/Under)</option>
                <option value="Puck Line">Puck Line</option>
                <option value="Run Line">Run Line</option>
                <option value="1st Half">1st Half</option>
                <option value="1st Quarter">1st Quarter</option>
                <option value="Player Props">Player Props</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium muted mb-2">
                Pick {formData.bet_type === 'Player Props' && loadingPlayerProps && <span className="text-xs text-blue-600">(Loading props...)</span>}
              </label>
              {formData.bet_type === 'Player Props' ? (
                // Dropdown for player props from API
                availablePlayerProps.length > 0 ? (
                  <select
                    value={formData.pick}
                    onChange={(e) => {
                      const selectedProp = availablePlayerProps.find(p => p.display === e.target.value);
                      if (selectedProp) {
                        setFormData({
                          ...formData,
                          pick: selectedProp.display,
                          odds: selectedProp.odds > 0 ? `+${selectedProp.odds}` : `${selectedProp.odds}`
                        });
                      }
                    }}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">Select a player prop...</option>
                    {availablePlayerProps.map((prop, index) => (
                      <option key={index} value={prop.display}>
                        {prop.display} ({prop.odds > 0 ? '+' : ''}{prop.odds})
                      </option>
                    ))}
                  </select>
                ) : loadingPlayerProps ? (
                  <div className="w-full px-3 py-2 border border-[var(--border)] rounded-lg bg-gray-50 dim flex items-center">
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600 mr-2"></div>
                    Loading available player props...
                  </div>
                ) : (
                  <div className="w-full px-3 py-2 border border-[var(--border)] rounded-lg bg-gray-50 dim">
                    No player props available for this game
                  </div>
                )
              ) : formData.bet_type && selectedGame ? (
                <select
                  value={(() => {
                    // Extract the key part from formatted pick for dropdown value matching
                    if (!formData.pick) return '';
                    if (formData.bet_type === 'Spread') {
                      // Extract team name from "Spread TeamName +/-X.X" 
                      const match = formData.pick.match(/Spread (.+?) [+-]/);
                      return match ? match[1] : '';
                    } else if (formData.bet_type === 'Moneyline') {
                      // Extract team name from "Moneyline TeamName"
                      return formData.pick.replace('Moneyline ', '');
                    } else if (formData.bet_type === 'Total (Over/Under)') {
                      // Extract "Over/Under X.X" from "Total Over/Under X.X"
                      return formData.pick.replace('Total ', '');
                    }
                    return formData.pick;
                  })()}
                  onChange={(e) => handleBetOptionSelection(e.target.value)}
                  className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                >
                  <option value="">Select {formData.bet_type.toLowerCase()} option</option>
                  {formData.bet_type === 'Spread' && selectedGame.bookmakers?.[0]?.markets?.find((m: any) => m.key === 'spreads')?.outcomes?.map((outcome: any) => {
                    const spreadText = `${outcome.name} ${outcome.point >= 0 ? '+' : ''}${outcome.point}`;
                    return (
                      <option key={outcome.name} value={outcome.name}>
                        Spread: {spreadText} ({outcome.price > 0 ? '+' : ''}{outcome.price})
                      </option>
                    );
                  })}
                  {formData.bet_type === 'Moneyline' && selectedGame.bookmakers?.[0]?.markets?.find((m: any) => m.key === 'h2h')?.outcomes?.map((outcome: any) => (
                    <option key={outcome.name} value={outcome.name}>
                      Moneyline: {outcome.name} ({outcome.price > 0 ? '+' : ''}{outcome.price})
                    </option>
                  ))}
                  {formData.bet_type === 'Total (Over/Under)' && selectedGame.bookmakers?.[0]?.markets?.find((m: any) => m.key === 'totals')?.outcomes?.map((outcome: any) => (
                    <option key={outcome.name} value={`${outcome.name} ${outcome.point}`}>
                      Total: {outcome.name} {outcome.point} ({outcome.price > 0 ? '+' : ''}{outcome.price})
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={formData.pick}
                  onChange={(e) => setFormData({...formData, pick: e.target.value})}
                  placeholder={formData.bet_type ? "Select a bet type first" : "e.g., Chiefs -3.5, Over 228.5"}
                  disabled={!formData.bet_type}
                  className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100"
                />
              )}
            </div>

            <div>
              <label className="block text-sm font-medium muted mb-2">Odds</label>
              <input
                type="text"
                value={formData.odds}
                onChange={(e) => setFormData({...formData, odds: e.target.value})}
                placeholder="e.g., -110, +150"
                className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium muted mb-2">Game Time</label>
              <input
                type="text"
                value={formData.game_time}
                onChange={(e) => setFormData({...formData, game_time: e.target.value})}
                placeholder="e.g., 8:20 PM EST"
                className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </div>

          {/* Confidence and Access Level */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium muted mb-2">
                Confidence Level: {formData.confidence}%
              </label>
              <input
                type="range"
                min="50"
                max="100"
                value={formData.confidence}
                onChange={(e) => setFormData({...formData, confidence: parseInt(e.target.value)})}
                className="w-full"
              />
              <div className="flex justify-between text-xs dim mt-1">
                <span>50%</span>
                <span>100%</span>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium muted mb-2">Access Level</label>
              <div className="flex items-center space-x-4">
                <button
                  onClick={() => setFormData({...formData, is_premium: false})}
                  className="flex items-center px-4 py-2 rounded-lg font-medium transition-colors border-2"
                  style={{
                    backgroundColor: !formData.is_premium ? '#059669' : '#f9fafb',
                    color: !formData.is_premium ? 'white' : '#6b7280',
                    borderColor: !formData.is_premium ? '#059669' : '#d1d5db',
                    fontWeight: !formData.is_premium ? 'bold' : 'normal'
                  }}
                >
                  <Unlock className="w-4 h-4 mr-2" style={{ color: !formData.is_premium ? 'white' : '#6b7280' }} />
                  Free
                </button>
                <button
                  onClick={() => setFormData({...formData, is_premium: true})}
                  className="flex items-center px-4 py-2 rounded-lg font-medium transition-colors border-2"
                  style={{
                    backgroundColor: formData.is_premium ? '#d97706' : '#f9fafb',
                    color: formData.is_premium ? 'white' : '#6b7280',
                    borderColor: formData.is_premium ? '#d97706' : '#d1d5db',
                    fontWeight: formData.is_premium ? 'bold' : 'normal'
                  }}
                >
                  <Lock className="w-4 h-4 mr-2" style={{ color: formData.is_premium ? 'white' : '#6b7280' }} />
                  Premium
                </button>
              </div>
            </div>
          </div>

          {/* Reasoning - different for parlay vs straight */}
          {betType === 'straight' ? (
            <div className="mb-6">
              <label className="block text-sm font-medium muted mb-2">Reasoning</label>
              <textarea
                value={formData.reasoning}
                onChange={(e) => setFormData({...formData, reasoning: e.target.value})}
                placeholder="Explain your analysis and reasoning for this bet..."
                rows={4}
                className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          ) : (
            <div className="mb-6 space-y-4">
              <div>
                <label className="block text-sm font-medium muted mb-2">Parlay Name</label>
                <input
                  type="text"
                  value={parlayName}
                  onChange={(e) => setParlayName(e.target.value)}
                  placeholder="e.g., 3-Team NFL Sunday Parlay"
                  className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium muted mb-2">Parlay Reasoning</label>
                <textarea
                  value={parlayReasoning}
                  onChange={(e) => setParlayReasoning(e.target.value)}
                  placeholder="Explain your overall parlay strategy and why these legs work together..."
                  rows={4}
                  className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium muted mb-2">
                  Parlay Confidence: {parlayConfidence}%
                </label>
                <input
                  type="range"
                  min="50"
                  max="100"
                  value={parlayConfidence}
                  onChange={(e) => setParlayConfidence(Number(e.target.value))}
                  className="w-full"
                />
              </div>
            </div>
          )}

          {/* Submit Buttons - different for parlay vs straight */}
          {betType === 'straight' ? (
            <button
              onClick={handleSubmitBet}
              disabled={isSubmitting || !formData.sport || !formData.game || !formData.bet_type || !formData.pick || !formData.odds || !formData.reasoning || !formData.game_time}
              className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center justify-center"
            >
              {isSubmitting ? (
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
              ) : (
                <>
                  <Save className="w-5 h-5 mr-2" />
                  Create Bet
                </>
              )}
            </button>
          ) : (
            <div className="space-y-3">
              <button
                onClick={addLegToParlay}
                disabled={!formData.sport || !formData.game || !formData.bet_type || !formData.pick || !formData.odds || !formData.game_time}
                className="w-full bg-green-600 text-white py-3 rounded-lg font-medium hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center justify-center"
              >
                <Plus className="w-5 h-5 mr-2" />
                Add Leg to Parlay
              </button>
              <button
                onClick={handleSubmitParlay}
                disabled={isSubmitting || parlayLegs.length < 2 || !parlayName || !parlayReasoning}
                className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center justify-center"
              >
                {isSubmitting ? (
                  <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                ) : (
                  <>
                    <Save className="w-5 h-5 mr-2" />
                    Create Parlay ({parlayLegs.length} legs)
                  </>
                )}
              </button>
            </div>
          )}
        </div>

        <AdminYetaiBetsManage refreshToken={betListRefresh} />
        </>
        )}

        {activeTab === 'featured' && (
          <div className="card">
            <h2 className="text-xl font-semibold mb-4 flex items-center">
              <Crown className="w-5 h-5 mr-2 text-yellow-600" />
              Manage Featured Games
            </h2>
            <p className="muted mb-6">
              Create curated featured games with professional explanations that will be highlighted on the dashboard.
            </p>

            {/* Add New Featured Game Form */}
            <div className="card card-tight p-6 mb-6">
              <h3 className="text-lg font-medium mb-4 flex items-center">
                <Plus className="w-4 h-4 mr-2" />
                Add New Featured Game
              </h3>

              {/* Game Selector */}
              <div className="mb-6">
                <label className="block text-sm font-medium muted mb-2">
                  Select Game from Today's Schedule
                  {loadingTodaysGames && <span className="text-xs text-blue-600 ml-2">(Loading...)</span>}
                </label>

                {availableTodaysGames.length > 0 ? (
                  <select
                    value={selectedGameForFeatured?.id || ''}
                    onChange={(e) => handleGameSelectionForFeatured(e.target.value)}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">Select a game from today's schedule...</option>
                    {availableTodaysGames.map((game) => (
                      <option key={game.id} value={game.id}>
                        {game.sport_name} - {game.away_team} @ {game.home_team} ({new Date(game.commence_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})
                      </option>
                    ))}
                  </select>
                ) : loadingTodaysGames ? (
                  <div className="flex items-center justify-center py-4 dim">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600 mr-2"></div>
                    Loading today's games...
                  </div>
                ) : (
                  <div className="text-center py-4 dim bg-gray-100 rounded-lg">
                    <Trophy className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                    <p>No games found for today</p>
                    <p className="text-sm">Games typically load closer to game day</p>
                  </div>
                )}
              </div>

              {/* Auto-filled Game Details (Read-only) */}
              {selectedGameForFeatured && (
                <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <h4 className="text-sm font-medium text-blue-900 mb-3 flex items-center">
                    <Crown className="w-4 h-4 mr-2" />
                    Selected Game Details (Auto-filled)
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                    <div>
                      <span className="font-medium text-blue-800">Game ID:</span>
                      <span className="ml-2 text-blue-700">{selectedGameForFeatured.id}</span>
                    </div>
                    <div>
                      <span className="font-medium text-blue-800">Sport:</span>
                      <span className="ml-2 text-blue-700">{selectedGameForFeatured.sport_name}</span>
                    </div>
                    <div>
                      <span className="font-medium text-blue-800">Matchup:</span>
                      <span className="ml-2 text-blue-700">{selectedGameForFeatured.away_team} @ {selectedGameForFeatured.home_team}</span>
                    </div>
                    <div>
                      <span className="font-medium text-blue-800">Start Time:</span>
                      <span className="ml-2 text-blue-700">{new Date(selectedGameForFeatured.commence_time).toLocaleString()}</span>
                    </div>
                  </div>
                </div>
              )}

              <div className="mb-4">
                <label className="block text-sm font-medium muted mb-2">Professional Explanation</label>
                <textarea
                  value={newFeaturedGame.explanation}
                  onChange={(e) => setNewFeaturedGame({...newFeaturedGame, explanation: e.target.value})}
                  placeholder="Provide a detailed analysis explaining why this game is featured. Include key factors, player insights, statistical analysis, etc."
                  rows={4}
                  className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>

              <div className="mb-4">
                <label className="block text-sm font-medium muted mb-2">Admin Notes (Internal)</label>
                <textarea
                  value={newFeaturedGame.admin_notes}
                  onChange={(e) => setNewFeaturedGame({...newFeaturedGame, admin_notes: e.target.value})}
                  placeholder="Internal notes for other admins (not shown to users)"
                  rows={2}
                  className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
            </div>

            {/* Current Featured Games List */}
            <div className="mb-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-mediumflex items-center">
                  <Crown className="w-4 h-4 mr-2 text-yellow-600" />
                  Current Featured Games ({featuredGames.length})
                </h3>
                <button
                  onClick={cleanupExpiredGames}
                  disabled={isCleaningUp}
                  className="bg-red-600 text-white px-4 py-2 rounded-lg font-medium hover:bg-red-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center"
                  title="Remove games that have already ended"
                >
                  {isCleaningUp ? (
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                  ) : (
                    <Trash2 className="w-4 h-4 mr-2" />
                  )}
                  {isCleaningUp ? 'Cleaning...' : 'Clean Expired'}
                </button>
              </div>

              {featuredGames.length === 0 ? (
                <div className="text-center py-8 dim">
                  <Trophy className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                  <p>No featured games configured</p>
                  <p className="text-sm">Add your first featured game above</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {featuredGames.map((game, index) => (
                    <div key={index} className="border border-[var(--border)] rounded-lg p-4 bg-gray-50">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center mb-2">
                            <Crown className="w-4 h-4 text-yellow-600 mr-2" />
                            <h4 className="font-semibold ">
                              {game.away_team} @ {game.home_team}
                            </h4>
                            <span className="ml-2 px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded">
                              {game.sport_key?.replace('_', ' ').toUpperCase() || 'Unknown Sport'}
                            </span>
                          </div>

                          {game.start_time && (
                            <div className="flex items-center text-sm muted mb-2">
                              <Calendar className="w-4 h-4 mr-1" />
                              {new Date(game.start_time).toLocaleString()}
                            </div>
                          )}

                          <div className="text-sm muted mb-2">
                            <strong>Game ID:</strong> {game.game_id}
                          </div>

                          {game.explanation && (
                            <div className="bg-white p-3 rounded border border-[var(--border)]">
                              <p className="text-sm ">
                                <strong>Explanation:</strong> {game.explanation}
                              </p>
                            </div>
                          )}

                          {game.admin_notes && (
                            <div className="mt-2 bg-yellow-50 p-2 rounded border border-yellow-200">
                              <p className="text-xs text-yellow-800">
                                <strong>Admin Notes:</strong> {game.admin_notes}
                              </p>
                            </div>
                          )}
                        </div>

                        <button
                          onClick={() => removeFeaturedGame(index)}
                          className="ml-4 p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                          title="Remove featured game"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Save Button */}
            <div className="flex justify-end">
              <button
                onClick={saveFeaturedGames}
                disabled={isSavingFeatured || !selectedGameForFeatured || !newFeaturedGame.explanation.trim()}
                className="bg-blue-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center"
              >
                {isSavingFeatured ? (
                  <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                ) : (
                  <Save className="w-5 h-5 mr-2" />
                )}
                {isSavingFeatured ? 'Saving...' : 'Save Featured Game'}
              </button>
            </div>

            {!selectedGameForFeatured && (
              <p className="text-sm muted text-right mt-2">
                Select a game from today's schedule to continue
              </p>
            )}
            {selectedGameForFeatured && !newFeaturedGame.explanation.trim() && (
              <p className="text-sm muted text-right mt-2">
                Add a professional explanation to save the featured game
              </p>
            )}
          </div>
        )}

        {activeTab === 'owens' && <AdminOwensBets />}
      </div>
    </Layout>
  );
}