'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { Trophy, Medal, Crown, TrendingUp, Users, Star } from 'lucide-react';

interface LeaderboardEntry {
  rank: number;
  user_id: number;
  username: string;
  profit: number;
  win_rate: number;
  roi: number;
  total_bets: number;
  total_wagered: number;
  is_current_user: boolean;
}

interface LeaderboardData {
  status: string;
  period: string;
  leaderboard: LeaderboardEntry[];
  current_user_rank: number | null;
  stats: {
    total_players: number;
    active_players: number;
    current_user_points: number;
  };
}

export default function LeaderboardPage() {
  const { isAuthenticated, loading, token } = useAuth();
  const router = useRouter();
  const [selectedPeriod, setSelectedPeriod] = useState('weekly');
  const [leaderboardData, setLeaderboardData] = useState<LeaderboardData | null>(null);
  const [isLoadingData, setIsLoadingData] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchLeaderboardData();
    }
  }, [isAuthenticated, selectedPeriod]);

  const fetchLeaderboardData = async () => {
    try {
      setIsLoadingData(true);
      setError(null);

      if (!token) {
        setError('Authentication required');
        return;
      }

      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/leaderboard?period=${selectedPeriod}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      console.log('Leaderboard API response:', data);

      if (data.status === 'success') {
        setLeaderboardData(data);
      } else {
        setError('Failed to load leaderboard data');
      }
    } catch (error) {
      console.error('Error fetching leaderboard data:', error);
      setError('Failed to load leaderboard data');
    } finally {
      setIsLoadingData(false);
    }
  };

  if (loading || isLoadingData) {
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

  const getRankIcon = (rank: number) => {
    switch (rank) {
      case 1: return <Crown className="w-6 h-6 text-yellow-500" />;
      case 2: return <Medal className="w-6 h-6 text-gray-400" />;
      case 3: return <Medal className="w-6 h-6 text-amber-600" />;
      default: return <span className="w-6 h-6 flex items-center justify-center text-gray-500 font-bold">{rank}</span>;
    }
  };

  const formatCurrency = (amount: number) => {
    const sign = amount >= 0 ? '+' : '-';
    return `${sign}$${Math.abs(amount).toLocaleString()}`;
  };

  if (error || !leaderboardData) {
    return (
      <Layout requiresAuth>
        <div className="space-y-6">
          <h1 className="text-3xl font-bold text-gray-900">Leaderboard</h1>

          {error ? (
            <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
              <p className="text-red-600 mb-4">{error}</p>
              <button
                onClick={fetchLeaderboardData}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
              >
                Try Again
              </button>
            </div>
          ) : (
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-12 text-center">
              <p className="text-gray-600 mb-4">No leaderboard data available</p>
              <button
                onClick={fetchLeaderboardData}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                Load Leaderboard
              </button>
            </div>
          )}
        </div>
      </Layout>
    );
  }

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold text-gray-900">Leaderboard</h1>
          <select
            value={selectedPeriod}
            onChange={(e) => setSelectedPeriod(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="all_time">All Time</option>
          </select>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Trophy className="w-8 h-8 text-yellow-500" />
              <span className="text-2xl font-bold text-yellow-500">#1</span>
            </div>
            <h3 className="font-semibold text-gray-900">Your Best Rank</h3>
            <p className="text-sm text-gray-600">
              {leaderboardData.current_user_rank ? `Currently #${leaderboardData.current_user_rank}` : 'No ranking yet'}
            </p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Users className="w-8 h-8 text-blue-600" />
              <span className="text-2xl font-bold text-blue-600">
                {leaderboardData.stats.active_players.toLocaleString()}
              </span>
            </div>
            <h3 className="font-semibold text-gray-900">Total Players</h3>
            <p className="text-sm text-gray-600">Active this {selectedPeriod}</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <TrendingUp className="w-8 h-8 text-green-600" />
              <span className="text-2xl font-bold text-green-600">
                {leaderboardData.current_user_rank ? `#${leaderboardData.current_user_rank}` : 'N/A'}
              </span>
            </div>
            <h3 className="font-semibold text-gray-900">Current Rank</h3>
            <p className="text-sm text-gray-600">This {selectedPeriod}</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Star className="w-8 h-8 text-purple-600" />
              <span className="text-2xl font-bold text-purple-600">
                {formatCurrency(leaderboardData.stats.current_user_points)}
              </span>
            </div>
            <h3 className="font-semibold text-gray-900">Profit</h3>
            <p className="text-sm text-gray-600">Current total</p>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200">
          <div className="p-6 border-b border-gray-200">
            <h2 className="text-xl font-semibold">Top Performers</h2>
          </div>
          
          <div className="p-6">
            {leaderboardData.leaderboard.length === 0 ? (
              <div className="text-center py-12">
                <Users className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                <p className="text-gray-500 text-lg mb-2">No active players yet</p>
                <p className="text-gray-400">Be the first to place some bets and climb the leaderboard!</p>
              </div>
            ) : (
              <div className="space-y-4">
                {leaderboardData.leaderboard.map((user) => (
                  <div
                    key={user.user_id}
                    className={`flex items-center justify-between p-4 rounded-lg ${
                      user.is_current_user ? 'bg-blue-50 border border-blue-200' : 'bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center space-x-4">
                      <div className="flex items-center justify-center w-10 h-10">
                        {getRankIcon(user.rank)}
                      </div>
                      <div>
                        <div className={`font-semibold ${user.is_current_user ? 'text-blue-900' : 'text-gray-900'}`}>
                          {user.username}
                          {user.is_current_user && <span className="ml-2 text-sm text-blue-600">(You)</span>}
                        </div>
                        <div className="text-sm text-gray-500">
                          Rank #{user.rank} • {user.total_bets} bets
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center space-x-8 text-right">
                      <div>
                        <div className={`font-semibold ${user.profit >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                          {formatCurrency(user.profit)}
                        </div>
                        <div className="text-xs text-gray-500">Profit</div>
                      </div>
                      <div>
                        <div className="font-semibold">{user.win_rate}%</div>
                        <div className="text-xs text-gray-500">Win Rate</div>
                      </div>
                      <div>
                        <div className={`font-semibold ${user.roi >= 0 ? 'text-blue-600' : 'text-red-600'}`}>
                          {user.roi >= 0 ? '+' : ''}{user.roi}%
                        </div>
                        <div className="text-xs text-gray-500">ROI</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}