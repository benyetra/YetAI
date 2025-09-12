'use client';

import { useState, useEffect } from 'react';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import LiveBettingDashboard from '@/components/LiveBettingDashboard';
import ActiveLiveBets from '@/components/ActiveLiveBets';
import { apiClient } from '@/lib/api';
import { useNotifications } from '@/components/NotificationProvider';
import { Activity, TrendingUp, DollarSign, Clock } from 'lucide-react';

export default function LiveBettingPage() {
  const { isAuthenticated, loading, token } = useAuth();
  const { addNotification } = useNotifications();
  const [activeTab, setActiveTab] = useState('markets');
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [stats, setStats] = useState({
    activeBets: 0,
    totalCashedOut: 0,
    potentialWins: 0,
    liveGames: 0
  });

  useEffect(() => {
    if (isAuthenticated && token) {
      loadStats();
    }
  }, [isAuthenticated, token]);

  const loadStats = async () => {
    try {
      // Load user's live betting stats and pending regular bets
      const activeBetsResponse = await apiClient.get('/api/live-bets/active', token);
      const pendingBetsResponse = await apiClient.post('/api/bets/history', { status: 'pending', limit: 50 }, token);
      const marketsResponse = await apiClient.get('/api/live-bets/markets', token);
      
      if (activeBetsResponse.status === 'success') {
        const activeLiveBets = activeBetsResponse.active_bets || [];
        const pendingRegularBets = pendingBetsResponse.status === 'success' ? pendingBetsResponse.history || [] : [];
        
        const totalActiveBets = activeLiveBets.length + pendingRegularBets.length;
        const livePotentialWins = activeLiveBets.reduce((sum: number, bet: any) => 
          sum + (bet.current_potential_win || bet.potential_win || 0), 0
        );
        const pendingPotentialWins = pendingRegularBets.reduce((sum: number, bet: any) => 
          sum + (bet.potential_win || 0), 0
        );
        
        setStats({
          activeBets: totalActiveBets,
          totalCashedOut: activeLiveBets.filter((b: any) => b.status === 'cashed_out').length,
          potentialWins: livePotentialWins + pendingPotentialWins,
          liveGames: marketsResponse.count || 0
        });
      }
    } catch (error) {
      console.error('Failed to load live betting stats:', error);
    }
  };

  const handleBetPlaced = () => {
    // Refresh stats and trigger refresh of ActiveLiveBets component
    loadStats();
    setRefreshTrigger(prev => prev + 1);
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
    return (
      <Layout>
        <div className="min-h-screen flex items-center justify-center">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-800 mb-4">Sign In Required</h2>
            <p className="text-gray-600">Please sign in to access live betting.</p>
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="space-y-6">
        {/* Page Header */}
        <div className="bg-gradient-to-r from-red-600 to-orange-600 rounded-lg p-6 text-white">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold flex items-center">
                <Activity className="w-8 h-8 mr-3" />
                Live Betting
              </h1>
              <p className="mt-2 text-red-100">
                Place bets on games in progress with real-time odds and instant cash-out options
              </p>
            </div>
            <div className="hidden lg:flex items-center space-x-2 bg-white/10 backdrop-blur px-4 py-2 rounded-lg">
              <div className="w-3 h-3 bg-green-400 rounded-full animate-pulse"></div>
              <span className="text-sm font-medium">Live Now</span>
            </div>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Active Live Bets</p>
                <p className="text-2xl font-bold text-gray-900">{stats.activeBets}</p>
              </div>
              <Activity className="w-8 h-8 text-red-500" />
            </div>
          </div>

          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Potential Wins</p>
                <p className="text-2xl font-bold text-gray-900">
                  ${stats.potentialWins.toFixed(2)}
                </p>
              </div>
              <TrendingUp className="w-8 h-8 text-green-500" />
            </div>
          </div>

          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Cashed Out</p>
                <p className="text-2xl font-bold text-gray-900">{stats.totalCashedOut}</p>
              </div>
              <DollarSign className="w-8 h-8 text-blue-500" />
            </div>
          </div>

          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Live Games</p>
                <p className="text-2xl font-bold text-gray-900">{stats.liveGames}</p>
              </div>
              <Clock className="w-8 h-8 text-purple-500" />
            </div>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="border-b border-gray-200">
            <div className="flex space-x-8 px-6">
              <button
                onClick={() => setActiveTab('markets')}
                className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                  activeTab === 'markets'
                    ? 'border-red-500 text-red-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                Live Markets
              </button>
              <button
                onClick={() => setActiveTab('active')}
                className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors relative ${
                  activeTab === 'active'
                    ? 'border-red-500 text-red-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                My Active Bets
                {stats.activeBets > 0 && (
                  <span className="absolute -top-1 -right-6 bg-red-500 text-white text-xs rounded-full px-2 py-0.5">
                    {stats.activeBets}
                  </span>
                )}
              </button>
            </div>
          </div>

          {/* Tab Content */}
          <div className="p-6">
            {activeTab === 'markets' ? (
              <LiveBettingDashboard onBetPlaced={handleBetPlaced} />
            ) : (
              <ActiveLiveBets onUpdate={handleBetPlaced} key={refreshTrigger} />
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}