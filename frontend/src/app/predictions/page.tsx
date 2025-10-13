'use client';

import { useEffect, useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { 
  Brain, 
  TrendingUp, 
  Target, 
  Clock, 
  Lock, 
  Crown, 
  CheckCircle, 
  XCircle,
  Calendar,
  DollarSign,
  BarChart3,
  Star,
  Zap,
  Trash2,
  Plus
} from 'lucide-react';
import YetAIBetModal from '@/components/YetAIBetModal';

interface BestBet {
  id: string;
  sport: string;
  game: string;
  bet_type: string;
  pick: string;
  odds: string;
  confidence: number;
  reasoning: string;
  status: 'pending' | 'won' | 'lost' | 'pushed';
  is_premium: boolean;
  game_time: string;
  result?: string;
  bet_category?: 'straight' | 'parlay';
  parlay_legs?: Array<{
    sport: string;
    game: string;
    bet_type: string;
    pick: string;
    odds: string;
  }>;
}

export default function YetAIBetsPage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  const [selectedPeriod, setSelectedPeriod] = useState('today');
  const [bets, setBets] = useState<BestBet[]>([]);
  const [loadingBets, setLoadingBets] = useState(true);
  const [performanceStats, setPerformanceStats] = useState({
    todayWinRate: 0,
    weeklyWinRate: 0,
    monthlyWinRate: 0,
    totalBets: 0,
    wonBets: 0,
    avgOdds: 0
  });
  const [selectedBetForPlacement, setSelectedBetForPlacement] = useState<BestBet | null>(null);
  const [showBetModal, setShowBetModal] = useState(false);
  const [deletingBetId, setDeletingBetId] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (isAuthenticated && user) {
      fetchBets();
    }
  }, [isAuthenticated, user]);

  const fetchBets = async () => {
    try {
      setLoadingBets(true);
      const token = localStorage.getItem('auth_token');
      const response = await fetch(getApiUrl('/api/yetai-bets'), {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });
      
      if (response.ok) {
        const data = await response.json();
        console.log('API response:', data); // Debug log

        // Extract bets from the response object
        const betsArray = Array.isArray(data.bets) ? data.bets : [];

        // Debug date filtering
        if (betsArray.length > 0) {
          console.log('Sample bet game_time format:', betsArray[0].game_time);
          console.log('Today\'s date:', new Date().toDateString());
        }
        setBets(betsArray);
        
        // Calculate performance stats from data
        const totalBets = betsArray.length;
        const settledBets = betsArray.filter((bet: BestBet) => bet.status === 'won' || bet.status === 'lost');
        const wonBets = betsArray.filter((bet: BestBet) => bet.status === 'won');
        const winRate = settledBets.length > 0 ? (wonBets.length / settledBets.length) * 100 : 0;
        
        setPerformanceStats({
          todayWinRate: Math.round(winRate),
          weeklyWinRate: Math.round(winRate * 0.95), // Mock calculation
          monthlyWinRate: Math.round(winRate * 0.9), // Mock calculation
          totalBets,
          wonBets: wonBets.length,
          avgOdds: -108 // Mock value
        });
      } else {
        console.error('API error:', response.status, response.statusText);
        setBets([]); // Set empty array on error
      }
    } catch (error) {
      console.error('Error fetching bets:', error);
      setBets([]); // Set empty array on error
    } finally {
      setLoadingBets(false);
    }
  };

  const handlePlaceBet = (bet: BestBet) => {
    setSelectedBetForPlacement(bet);
    setShowBetModal(true);
  };

  const handleDeleteBet = async (betId: string) => {
    if (!user?.is_admin) return;
    
    const confirmed = window.confirm('Are you sure you want to delete this bet? This action cannot be undone.');
    if (!confirmed) return;

    try {
      setDeletingBetId(betId);
      const token = localStorage.getItem('auth_token');
      const response = await fetch(getApiUrl(`/api/admin/yetai-bets/${betId}`), {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      if (response.ok) {
        // Remove the bet from the local state
        setBets(prevBets => prevBets.filter(bet => bet.id !== betId));
      } else {
        const errorData = await response.json();
        alert(`Failed to delete bet: ${errorData.detail || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('Error deleting bet:', error);
      alert('Failed to delete bet. Please try again.');
    } finally {
      setDeletingBetId(null);
    }
  };

  const handleBetPlaced = () => {
    // Optionally refresh bets or show success message
    setShowBetModal(false);
    setSelectedBetForPlacement(null);
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

  const isProUser = user?.subscription_tier === 'pro' || user?.subscription_tier === 'elite';

  // Helper function to check if a date string matches the selected period
  const isInPeriod = (gameTimeStr: string, period: string) => {
    try {
      // Parse the game time string - handle different formats
      let dateStr = gameTimeStr;

      // If format is "09/16/2025 @06:46 PM EDT", extract just the date part
      if (dateStr.includes(' @')) {
        dateStr = dateStr.split(' @')[0];
      }

      // Parse the date (handle MM/DD/YYYY format)
      const gameDate = new Date(dateStr);
      const today = new Date();

      // Debug logging
      console.log(`Parsing date: "${dateStr}" -> ${gameDate.toDateString()}, Today: ${today.toDateString()}`);

      // Ensure we have a valid date
      if (isNaN(gameDate.getTime())) {
        console.warn('Invalid date format:', gameTimeStr);
        return false;
      }

      // Set times to start of day for comparison
      gameDate.setHours(0, 0, 0, 0);
      today.setHours(0, 0, 0, 0);

      const yesterday = new Date(today);
      yesterday.setDate(today.getDate() - 1);
      const weekAgo = new Date(today);
      weekAgo.setDate(today.getDate() - 7);

      switch (period) {
        case 'today':
          const isToday = gameDate.getTime() === today.getTime();
          console.log(`Today check: ${isToday} (${gameDate.toDateString()} === ${today.toDateString()})`);
          return isToday;
        case 'yesterday':
          const isYesterday = gameDate.getTime() === yesterday.getTime();
          console.log(`Yesterday check: ${isYesterday} (${gameDate.toDateString()} === ${yesterday.toDateString()})`);
          return isYesterday;
        case 'week':
          const isInWeek = gameDate.getTime() >= weekAgo.getTime() && gameDate.getTime() <= today.getTime();
          console.log(`Week check: ${isInWeek} (${gameDate.toDateString()} between ${weekAgo.toDateString()} and ${today.toDateString()})`);
          return isInWeek;
        default:
          return false;
      }
    } catch (error) {
      console.error('Error parsing date:', gameTimeStr, error);
      return false;
    }
  };

  // Filter bets based on selected period and user tier
  const todaysBets = bets.filter(bet => {
    const matchesPeriod = isInPeriod(bet.game_time, selectedPeriod);
    // For 'today' period, show pending bets for today
    if (selectedPeriod === 'today') {
      const result = bet.status === 'pending' && matchesPeriod;
      console.log(`Today filter - Bet ${bet.id} (${bet.game_time}): matchesPeriod=${matchesPeriod}, status=${bet.status}, included=${result}`);
      return result;
    }
    // For other periods (yesterday/week), show all bets (pending, won, lost) in that time range
    const result = matchesPeriod;
    console.log(`${selectedPeriod} filter - Bet ${bet.id} (${bet.game_time}): matchesPeriod=${matchesPeriod}, status=${bet.status}, included=${result}`);
    return result;
  });

  const recentResults = bets.filter(bet => {
    // This is now only used for the "Recent Results" section when selectedPeriod !== 'today'
    // For non-today periods, we show all bets in todaysBets, so this can be empty
    return selectedPeriod === 'today' && (bet.status === 'won' || bet.status === 'lost') && isInPeriod(bet.game_time, selectedPeriod);
  });

  const visibleBets = isProUser ? todaysBets : todaysBets.slice(0, 1);
  const lockedBets = isProUser ? [] : todaysBets.slice(1);

  // Helper function to check if a game is in the past
  const isGameInPast = (gameTimeStr: string) => {
    try {
      // Parse format: "10/12/2025 @01:00 PM EDT"
      // Remove timezone abbreviation and parse the full datetime
      let dateStr = gameTimeStr.replace(' EDT', '').replace(' EST', '').replace(' PST', '').replace(' MST', '');

      // Replace @ with space for proper parsing: "10/12/2025 01:00 PM"
      if (dateStr.includes(' @')) {
        dateStr = dateStr.replace(' @', ' ');
      }

      const gameDate = new Date(dateStr);
      const now = new Date();

      // If parsing failed, return false (treat as upcoming)
      if (isNaN(gameDate.getTime())) {
        console.warn('Failed to parse game time:', gameTimeStr);
        return false;
      }

      return gameDate < now;
    } catch (error) {
      console.error('Error parsing game time:', gameTimeStr, error);
      return false;
    }
  };

  const BetCard = ({ bet, isLocked = false }: { bet: BestBet; isLocked?: boolean }) => {
    const gameIsInPast = isGameInPast(bet.game_time);

    return (
    <div className={`bg-white rounded-lg border-2 p-6 relative ${
      isLocked ? 'border-gray-200 opacity-60' :
      bet.status === 'won' ? 'border-green-200' :
      bet.status === 'lost' ? 'border-red-200' : 'border-blue-200'
    }`}>
      {isLocked && (
        <div className="absolute inset-0 bg-gray-50 bg-opacity-90 rounded-lg flex items-center justify-center z-10">
          <div className="text-center">
            <Lock className="w-8 h-8 text-gray-400 mx-auto mb-2" />
            <p className="text-gray-600 font-medium">Pro Members Only</p>
            <button 
              onClick={() => router.push('/upgrade')}
              className="mt-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700 transition-colors"
            >
              Upgrade Now
            </button>
          </div>
        </div>
      )}

      {/* Admin Delete Button */}
      {user?.is_admin && !isLocked && (
        <button
          onClick={() => handleDeleteBet(bet.id)}
          disabled={deletingBetId === bet.id}
          className="absolute top-2 right-2 p-1.5 text-red-500 hover:text-red-700 hover:bg-red-50 rounded-full transition-colors disabled:opacity-50 z-10"
          title="Delete bet (Admin only)"
        >
          {deletingBetId === bet.id ? (
            <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-red-500"></div>
          ) : (
            <Trash2 className="w-3 h-3" />
          )}
        </button>
      )}
      
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center space-x-2">
          <span className="bg-blue-100 text-blue-800 text-xs font-medium px-2 py-1 rounded">
            {bet.sport}
          </span>
          {bet.is_premium && (
            <Crown className="w-4 h-4 text-yellow-500" />
          )}
          {bet.status === 'won' && (
            <CheckCircle className="w-4 h-4 text-green-500" />
          )}
          {bet.status === 'lost' && (
            <XCircle className="w-4 h-4 text-red-500" />
          )}
        </div>
        <div className="text-right">
          <div className={`text-sm font-medium ${
            bet.confidence >= 90 ? 'text-green-600' :
            bet.confidence >= 80 ? 'text-blue-600' : 'text-yellow-600'
          }`}>
            {bet.confidence}% Confidence
          </div>
          <div className="text-xs text-gray-500">{bet.game_time}</div>
        </div>
      </div>

      <div className="mb-4">
        <h3 className="font-bold text-lg text-gray-900 mb-1">{bet.game}</h3>
        <div className="flex items-center space-x-4">
          <span className="text-gray-600">{bet.bet_type.charAt(0).toUpperCase() + bet.bet_type.slice(1)}:</span>
          <span className="font-semibold text-blue-600">{bet.pick}</span>
          <span className="text-gray-500">({bet.odds})</span>
        </div>
        {bet.bet_category === 'parlay' && bet.parlay_legs && (
          <div className="mt-2">
            <p className="text-xs text-gray-500 mb-1">Parlay Legs:</p>
            <div className="space-y-1">
              {bet.parlay_legs.map((leg, index) => (
                <div key={index} className="text-xs text-gray-600 bg-gray-50 p-2 rounded">
                  {leg.sport} - {leg.game}: {leg.bet_type} {leg.pick} ({leg.odds})
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {!isLocked && (
        <>
          <div className="bg-gray-50 rounded-lg p-3 mb-4">
            <p className="text-sm text-gray-700">{bet.reasoning}</p>
          </div>

          {/* Show result for completed bets */}
          {bet.result && bet.status !== 'pending' && (
            <div className={`mt-4 pt-4 border-t border-gray-200 text-center ${
              bet.status === 'won' ? 'text-green-600' :
              bet.status === 'lost' ? 'text-red-600' : 'text-gray-600'
            }`}>
              <div className="flex items-center justify-center space-x-2 mb-2">
                {bet.status === 'won' && <CheckCircle className="w-5 h-5" />}
                {bet.status === 'lost' && <XCircle className="w-5 h-5" />}
                <span className="font-semibold text-lg">
                  {bet.status === 'won' ? 'Won' :
                   bet.status === 'lost' ? 'Lost' :
                   bet.status === 'pushed' ? 'Push' : 'Result'}
                </span>
              </div>
              <div className="text-sm font-medium">
                {bet.result}
              </div>
            </div>
          )}

          {/* Show "Game in Progress" for pending bets in the past */}
          {bet.status === 'pending' && gameIsInPast && (
            <div className="mt-4 pt-4 border-t border-gray-200">
              <div className="w-full bg-gray-100 text-gray-600 py-2 px-4 rounded-lg flex items-center justify-center space-x-2">
                <Clock className="w-4 h-4" />
                <span>Game in Progress / Awaiting Result</span>
              </div>
            </div>
          )}

          {/* Place Bet Button - Only show for pending bets that haven't started yet */}
          {bet.status === 'pending' && !gameIsInPast && (
            <div className="mt-4 pt-4 border-t border-gray-200">
              <button
                onClick={() => handlePlaceBet(bet)}
                className="w-full bg-blue-600 text-white py-2 px-4 rounded-lg hover:bg-blue-700 transition-colors flex items-center justify-center space-x-2"
              >
                <Plus className="w-4 h-4" />
                <span>Place Bet</span>
              </button>
            </div>
          )}
        </>
      )}
    </div>
    );
  };

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center">
              <Brain className="w-8 h-8 text-blue-600 mr-3" />
              YetAI Bets
            </h1>
            <p className="text-gray-600 mt-1">
              {isProUser ? 'Your daily premium betting insights' : 'Get 1 free bet daily, upgrade for 3+ premium bets'}
            </p>
          </div>
          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-2 text-sm text-gray-500">
              <Clock className="w-4 h-4" />
              <span>Updated 3 minutes ago</span>
            </div>
            {!isProUser && (
              <button 
                onClick={() => router.push('/upgrade')}
                className="bg-gradient-to-r from-blue-600 to-purple-600 text-white px-4 py-2 rounded-lg hover:from-blue-700 hover:to-purple-700 font-medium flex items-center"
              >
                <Crown className="w-4 h-4 mr-2" />
                Upgrade to Pro
              </button>
            )}
          </div>
        </div>

        {/* Performance Stats */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-white p-4 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-2">
              <Target className="w-6 h-6 text-green-600" />
              <span className="text-2xl font-bold text-green-600">{performanceStats.todayWinRate}%</span>
            </div>
            <h3 className="font-semibold text-gray-900 text-sm">Today's Win Rate</h3>
            <p className="text-xs text-gray-600">{performanceStats.wonBets} of {performanceStats.totalBets} bets</p>
          </div>
          
          <div className="bg-white p-4 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-2">
              <BarChart3 className="w-6 h-6 text-blue-600" />
              <span className="text-2xl font-bold text-blue-600">{performanceStats.weeklyWinRate}%</span>
            </div>
            <h3 className="font-semibold text-gray-900 text-sm">7-Day Win Rate</h3>
            <p className="text-xs text-gray-600">{Math.floor(performanceStats.wonBets * 0.85)} of {Math.floor(performanceStats.totalBets * 0.9)} bets</p>
          </div>

          <div className="bg-white p-4 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-2">
              <TrendingUp className="w-6 h-6 text-purple-600" />
              <span className="text-2xl font-bold text-purple-600">{performanceStats.monthlyWinRate}%</span>
            </div>
            <h3 className="font-semibold text-gray-900 text-sm">30-Day Win Rate</h3>
            <p className="text-xs text-gray-600">{performanceStats.wonBets} of {performanceStats.totalBets} bets</p>
          </div>

          <div className="bg-white p-4 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-2">
              <DollarSign className="w-6 h-6 text-green-600" />
              <span className="text-2xl font-bold text-green-600">+$2,340</span>
            </div>
            <h3 className="font-semibold text-gray-900 text-sm">Monthly Profit</h3>
            <p className="text-xs text-gray-600">$100 unit size</p>
          </div>
        </div>

        {/* Period Selector */}
        <div className="flex space-x-4">
          {['today', 'yesterday', 'week'].map((period) => (
            <button
              key={period}
              onClick={() => setSelectedPeriod(period)}
              className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                selectedPeriod === period
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              {period.charAt(0).toUpperCase() + period.slice(1)}
            </button>
          ))}
        </div>

        {/* Current Period Bets */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold text-gray-900 flex items-center">
              <Calendar className="w-5 h-5 mr-2" />
              {selectedPeriod === 'today' ? "Today's Best Bets" :
               selectedPeriod === 'yesterday' ? "Yesterday's Bets" :
               "This Week's Bets"}
            </h2>
            <span className="text-sm text-gray-500">
              {loadingBets ? 'Loading...' :
                selectedPeriod === 'today' && !isProUser ? '1 free bet, 3 premium bets' :
                `${todaysBets.length} bets available`}
            </span>
          </div>

          {loadingBets ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {selectedPeriod === 'today' ? (
                <>
                  {visibleBets.map((bet) => (
                    <BetCard key={bet.id} bet={bet} />
                  ))}
                  {lockedBets.map((bet) => (
                    <BetCard key={bet.id} bet={bet} isLocked={true} />
                  ))}
                </>
              ) : (
                <>
                  {todaysBets.map((bet) => (
                    <BetCard key={bet.id} bet={bet} />
                  ))}
                </>
              )}
              {!loadingBets && todaysBets.length === 0 && (
                <div className="col-span-2 text-center py-8 text-gray-500">
                  {selectedPeriod === 'today' ? 'No bets available today. Check back later!' :
                   selectedPeriod === 'yesterday' ? 'No bets from yesterday.' :
                   'No bets from this week.'}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Upgrade CTA for Free Users */}
        {!isProUser && (
          <div className="bg-gradient-to-r from-blue-50 to-purple-50 rounded-lg p-6 border border-blue-200">
            <div className="flex items-center justify-between">
              <div className="flex items-center">
                <Zap className="w-8 h-8 text-blue-600 mr-3" />
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">Unlock All Daily Bets</h3>
                  <p className="text-gray-600">Get access to 3+ premium bets daily with detailed analysis and higher win rates</p>
                </div>
              </div>
              <button 
                onClick={() => router.push('/upgrade')}
                className="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 font-medium transition-colors"
              >
                Upgrade Now
              </button>
            </div>
          </div>
        )}

        {/* Bet Placement Modal */}
        <YetAIBetModal
          isOpen={showBetModal}
          onClose={() => {
            setShowBetModal(false);
            setSelectedBetForPlacement(null);
          }}
          bet={selectedBetForPlacement}
          onBetPlaced={handleBetPlaced}
        />
      </div>
    </Layout>
  );
}