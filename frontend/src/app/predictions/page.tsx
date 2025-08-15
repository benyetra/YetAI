'use client';

import { useEffect, useState } from 'react';
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
  Zap
} from 'lucide-react';

interface BestBet {
  id: string;
  sport: string;
  game: string;
  betType: string;
  pick: string;
  odds: string;
  confidence: number;
  reasoning: string;
  status: 'pending' | 'won' | 'lost';
  isPremium: boolean;
  gameTime: string;
  result?: string;
}

export default function YetAIBetsPage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  const [selectedPeriod, setSelectedPeriod] = useState('today');

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

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

  // Mock data for today's best bets
  const todaysBets: BestBet[] = [
    {
      id: '1',
      sport: 'NFL',
      game: 'Chiefs vs Bills',
      betType: 'Spread',
      pick: 'Chiefs -3.5',
      odds: '-110',
      confidence: 92,
      reasoning: 'Chiefs have excellent road record vs top defenses. Buffalo missing key defensive players. Weather favors KC running game.',
      status: 'pending',
      isPremium: false,
      gameTime: '8:20 PM EST',
    },
    {
      id: '2', 
      sport: 'NBA',
      game: 'Lakers vs Warriors',
      betType: 'Total',
      pick: 'Over 228.5',
      odds: '-105',
      confidence: 87,
      reasoning: 'Both teams ranking in top 5 for pace. Lakers missing defensive anchor, Warriors at home average 118 PPG.',
      status: 'pending',
      isPremium: true,
      gameTime: '10:30 PM EST',
    },
    {
      id: '3',
      sport: 'MLB',
      game: 'Dodgers vs Padres',
      betType: 'Moneyline',
      pick: 'Dodgers ML',
      odds: '-135',
      confidence: 89,
      reasoning: 'Pitcher matchup heavily favors LAD. Padres bullpen fatigued from extra innings yesterday. Wind blowing out favors Dodgers power.',
      status: 'pending',
      isPremium: true,
      gameTime: '9:40 PM EST',
    },
    {
      id: '4',
      sport: 'NHL',
      game: 'Rangers vs Bruins',
      betType: 'Puck Line',
      pick: 'Rangers +1.5',
      odds: '-180',
      confidence: 84,
      reasoning: 'Rangers excellent in back-to-back games. Bruins on 4-game road trip, fatigue factor. Shesterkin expected to start.',
      status: 'pending',
      isPremium: true,
      gameTime: '7:00 PM EST',
    }
  ];

  // Mock data for recent performance
  const recentResults: BestBet[] = [
    {
      id: 'r1',
      sport: 'NFL',
      game: 'Cowboys vs Eagles',
      betType: 'Spread',
      pick: 'Eagles -7',
      odds: '-110',
      confidence: 90,
      reasoning: 'Eagles at home, Cowboys missing key players',
      status: 'won',
      isPremium: false,
      gameTime: 'Yesterday 8:20 PM',
      result: 'Eagles won 31-14'
    },
    {
      id: 'r2',
      sport: 'NBA',
      game: 'Celtics vs Heat',
      betType: 'Total',
      pick: 'Under 215.5',
      odds: '-105',
      confidence: 85,
      reasoning: 'Both teams excellent defensively',
      status: 'won',
      isPremium: true,
      gameTime: 'Yesterday 7:30 PM',
      result: 'Final: 102-98 (200 total)'
    },
    {
      id: 'r3',
      sport: 'MLB',
      game: 'Yankees vs Red Sox',
      betType: 'Moneyline',
      pick: 'Yankees ML',
      odds: '-150',
      confidence: 78,
      reasoning: 'Pitcher advantage to Yankees',
      status: 'lost',
      isPremium: true,
      gameTime: '2 days ago 7:05 PM',
      result: 'Red Sox won 6-4'
    }
  ];

  const visibleBets = isProUser ? todaysBets : todaysBets.slice(0, 1);
  const lockedBets = isProUser ? [] : todaysBets.slice(1);

  const stats = {
    todayWinRate: 85,
    weeklyWinRate: 82,
    monthlyWinRate: 79,
    totalBets: 156,
    wonBets: 128,
    avgOdds: -108
  };

  const BetCard = ({ bet, isLocked = false }: { bet: BestBet; isLocked?: boolean }) => (
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
      
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center space-x-2">
          <span className="bg-blue-100 text-blue-800 text-xs font-medium px-2 py-1 rounded">
            {bet.sport}
          </span>
          {bet.isPremium && (
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
          <div className="text-xs text-gray-500">{bet.gameTime}</div>
        </div>
      </div>

      <div className="mb-4">
        <h3 className="font-bold text-lg text-gray-900 mb-1">{bet.game}</h3>
        <div className="flex items-center space-x-4">
          <span className="text-gray-600">{bet.betType}:</span>
          <span className="font-semibold text-blue-600">{bet.pick}</span>
          <span className="text-gray-500">({bet.odds})</span>
        </div>
      </div>

      {!isLocked && (
        <>
          <div className="bg-gray-50 rounded-lg p-3 mb-4">
            <p className="text-sm text-gray-700">{bet.reasoning}</p>
          </div>

          {bet.result && (
            <div className={`text-sm font-medium ${
              bet.status === 'won' ? 'text-green-600' : 'text-red-600'
            }`}>
              Result: {bet.result}
            </div>
          )}
        </>
      )}
    </div>
  );

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
              <span className="text-2xl font-bold text-green-600">{stats.todayWinRate}%</span>
            </div>
            <h3 className="font-semibold text-gray-900 text-sm">Today's Win Rate</h3>
            <p className="text-xs text-gray-600">5 of 6 bets won</p>
          </div>
          
          <div className="bg-white p-4 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-2">
              <BarChart3 className="w-6 h-6 text-blue-600" />
              <span className="text-2xl font-bold text-blue-600">{stats.weeklyWinRate}%</span>
            </div>
            <h3 className="font-semibold text-gray-900 text-sm">7-Day Win Rate</h3>
            <p className="text-xs text-gray-600">23 of 28 bets</p>
          </div>

          <div className="bg-white p-4 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-2">
              <TrendingUp className="w-6 h-6 text-purple-600" />
              <span className="text-2xl font-bold text-purple-600">{stats.monthlyWinRate}%</span>
            </div>
            <h3 className="font-semibold text-gray-900 text-sm">30-Day Win Rate</h3>
            <p className="text-xs text-gray-600">{stats.wonBets} of {stats.totalBets} bets</p>
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

        {/* Today's Bets */}
        {selectedPeriod === 'today' && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-gray-900 flex items-center">
                <Calendar className="w-5 h-5 mr-2" />
                Today's Best Bets
              </h2>
              <span className="text-sm text-gray-500">
                {isProUser ? `${todaysBets.length} bets available` : '1 free bet, 3 premium bets'}
              </span>
            </div>
            
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {visibleBets.map((bet) => (
                <BetCard key={bet.id} bet={bet} />
              ))}
              {lockedBets.map((bet) => (
                <BetCard key={bet.id} bet={bet} isLocked={true} />
              ))}
            </div>
          </div>
        )}

        {/* Recent Results */}
        {selectedPeriod !== 'today' && (
          <div>
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
              <Star className="w-5 h-5 mr-2" />
              Recent Results
            </h2>
            
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {recentResults.map((bet) => (
                <BetCard key={bet.id} bet={bet} />
              ))}
            </div>
          </div>
        )}

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
      </div>
    </Layout>
  );
}