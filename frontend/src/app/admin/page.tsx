'use client';

import { useEffect, useState } from 'react';
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
  Users
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
    bet_type: '',
    pick: '',
    odds: '',
    confidence: 80,
    reasoning: '',
    game_time: '',
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
          const response = await fetch('http://localhost:8000/api/admin/bets/verification/stats', {
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
      const response = await fetch('http://localhost:8000/api/admin/yetai-bets', {
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
          bet_type: '',
          pick: '',
          odds: '',
          confidence: 80,
          reasoning: '',
          game_time: '',
          is_premium: true
        });
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
    setFormData({...formData, sport: selectedSport, game: '', bet_type: '', pick: '', odds: '', game_time: ''});
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
        'NHL': 'icehockey_nhl'
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
      const response = await fetch('http://localhost:8000/api/admin/bets/verification/stats', {
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

  const triggerVerification = async () => {
    setIsVerifying(true);
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch('http://localhost:8000/api/admin/bets/verify', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({})
      });
      
      if (response.ok) {
        const data = await response.json();
        setMessage({ type: 'success', text: `Verification completed: ${data.data?.message || 'Success'}` });
        // Refresh stats by setting verificationStats to null to trigger re-fetch
        setVerificationStats(null);
      } else {
        const errorData = await response.json();
        setMessage({ type: 'error', text: `Verification failed: ${errorData.detail || 'Unknown error'}` });
      }
    } catch (error) {
      console.error('Error triggering verification:', error);
      setMessage({ type: 'error', text: 'Failed to trigger bet verification' });
    } finally {
      setIsVerifying(false);
    }
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
      </div>
    </Layout>
  );
}