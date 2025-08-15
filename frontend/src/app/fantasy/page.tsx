'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { Trophy, Users, TrendingUp, Star } from 'lucide-react';

export default function FantasyPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();
  const [selectedSport, setSelectedSport] = useState('nfl');

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

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold text-gray-900">Fantasy Sports</h1>
          <select
            value={selectedSport}
            onChange={(e) => setSelectedSport(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="nfl">NFL</option>
            <option value="nba">NBA</option>
            <option value="mlb">MLB</option>
            <option value="nhl">NHL</option>
          </select>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Trophy className="w-8 h-8 text-yellow-600" />
              <span className="text-2xl font-bold text-yellow-600">7</span>
            </div>
            <h3 className="font-semibold text-gray-900">Contests Won</h3>
            <p className="text-sm text-gray-600">This season</p>
          </div>
          
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Users className="w-8 h-8 text-blue-600" />
              <span className="text-2xl font-bold text-blue-600">23</span>
            </div>
            <h3 className="font-semibold text-gray-900">Active Lineups</h3>
            <p className="text-sm text-gray-600">This week</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <TrendingUp className="w-8 h-8 text-green-600" />
              <span className="text-2xl font-bold text-green-600">+15%</span>
            </div>
            <h3 className="font-semibold text-gray-900">ROI</h3>
            <p className="text-sm text-gray-600">Last 30 days</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Star className="w-8 h-8 text-purple-600" />
              <span className="text-2xl font-bold text-purple-600">892</span>
            </div>
            <h3 className="font-semibold text-gray-900">Rank</h3>
            <p className="text-sm text-gray-600">Overall leaderboard</p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-xl font-semibold mb-4">AI Lineup Optimizer</h2>
            <div className="text-center py-12 text-gray-500">
              <Star className="w-12 h-12 mx-auto mb-4 text-gray-300" />
              <p>Lineup optimization coming soon</p>
              <p className="text-sm">AI will help you build winning lineups</p>
            </div>
          </div>

          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-xl font-semibold mb-4">Player Projections</h2>
            <div className="text-center py-12 text-gray-500">
              <TrendingUp className="w-12 h-12 mx-auto mb-4 text-gray-300" />
              <p>Projections coming soon</p>
              <p className="text-sm">Get AI-powered player performance predictions</p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}