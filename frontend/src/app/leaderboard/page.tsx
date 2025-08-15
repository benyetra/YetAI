'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { Trophy, Medal, Crown, TrendingUp, Users, Star } from 'lucide-react';

export default function LeaderboardPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();
  const [selectedPeriod, setSelectedPeriod] = useState('weekly');

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

  const mockLeaderboard = [
    { rank: 1, name: 'BetMaster2024', profit: '+$3,245', winRate: '78%', roi: '22.5%' },
    { rank: 2, name: 'SportsPro', profit: '+$2,890', winRate: '74%', roi: '18.9%' },
    { rank: 3, name: 'AnalyticsKing', profit: '+$2,567', winRate: '71%', roi: '17.2%' },
    { rank: 4, name: 'LuckyStreak', profit: '+$2,234', winRate: '69%', roi: '15.8%' },
    { rank: 5, name: 'DataDriven', profit: '+$1,998', winRate: '67%', roi: '14.3%' },
  ];

  const getRankIcon = (rank: number) => {
    switch (rank) {
      case 1: return <Crown className="w-6 h-6 text-yellow-500" />;
      case 2: return <Medal className="w-6 h-6 text-gray-400" />;
      case 3: return <Medal className="w-6 h-6 text-amber-600" />;
      default: return <span className="w-6 h-6 flex items-center justify-center text-gray-500 font-bold">{rank}</span>;
    }
  };

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
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="alltime">All Time</option>
          </select>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Trophy className="w-8 h-8 text-yellow-500" />
              <span className="text-2xl font-bold text-yellow-500">#1</span>
            </div>
            <h3 className="font-semibold text-gray-900">Your Best Rank</h3>
            <p className="text-sm text-gray-600">Last month</p>
          </div>
          
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Users className="w-8 h-8 text-blue-600" />
              <span className="text-2xl font-bold text-blue-600">2,847</span>
            </div>
            <h3 className="font-semibold text-gray-900">Total Players</h3>
            <p className="text-sm text-gray-600">Active this week</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <TrendingUp className="w-8 h-8 text-green-600" />
              <span className="text-2xl font-bold text-green-600">#47</span>
            </div>
            <h3 className="font-semibold text-gray-900">Current Rank</h3>
            <p className="text-sm text-gray-600">This week</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Star className="w-8 h-8 text-purple-600" />
              <span className="text-2xl font-bold text-purple-600">1,250</span>
            </div>
            <h3 className="font-semibold text-gray-900">Points</h3>
            <p className="text-sm text-gray-600">Current total</p>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200">
          <div className="p-6 border-b border-gray-200">
            <h2 className="text-xl font-semibold">Top Performers</h2>
          </div>
          
          <div className="p-6">
            <div className="space-y-4">
              {mockLeaderboard.map((user) => (
                <div key={user.rank} className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
                  <div className="flex items-center space-x-4">
                    <div className="flex items-center justify-center w-10 h-10">
                      {getRankIcon(user.rank)}
                    </div>
                    <div>
                      <div className="font-semibold text-gray-900">{user.name}</div>
                      <div className="text-sm text-gray-500">Rank #{user.rank}</div>
                    </div>
                  </div>
                  
                  <div className="flex items-center space-x-8 text-right">
                    <div>
                      <div className="font-semibold text-green-600">{user.profit}</div>
                      <div className="text-xs text-gray-500">Profit</div>
                    </div>
                    <div>
                      <div className="font-semibold">{user.winRate}</div>
                      <div className="text-xs text-gray-500">Win Rate</div>
                    </div>
                    <div>
                      <div className="font-semibold text-blue-600">{user.roi}</div>
                      <div className="text-xs text-gray-500">ROI</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <div className="flex items-center justify-center w-10 h-10 bg-blue-100 rounded-full">
                    <span className="font-bold text-blue-600">47</span>
                  </div>
                  <div>
                    <div className="font-semibold text-gray-900">You</div>
                    <div className="text-sm text-gray-500">Your current position</div>
                  </div>
                </div>
                
                <div className="flex items-center space-x-8 text-right">
                  <div>
                    <div className="font-semibold text-green-600">+$487</div>
                    <div className="text-xs text-gray-500">Profit</div>
                  </div>
                  <div>
                    <div className="font-semibold">64%</div>
                    <div className="text-xs text-gray-500">Win Rate</div>
                  </div>
                  <div>
                    <div className="font-semibold text-blue-600">12.3%</div>
                    <div className="text-xs text-gray-500">ROI</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}