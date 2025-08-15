'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { TrendingUp, TrendingDown, DollarSign, Target, Brain, Cloud, Crown, ArrowUpRight, Calendar, Users, Wifi, WifiOff } from 'lucide-react';
import { useAuth } from './Auth';
import BetModal from './BetModal';
import { useWebSocket } from '@/hooks/useWebSocket';

interface User {
  id: string;
  email: string;
  first_name?: string;
  last_name?: string;
  subscription_tier: 'free' | 'pro' | 'elite';
  favorite_teams?: string[];
}

interface Game {
  id: string;
  home_team: string;
  away_team: string;
  home_score?: number;
  away_score?: number;
  status: string;
  start_time: string;
  commence_time?: string;
  sport?: string;
  home_odds?: number;
  away_odds?: number;
  spread?: number;
  total?: number;
  over_under?: number;
  weather_impact?: 'low' | 'medium' | 'high';
}

interface Prediction {
  id: string;
  game_id: string;
  type: 'spread' | 'moneyline' | 'over_under';
  recommendation: string;
  confidence: number;
  value_rating: number;
  reasoning: string;
}

interface Stats {
  total_predictions: number;
  accuracy_rate: number;
  profit_loss: number;
  win_streak: number;
}

interface AIInsight {
  title: string;
  content: string;
  confidence: number;
  category: 'trend' | 'injury' | 'weather' | 'value';
}

// StatCard Component
const StatCard: React.FC<{
  title: string;
  value: string | number;
  icon: React.ReactNode;
  change?: string;
  changeType?: 'positive' | 'negative' | 'neutral';
  subtitle?: string;
}> = ({ title, value, icon, change, changeType, subtitle }) => {
  const getChangeColor = () => {
    switch (changeType) {
      case 'positive': return 'text-green-600';
      case 'negative': return 'text-red-600';
      default: return 'text-gray-700';
    }
  };

  const getChangeIcon = () => {
    switch (changeType) {
      case 'positive': return <TrendingUp className="w-4 h-4" />;
      case 'negative': return <TrendingDown className="w-4 h-4" />;
      default: return null;
    }
  };

  return (
    <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200 metric-card">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-gray-700 metric-label">{title}</p>
          <p className="text-2xl font-bold text-gray-900 mt-2 metric-value value">{value}</p>
          {subtitle && (
            <p className="text-sm text-gray-600 font-medium mt-1 subtitle">{subtitle}</p>
          )}
        </div>
        <div className="p-2 bg-blue-50 rounded-lg">
          {icon}
        </div>
      </div>
      {change && (
        <div className={`flex items-center mt-4 ${getChangeColor()}`}>
          {getChangeIcon()}
          <span className="text-sm font-medium ml-1">{change}</span>
        </div>
      )}
    </div>
  );
};

// GameCard Component
const GameCard: React.FC<{
  game: Game;
  prediction?: Prediction;
  isFavorite?: boolean;
  onPlaceBet?: (game: Game) => void;
}> = ({ game, prediction, isFavorite, onPlaceBet }) => {
  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'live': return 'bg-red-100 text-red-800';
      case 'upcoming': return 'bg-blue-100 text-blue-800';
      case 'final': return 'bg-gray-100 text-gray-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const getWeatherIcon = (impact?: string) => {
    if (impact === 'high') return <Cloud className="w-4 h-4 text-red-500" />;
    if (impact === 'medium') return <Cloud className="w-4 h-4 text-yellow-500" />;
    return null;
  };

  return (
    <div className={`bg-white rounded-lg border-2 ${isFavorite ? 'border-blue-200 bg-blue-50' : 'border-gray-200'} p-4 hover:shadow-md transition-shadow`}>
      <div className="flex justify-between items-start mb-3">
        <div className="flex items-center space-x-2">
          <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(game.status)}`}>
            {game.status}
          </span>
          {getWeatherIcon(game.weather_impact)}
          {isFavorite && <span className="text-blue-600 text-xs font-medium">★ Favorite</span>}
        </div>
        <p className="text-xs text-gray-500">
          {new Date(game.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <span className="font-medium text-gray-900">{game.away_team}</span>
          {game.away_score !== undefined && (
            <span className="text-lg font-bold">{game.away_score}</span>
          )}
        </div>
        <div className="flex justify-between items-center">
          <span className="font-medium text-gray-900">{game.home_team}</span>
          {game.home_score !== undefined && (
            <span className="text-lg font-bold">{game.home_score}</span>
          )}
        </div>
      </div>

      {game.spread && (
        <div className="mt-3 text-sm text-gray-700 font-medium">
          <p>Spread: {game.home_team} {game.spread > 0 ? '+' : ''}{game.spread}</p>
          {game.over_under && <p>O/U: {game.over_under}</p>}
        </div>
      )}

      {prediction && (
        <div className="mt-3 p-3 bg-gray-50 rounded-lg">
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm font-medium text-gray-900">AI Prediction</span>
            <span className={`text-xs px-2 py-1 rounded ${
              prediction.confidence >= 80 ? 'bg-green-100 text-green-800' :
              prediction.confidence >= 60 ? 'bg-yellow-100 text-yellow-800' :
              'bg-red-100 text-red-800'
            }`}>
              {prediction.confidence}% confidence
            </span>
          </div>
          <p className="text-sm text-gray-800 font-medium">{prediction.recommendation}</p>
          <p className="text-xs text-gray-600 mt-1">{prediction.reasoning}</p>
        </div>
      )}
      
      {/* Place Bet Button */}
      {onPlaceBet && (game.status.toLowerCase() === 'upcoming' || game.status.toLowerCase() === 'status_scheduled' || game.status === 'SCHEDULED') && (
        <button
          onClick={() => onPlaceBet(game)}
          className="mt-3 w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 font-medium transition-colors"
        >
          Place Bet
        </button>
      )}
    </div>
  );
};

// AIInsightCard Component
const AIInsightCard: React.FC<{ insight: AIInsight }> = ({ insight }) => {
  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'trend': return <TrendingUp className="w-5 h-5 text-blue-600" />;
      case 'injury': return <Users className="w-5 h-5 text-red-600" />;
      case 'weather': return <Cloud className="w-5 h-5 text-gray-600" />;
      case 'value': return <Target className="w-5 h-5 text-green-600" />;
      default: return <Brain className="w-5 h-5 text-purple-600" />;
    }
  };

  return (
    <div className="bg-white p-4 rounded-lg border border-gray-200">
      <div className="flex items-start space-x-3">
        <div className="p-2 bg-gray-50 rounded-lg">
          {getCategoryIcon(insight.category)}
        </div>
        <div className="flex-1">
          <h4 className="font-medium text-gray-900 mb-1">{insight.title}</h4>
          <p className="text-sm text-gray-700 mb-2 leading-relaxed">{insight.content}</p>
          <div className="flex justify-between items-center">
            <span className="text-xs text-gray-600 capitalize font-medium">{insight.category}</span>
            <span className="text-xs font-medium text-blue-600">{insight.confidence}% confidence</span>
          </div>
        </div>
      </div>
    </div>
  );
};

// Main Dashboard Component
const Dashboard: React.FC = () => {
  const { user, token } = useAuth() as { user: User; token: string };
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<Stats>({
    total_predictions: 0,
    accuracy_rate: 0,
    profit_loss: 0,
    win_streak: 0
  });
  const [games, setGames] = useState<Game[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [insights, setInsights] = useState<AIInsight[]>([]);
  const [activeTab, setActiveTab] = useState('overview');
  const [showBetModal, setShowBetModal] = useState(false);
  const [selectedGame, setSelectedGame] = useState<Game | null>(null);
  
  // WebSocket integration
  const { isConnected, subscribeToGame, unsubscribeFromGame, getGameUpdate } = useWebSocket();

  // Handle place bet
  const handlePlaceBet = (game: Game) => {
    // Enhance game with required fields for BetModal
    const enhancedGame = {
      ...game,
      sport: 'NFL',
      commence_time: game.start_time,
      home_odds: game.home_odds || -110,
      away_odds: game.away_odds || +100,
      total: game.over_under || 45.5
    };
    setSelectedGame(enhancedGame);
    setShowBetModal(true);
  };

  // Fetch dashboard data
  useEffect(() => {
    const fetchDashboardData = async () => {
      setLoading(true);
      try {
        // Fetch user stats
        const statsResponse = await fetch('http://localhost:8000/api/user/performance', {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (statsResponse.ok) {
          const statsData = await statsResponse.json();
          setStats({
            total_predictions: statsData.personal_stats?.predictions_made || 25,
            accuracy_rate: statsData.personal_stats?.accuracy_rate || 78.5,
            profit_loss: typeof statsData.personal_stats?.total_profit === 'number' ? 
                         statsData.personal_stats.total_profit : 125.50,
            win_streak: 5
          });
        }

        // Fetch games and personalized predictions
        const [gamesResponse, predictionsResponse] = await Promise.all([
          fetch('http://localhost:8000/api/games/nfl'),
          fetch('http://localhost:8000/api/predictions/personalized', {
            headers: { 'Authorization': `Bearer ${token}` }
          })
        ]);

        if (gamesResponse.ok) {
          const gamesData = await gamesResponse.json();
          // Mock enhance games with additional data
          const enhancedGames = gamesData.games?.map((game: any, index: number) => ({
            id: game.id || `game_${index}`,
            home_team: game.home_team || game.home_display_name || 'TBD',
            away_team: game.away_team || game.away_display_name || 'TBD',
            home_score: game.home_score,
            away_score: game.away_score,
            status: game.status || 'upcoming',
            start_time: game.start_time || new Date().toISOString(),
            spread: game.spread || Math.random() * 14 - 7,
            over_under: game.over_under || 45 + Math.random() * 20,
            home_odds: game.home_odds || (Math.random() > 0.5 ? -110 - Math.random() * 100 : 100 + Math.random() * 100),
            away_odds: game.away_odds || (Math.random() > 0.5 ? -110 - Math.random() * 100 : 100 + Math.random() * 100),
            weather_impact: ['low', 'medium', 'high'][Math.floor(Math.random() * 3)] as 'low' | 'medium' | 'high'
          })) || [];
          setGames(enhancedGames);
        }

        // Mock predictions for demonstration
        const mockPredictions: Prediction[] = games.slice(0, 3).map((game, index) => ({
          id: `pred_${index}`,
          game_id: game.id,
          type: ['spread', 'moneyline', 'over_under'][index % 3] as 'spread' | 'moneyline' | 'over_under',
          recommendation: [
            `Take ${game.home_team} -3.5`,
            `Bet ${game.away_team} moneyline`,
            `Under ${game.over_under || 52.5}`
          ][index % 3],
          confidence: 75 + Math.random() * 20,
          value_rating: 7 + Math.random() * 3,
          reasoning: [
            'Strong home field advantage and better recent form',
            'Away team has favorable matchup against weak defense',
            'Weather conditions favor under, both teams struggle in rain'
          ][index % 3]
        }));
        setPredictions(mockPredictions);

        // Mock AI insights
        setInsights([
          {
            title: 'Weather Alert: Chiefs vs Bills',
            content: 'Heavy winds expected (15+ mph) will significantly impact passing games. Consider under bets and rushing prop overs.',
            confidence: 87,
            category: 'weather'
          },
          {
            title: 'Value Opportunity: Cowboys Spread',
            content: 'Public heavily backing Cowboys, but advanced metrics suggest Eagles are undervalued at current spread.',
            confidence: 92,
            category: 'value'
          },
          {
            title: 'Injury Impact: Star WR Questionable',
            content: 'Top receiver listed as questionable with ankle injury. Historical data shows 15% drop in offensive production.',
            confidence: 78,
            category: 'injury'
          }
        ]);

      } catch (error) {
        console.error('Error fetching dashboard data:', error);
      } finally {
        setLoading(false);
      }
    };

    if (user && token) {
      fetchDashboardData();
    }
  }, [user, token]);

  // Subscribe to game updates via WebSocket
  useEffect(() => {
    if (isConnected && games.length > 0) {
      games.forEach(game => {
        subscribeToGame(game.id);
      });

      // Cleanup on unmount or games change
      return () => {
        games.forEach(game => {
          unsubscribeFromGame(game.id);
        });
      };
    }
  }, [isConnected, games, subscribeToGame, unsubscribeFromGame]);

  // Function to get live odds for a game
  const getLiveGameData = (game: Game) => {
    const liveUpdate = getGameUpdate(game.id);
    if (liveUpdate) {
      return {
        ...game,
        home_odds: liveUpdate.home_odds ?? game.home_odds,
        away_odds: liveUpdate.away_odds ?? game.away_odds,
        spread: liveUpdate.spread ?? game.spread,
        total: liveUpdate.total ?? game.total,
        home_score: liveUpdate.home_score ?? game.home_score,
        away_score: liveUpdate.away_score ?? game.away_score,
        movement: liveUpdate.movement,
        last_updated: liveUpdate.last_updated
      };
    }
    return game;
  };

  // Get user's favorite teams for highlighting
  const favoriteTeams = user?.favorite_teams || ['KC', 'BUF']; // Demo favorites

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-lg">Loading dashboard...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div>
              <div className="flex items-center space-x-3">
                <h1 className="text-2xl font-bold text-gray-900 page-title">
                  Welcome back, {user?.first_name || 'Player'}!
                </h1>
                <div className="flex items-center space-x-1">
                  {isConnected ? (
                    <Wifi className="w-4 h-4 text-green-600" />
                  ) : (
                    <WifiOff className="w-4 h-4 text-red-600" />
                  )}
                  <span className={`text-xs font-medium ${
                    isConnected ? 'text-green-600' : 'text-red-600'
                  }`}>
                    {isConnected ? 'Live' : 'Offline'}
                  </span>
                </div>
              </div>
              <p className="text-sm text-gray-700 font-medium">
                {user?.subscription_tier === 'free' ? 'Free Tier' : 
                 user?.subscription_tier === 'pro' ? 'Pro Member' : 'Elite Member'}
              </p>
            </div>
            {user?.subscription_tier === 'free' && (
              <button className="bg-gradient-to-r from-blue-600 to-purple-600 text-white px-4 py-2 rounded-lg hover:from-blue-700 hover:to-purple-700 font-medium flex items-center">
                <Crown className="w-4 h-4 mr-2" />
                Upgrade to Pro
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <nav className="flex space-x-8">
            {['overview', 'games', 'insights', 'performance'].map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`py-4 px-1 border-b-2 font-medium text-sm capitalize ${
                  activeTab === tab
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-600 hover:text-gray-800 hover:border-gray-300 font-medium'
                }`}
              >
                {tab}
              </button>
            ))}
            <Link
              href="/bets"
              className="py-4 px-1 border-b-2 border-transparent text-purple-600 hover:text-purple-700 hover:border-purple-300 font-medium text-sm"
            >
              My Bets
            </Link>
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {activeTab === 'overview' && (
          <div className="space-y-8">
            {/* Stats Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              <StatCard
                title="Total Predictions"
                value={stats.total_predictions}
                icon={<Target className="w-6 h-6 text-blue-600" />}
                change="+3 this week"
                changeType="positive"
              />
              <StatCard
                title="Accuracy Rate"
                value={`${stats.accuracy_rate}%`}
                icon={<TrendingUp className="w-6 h-6 text-green-600" />}
                change="+2.3% vs last month"
                changeType="positive"
              />
              <StatCard
                title={user?.subscription_tier === 'free' ? 'Upgrade for P&L' : 'Profit/Loss'}
                value={user?.subscription_tier === 'free' ? 'Pro Feature' : `$${stats.profit_loss}`}
                icon={<DollarSign className="w-6 h-6 text-green-600" />}
                change={user?.subscription_tier !== 'free' ? '+$23 today' : undefined}
                changeType="positive"
              />
              <StatCard
                title="Win Streak"
                value={stats.win_streak}
                icon={<ArrowUpRight className="w-6 h-6 text-blue-600" />}
                subtitle="Current streak"
              />
            </div>

            {/* AI Insights */}
            <div>
              <h2 className="text-xl font-bold text-gray-900 mb-4 flex items-center section-subtitle">
                <Brain className="w-5 h-5 mr-2 text-purple-600" />
                AI Insights
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {insights.map((insight, index) => (
                  <AIInsightCard key={index} insight={insight} />
                ))}
              </div>
            </div>

            {/* Featured Games */}
            <div>
              <h2 className="text-xl font-bold text-gray-900 mb-4 section-subtitle">Today's Featured Games</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {games.slice(0, 6).map((game) => {
                  const prediction = predictions.find(p => p.game_id === game.id);
                  const isFavorite = favoriteTeams.some(team => 
                    game.home_team.includes(team) || game.away_team.includes(team)
                  );
                  return (
                    <GameCard
                      key={game.id}
                      game={getLiveGameData(game)}
                      prediction={prediction}
                      isFavorite={isFavorite}
                      onPlaceBet={handlePlaceBet}
                    />
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'games' && (
          <div className="space-y-6">
            <h2 className="text-xl font-bold text-gray-900">All Games</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {games.map((game) => {
                const prediction = predictions.find(p => p.game_id === game.id);
                const isFavorite = favoriteTeams.some(team => 
                  game.home_team.includes(team) || game.away_team.includes(team)
                );
                return (
                  <GameCard
                    key={game.id}
                    game={getLiveGameData(game)}
                    prediction={prediction}
                    isFavorite={isFavorite}
                    onPlaceBet={handlePlaceBet}
                  />
                );
              })}
            </div>
          </div>
        )}

        {activeTab === 'insights' && (
          <div className="space-y-6">
            <h2 className="text-xl font-bold text-gray-900">AI Insights & Analysis</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {insights.map((insight, index) => (
                <AIInsightCard key={index} insight={insight} />
              ))}
            </div>
          </div>
        )}

        {activeTab === 'performance' && (
          <div className="space-y-6">
            <h2 className="text-xl font-bold text-gray-900">Performance Analytics</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              <StatCard
                title="Win Rate"
                value={`${stats.accuracy_rate}%`}
                icon={<Target className="w-6 h-6 text-green-600" />}
              />
              <StatCard
                title="Best Sport"
                value="NFL"
                icon={<TrendingUp className="w-6 h-6 text-blue-600" />}
                subtitle="85% accuracy"
              />
              <StatCard
                title="Favorite Bet"
                value="Spreads"
                icon={<Calendar className="w-6 h-6 text-purple-600" />}
                subtitle="12 bets this week"
              />
              <StatCard
                title="ROI"
                value={user?.subscription_tier === 'free' ? 'Upgrade' : '12.5%'}
                icon={<DollarSign className="w-6 h-6 text-green-600" />}
                subtitle={user?.subscription_tier !== 'free' ? 'Last 30 days' : 'Pro feature'}
              />
            </div>
          </div>
        )}

        {/* Subscription Upsell for Free Users */}
        {user?.subscription_tier === 'free' && (
          <div className="mt-8 bg-gradient-to-r from-blue-50 to-purple-50 border border-blue-200 rounded-lg p-6">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-gray-900 mb-2">
                  Unlock Premium Features
                </h3>
                <p className="text-gray-700 leading-relaxed">
                  Get advanced analytics, profit tracking, exclusive insights, and more accurate predictions.
                </p>
              </div>
              <button className="bg-gradient-to-r from-[#A855F7] to-[#F59E0B] text-white px-6 py-3 rounded-lg hover:from-[#A855F7]/90 hover:to-[#F59E0B]/90 font-medium flex items-center whitespace-nowrap ml-4">
                <Crown className="w-4 h-4 mr-2" />
                Upgrade Now
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Bet Placement Modal */}
      <BetModal
        isOpen={showBetModal}
        onClose={() => {
          setShowBetModal(false);
          setSelectedGame(null);
        }}
        game={selectedGame}
      />
    </div>
  );
};

export default Dashboard;