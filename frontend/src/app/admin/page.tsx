'use client';

import { useEffect, useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import {
  Shield,
  Plus,
  Target,
  Layers,
  Clock,
  Save,
  Lock,
  Unlock,
  Users,
  Crown,
  Trash2,
  Calendar,
  Trophy
} from 'lucide-react';
import { sportsAPI } from '@/lib/api';


export default function AdminPage() {
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
  
  // Bet Verification states
  const [showVerificationPanel, setShowVerificationPanel] = useState(false);
  const [verificationStats, setVerificationStats] = useState<any>(null);
  const [isVerifying, setIsVerifying] = useState(false);
  
  // Auto-fill states
  const [availableGames, setAvailableGames] = useState<any[]>([]);
  const [loadingGames, setLoadingGames] = useState(false);
  const [selectedGame, setSelectedGame] = useState<any>(null);

  // Featured Games states
  const [activeTab, setActiveTab] = useState<'bets' | 'featured'>('bets');
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

  useEffect(() => {
    if (!loading && (!isAuthenticated || !user?.is_admin)) {
      router.push('/dashboard');
    }
  }, [isAuthenticated, loading, user, router]);

  // Load verification stats when panel is opened - must be at top level
  useEffect(() => {
    if (showVerificationPanel && !verificationStats) {
      const fetchVerificationStats = async () => {
        try {
          const token = localStorage.getItem('auth_token');
          const response = await fetch(getApiUrl('/api/admin/bets/verification/stats'), {
            method: 'GET',
            headers: {
              'Authorization': `Bearer ${token}`,
              'Content-Type': 'application/json'
            }
          });
          
          if (response.ok) {
            const data = await response.json();
            setVerificationStats(data.data || data);
          } else {
            setMessage({ type: 'error', text: 'Failed to fetch verification stats' });
          }
        } catch (error) {
          console.error('Error fetching verification stats:', error);
          setMessage({ type: 'error', text: 'Failed to fetch verification stats' });
        }
      };
      fetchVerificationStats();
    }
  }, [showVerificationPanel, verificationStats]);

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
      const sports = ['americanfootball_nfl', 'basketball_nba', 'baseball_mlb', 'icehockey_nhl', 'soccer_epl'];
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
      <Layout>
        <div className="min-h-screen flex items-center justify-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
      </Layout>
    );
  }

  if (!isAuthenticated || !user?.is_admin) {
    return null;
  }

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
      // Map sport names to API keys
      const sportKeyMap: {[key: string]: string} = {
        'NFL': 'americanfootball_nfl',
        'NBA': 'basketball_nba',
        'MLB': 'baseball_mlb',
        'NHL': 'icehockey_nhl',
        'NCAA Football': 'americanfootball_ncaaf',
        'NCAA Basketball': 'basketball_ncaab',
        'Soccer': 'soccer_epl',
        'Tennis': 'tennis_atp'
      };
      
      const sportKey = sportKeyMap[selectedSport];
      if (!sportKey) {
        console.warn('Unsupported sport:', selectedSport);
        return;
      }
      
      const result = await sportsAPI.getOdds(sportKey);
      if (result.status === 'success' && result.games) {
        setAvailableGames(result.games);
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
  const handleBetTypeSelection = (betType: string) => {
    if (!selectedGame) return;
    
    // Reset pick and odds when bet type changes - user will select from dropdown
    setFormData(prev => ({
      ...prev,
      bet_type: betType,
      pick: '',
      odds: ''
    }));
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

  // Bet Verification Functions
  const fetchVerificationStats = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(getApiUrl('/api/admin/bets/verification/stats'), {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });
      
      if (response.ok) {
        const data = await response.json();
        setVerificationStats(data.data || data);
      } else {
        setMessage({ type: 'error', text: 'Failed to fetch verification stats' });
      }
    } catch (error) {
      console.error('Error fetching verification stats:', error);
      setMessage({ type: 'error', text: 'Failed to fetch verification stats' });
    }
  };

  const triggerVerificationInternal = async (retryCount = 0) => {
    setIsVerifying(true);
    const maxRetries = 2;

    try {
      const token = localStorage.getItem('auth_token');
      console.log('Triggering verification with URL:', getApiUrl('/api/admin/bets/verify'));

      // Add a small delay for retries to handle potential rate limiting or temporary issues
      if (retryCount > 0) {
        await new Promise(resolve => setTimeout(resolve, 1000 * retryCount));
      }

      const response = await fetch(getApiUrl('/api/admin/bets/verify'), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({})
      });

      console.log('Verification response status:', response.status, response.statusText);

      if (response.ok) {
        const data = await response.json();
        console.log('Verification successful:', data);
        setMessage({ type: 'success', text: `Verification completed: ${data.result?.message || 'Success'}` });
        // Refresh stats by setting verificationStats to null to trigger re-fetch
        setVerificationStats(null);
      } else if (response.status >= 500 && retryCount < maxRetries) {
        // Retry on server errors (5xx)
        console.log(`Server error ${response.status}, retrying... (attempt ${retryCount + 1}/${maxRetries + 1})`);
        return triggerVerificationInternal(retryCount + 1);
      } else {
        let errorText = `HTTP ${response.status}: ${response.statusText}`;
        try {
          const errorData = await response.json();
          errorText = `${errorText} - ${errorData.detail || 'Unknown error'}`;
        } catch (jsonError) {
          console.error('Failed to parse error response as JSON:', jsonError);
          errorText = `${errorText} - Unable to parse error response`;
        }
        console.error('Verification failed:', errorText);
        setMessage({ type: 'error', text: `Verification failed: ${errorText}` });
      }
    } catch (error) {
      console.error('Error triggering verification:', error);

      // Retry on network errors if we haven't exceeded max retries
      if (retryCount < maxRetries && (error instanceof TypeError || (error instanceof Error && error.message.includes('Failed to fetch')))) {
        console.log(`Network error, retrying... (attempt ${retryCount + 1}/${maxRetries + 1})`);
        return triggerVerificationInternal(retryCount + 1);
      }

      const errorMsg = error instanceof Error ? error.message : 'Network or connection error';
      setMessage({
        type: 'error',
        text: `Failed to trigger bet verification: ${errorMsg}. Check console for details.`
      });
    } finally {
      if (retryCount === 0) { // Only reset loading state on the final attempt
        setIsVerifying(false);
      }
    }
  };

  const triggerVerification = () => {
    triggerVerificationInternal();
  };

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center">
              <Shield className="w-8 h-8 text-red-600 mr-3" />
              Admin Dashboard
            </h1>
            <p className="text-gray-600 mt-1">
              Create and manage YetAI Bets for all users
            </p>
          </div>
        </div>
        
        {/* Quick Actions */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <button
            onClick={() => router.push('/admin/users')}
            className="bg-white rounded-lg border border-gray-200 p-6 hover:border-blue-500 transition-colors group"
          >
            <div className="flex items-center">
              <Users className="w-8 h-8 text-blue-600 mr-4" />
              <div className="text-left">
                <h3 className="text-lg font-semibold text-gray-900 group-hover:text-blue-600">
                  User Management
                </h3>
                <p className="text-sm text-gray-600">
                  View, edit, and manage all user accounts
                </p>
              </div>
            </div>
          </button>
          
          <button
            onClick={() => setShowVerificationPanel(true)}
            className="bg-white rounded-lg border border-gray-200 p-6 hover:border-green-500 transition-colors group"
          >
            <div className="flex items-center">
              <Target className="w-8 h-8 text-green-600 mr-4" />
              <div className="text-left">
                <h3 className="text-lg font-semibold text-gray-900 group-hover:text-green-600">
                  Bet Verification
                </h3>
                <p className="text-sm text-gray-600">
                  Monitor and control automatic bet verification
                </p>
              </div>
            </div>
          </button>
        </div>
        
        {/* Message Alert */}
        {message && (
          <div className={`p-4 rounded-lg ${
            message.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
          }`}>
            {message.text}
          </div>
        )}

        {/* Tab Navigation */}
        <div className="flex space-x-1 bg-gray-100 p-1 rounded-lg mb-6">
          <button
            onClick={() => setActiveTab('bets')}
            className={`flex-1 flex items-center justify-center py-2 px-4 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'bets'
                ? 'bg-white text-blue-600 shadow-sm'
                : 'text-gray-700 hover:text-gray-900'
            }`}
          >
            <Plus className="w-4 h-4 mr-2" />
            Create Bets
          </button>
          <button
            onClick={() => setActiveTab('featured')}
            className={`flex-1 flex items-center justify-center py-2 px-4 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'featured'
                ? 'bg-white text-blue-600 shadow-sm'
                : 'text-gray-700 hover:text-gray-900'
            }`}
          >
            <Crown className="w-4 h-4 mr-2" />
            Featured Games
          </button>
        </div>

        {activeTab === 'bets' && (
          <>
            {/* Bet Constructor */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
            <Plus className="w-5 h-5 mr-2" />
            Create New Bet
          </h2>

          {/* Bet Type Selector */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-2">Bet Type</label>
            <div className="flex space-x-4">
              <button
                onClick={() => setBetType('straight')}
                className={`flex items-center px-4 py-2 rounded-lg font-medium transition-colors ${
                  betType === 'straight'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                <Target className="w-4 h-4 mr-2" />
                Straight Bet
              </button>
              <button
                onClick={() => setBetType('parlay')}
                className={`flex items-center px-4 py-2 rounded-lg font-medium transition-colors ${
                  betType === 'parlay'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                <Layers className="w-4 h-4 mr-2" />
                Parlay Bet (Coming Soon)
              </button>
            </div>
          </div>

          {/* Bet Form Fields */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Sport</label>
              <select
                value={formData.sport}
                onChange={(e) => handleSportChange(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="">Select Sport</option>
                <option value="NFL">NFL</option>
                <option value="NBA">NBA</option>
                <option value="MLB">MLB</option>
                <option value="NHL">NHL</option>
                <option value="NCAA Football">NCAA Football</option>
                <option value="NCAA Basketball">NCAA Basketball</option>
                <option value="Soccer">Soccer</option>
                <option value="Tennis">Tennis</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Game {loadingGames && <span className="text-xs text-blue-600">(Loading...)</span>}
              </label>
              {availableGames.length > 0 ? (
                <select
                  value={selectedGame?.id || ''}
                  onChange={(e) => handleGameSelection(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
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
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100"
                />
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Bet Type</label>
              <select
                value={formData.bet_type}
                onChange={(e) => handleBetTypeSelection(e.target.value)}
                disabled={!selectedGame}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100"
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
              <label className="block text-sm font-medium text-gray-700 mb-2">Pick</label>
              {formData.bet_type && selectedGame ? (
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
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
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
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100"
                />
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Odds</label>
              <input
                type="text"
                value={formData.odds}
                onChange={(e) => setFormData({...formData, odds: e.target.value})}
                placeholder="e.g., -110, +150"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Game Time</label>
              <input
                type="text"
                value={formData.game_time}
                onChange={(e) => setFormData({...formData, game_time: e.target.value})}
                placeholder="e.g., 8:20 PM EST"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </div>

          {/* Confidence and Access Level */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
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
              <div className="flex justify-between text-xs text-gray-500 mt-1">
                <span>50%</span>
                <span>100%</span>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Access Level</label>
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

          {/* Reasoning */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-2">Reasoning</label>
            <textarea
              value={formData.reasoning}
              onChange={(e) => setFormData({...formData, reasoning: e.target.value})}
              placeholder="Explain your analysis and reasoning for this bet..."
              rows={4}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>

          {/* Submit Button */}
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
        </div>
        
        {/* Bet Verification Panel Modal */}
        {showVerificationPanel && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg max-w-4xl w-full max-h-[90vh] overflow-y-auto">
              <div className="p-6 border-b border-gray-200">
                <div className="flex items-center justify-between">
                  <h2 className="text-2xl font-bold text-gray-900 flex items-center">
                    <Target className="w-6 h-6 text-green-600 mr-2" />
                    Bet Verification System
                  </h2>
                  <button
                    onClick={() => setShowVerificationPanel(false)}
                    className="text-gray-400 hover:text-gray-600"
                  >
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              </div>
              
              <div className="p-6 space-y-6">
                {/* Action Buttons */}
                <div className="flex gap-4">
                  <button
                    onClick={triggerVerification}
                    disabled={isVerifying}
                    className="bg-green-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center"
                  >
                    {isVerifying ? (
                      <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                    ) : (
                      <Target className="w-5 h-5 mr-2" />
                    )}
                    {isVerifying ? 'Verifying...' : 'Run Verification Now'}
                  </button>
                  
                  <button
                    onClick={fetchVerificationStats}
                    className="bg-blue-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-blue-700 flex items-center"
                  >
                    <Clock className="w-5 h-5 mr-2" />
                    Refresh Stats
                  </button>
                </div>
                
                {/* Verification Statistics */}
                {verificationStats && (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {/* Scheduler Status */}
                    <div className="bg-gray-50 p-4 rounded-lg">
                      <h3 className="font-semibold text-gray-900 mb-2">Scheduler Status</h3>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span>Status:</span>
                          <span className={`font-medium ${verificationStats.status?.running ? 'text-green-600' : 'text-red-600'}`}>
                            {verificationStats.status?.running ? 'Running' : 'Stopped'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span>Interval:</span>
                          <span className="font-medium">{verificationStats.config?.interval_minutes} min</span>
                        </div>
                        <div className="flex justify-between">
                          <span>In Quiet Hours:</span>
                          <span className={`font-medium ${verificationStats.status?.in_quiet_hours ? 'text-yellow-600' : 'text-green-600'}`}>
                            {verificationStats.status?.in_quiet_hours ? 'Yes' : 'No'}
                          </span>
                        </div>
                      </div>
                    </div>
                    
                    {/* Run Statistics */}
                    <div className="bg-gray-50 p-4 rounded-lg">
                      <h3 className="font-semibold text-gray-900 mb-2">Run Statistics</h3>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span>Total Runs:</span>
                          <span className="font-medium">{verificationStats.stats?.total_runs || 0}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Successful:</span>
                          <span className="font-medium text-green-600">{verificationStats.stats?.successful_runs || 0}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Failed:</span>
                          <span className="font-medium text-red-600">{verificationStats.stats?.failed_runs || 0}</span>
                        </div>
                      </div>
                    </div>
                    
                    {/* Bet Statistics */}
                    <div className="bg-gray-50 p-4 rounded-lg">
                      <h3 className="font-semibold text-gray-900 mb-2">Bet Statistics</h3>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span>Total Verified:</span>
                          <span className="font-medium">{verificationStats.stats?.total_bets_verified || 0}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Total Settled:</span>
                          <span className="font-medium text-blue-600">{verificationStats.stats?.total_bets_settled || 0}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Success Rate:</span>
                          <span className="font-medium">
                            {verificationStats.stats?.total_runs > 0 
                              ? `${Math.round((verificationStats.stats.successful_runs / verificationStats.stats.total_runs) * 100)}%`
                              : '0%'
                            }
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
                
                {/* Recent Activity */}
                {verificationStats?.stats && (
                  <div className="bg-gray-50 p-4 rounded-lg">
                    <h3 className="font-semibold text-gray-900 mb-2">Recent Activity</h3>
                    <div className="space-y-2 text-sm">
                      {verificationStats.stats.last_run_time && (
                        <div className="flex justify-between">
                          <span>Last Run:</span>
                          <span className="font-medium">
                            {new Date(verificationStats.stats.last_run_time).toLocaleString()}
                          </span>
                        </div>
                      )}
                      {verificationStats.stats.last_success_time && (
                        <div className="flex justify-between">
                          <span>Last Success:</span>
                          <span className="font-medium text-green-600">
                            {new Date(verificationStats.stats.last_success_time).toLocaleString()}
                          </span>
                        </div>
                      )}
                      {verificationStats.stats.last_error && (
                        <div className="mt-2">
                          <span className="text-red-600 font-medium">Last Error:</span>
                          <p className="text-red-600 text-xs mt-1 bg-red-50 p-2 rounded">
                            {verificationStats.stats.last_error}
                          </p>
                        </div>
                      )}
                      {verificationStats.status?.next_run_estimate && (
                        <div className="flex justify-between">
                          <span>Next Run:</span>
                          <span className="font-medium text-blue-600">
                            {new Date(verificationStats.status.next_run_estimate).toLocaleString()}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )}
                
                {/* Configuration */}
                {verificationStats?.config && (
                  <div className="bg-gray-50 p-4 rounded-lg">
                    <h3 className="font-semibold text-gray-900 mb-2">Configuration</h3>
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div className="flex justify-between">
                        <span>Check Interval:</span>
                        <span className="font-medium">{verificationStats.config.interval_minutes} minutes</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Retry Interval:</span>
                        <span className="font-medium">{verificationStats.config.retry_interval_minutes} minutes</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Max Retries:</span>
                        <span className="font-medium">{verificationStats.config.max_retries}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Quiet Hours:</span>
                        <span className="font-medium">
                          {verificationStats.config.quiet_hours_start}:00 - {verificationStats.config.quiet_hours_end}:00 UTC
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
          </>
        )}

        {activeTab === 'featured' && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
              <Crown className="w-5 h-5 mr-2 text-yellow-600" />
              Manage Featured Games
            </h2>
            <p className="text-gray-600 mb-6">
              Create curated featured games with professional explanations that will be highlighted on the dashboard.
            </p>

            {/* Add New Featured Game Form */}
            <div className="bg-gray-50 rounded-lg p-6 mb-6">
              <h3 className="text-lg font-medium text-gray-900 mb-4 flex items-center">
                <Plus className="w-4 h-4 mr-2" />
                Add New Featured Game
              </h3>

              {/* Game Selector */}
              <div className="mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Select Game from Today's Schedule
                  {loadingTodaysGames && <span className="text-xs text-blue-600 ml-2">(Loading...)</span>}
                </label>

                {availableTodaysGames.length > 0 ? (
                  <select
                    value={selectedGameForFeatured?.id || ''}
                    onChange={(e) => handleGameSelectionForFeatured(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">Select a game from today's schedule...</option>
                    {availableTodaysGames.map((game) => (
                      <option key={game.id} value={game.id}>
                        {game.sport_name} - {game.away_team} @ {game.home_team} ({new Date(game.commence_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})
                      </option>
                    ))}
                  </select>
                ) : loadingTodaysGames ? (
                  <div className="flex items-center justify-center py-4 text-gray-500">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600 mr-2"></div>
                    Loading today's games...
                  </div>
                ) : (
                  <div className="text-center py-4 text-gray-500 bg-gray-100 rounded-lg">
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
                <label className="block text-sm font-medium text-gray-700 mb-2">Professional Explanation</label>
                <textarea
                  value={newFeaturedGame.explanation}
                  onChange={(e) => setNewFeaturedGame({...newFeaturedGame, explanation: e.target.value})}
                  placeholder="Provide a detailed analysis explaining why this game is featured. Include key factors, player insights, statistical analysis, etc."
                  rows={4}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>

              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">Admin Notes (Internal)</label>
                <textarea
                  value={newFeaturedGame.admin_notes}
                  onChange={(e) => setNewFeaturedGame({...newFeaturedGame, admin_notes: e.target.value})}
                  placeholder="Internal notes for other admins (not shown to users)"
                  rows={2}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
            </div>

            {/* Current Featured Games List */}
            <div className="mb-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-medium text-gray-900 flex items-center">
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
                <div className="text-center py-8 text-gray-500">
                  <Trophy className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                  <p>No featured games configured</p>
                  <p className="text-sm">Add your first featured game above</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {featuredGames.map((game, index) => (
                    <div key={index} className="border border-gray-200 rounded-lg p-4 bg-gray-50">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center mb-2">
                            <Crown className="w-4 h-4 text-yellow-600 mr-2" />
                            <h4 className="font-semibold text-gray-900">
                              {game.away_team} @ {game.home_team}
                            </h4>
                            <span className="ml-2 px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded">
                              {game.sport_key?.replace('_', ' ').toUpperCase() || 'Unknown Sport'}
                            </span>
                          </div>

                          {game.start_time && (
                            <div className="flex items-center text-sm text-gray-600 mb-2">
                              <Calendar className="w-4 h-4 mr-1" />
                              {new Date(game.start_time).toLocaleString()}
                            </div>
                          )}

                          <div className="text-sm text-gray-700 mb-2">
                            <strong>Game ID:</strong> {game.game_id}
                          </div>

                          {game.explanation && (
                            <div className="bg-white p-3 rounded border border-gray-200">
                              <p className="text-sm text-gray-800">
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
              <p className="text-sm text-gray-600 text-right mt-2">
                Select a game from today's schedule to continue
              </p>
            )}
            {selectedGameForFeatured && !newFeaturedGame.explanation.trim() && (
              <p className="text-sm text-gray-600 text-right mt-2">
                Add a professional explanation to save the featured game
              </p>
            )}
          </div>
        )}
      </div>
    </Layout>
  );
}