'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { BarChart3, TrendingUp, TrendingDown, DollarSign, Target, Calendar } from 'lucide-react';

export default function PerformancePage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();

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
          <h1 className="text-3xl font-bold text-gray-900">Performance Analytics</h1>
          <div className="flex items-center space-x-2">
            <Calendar className="w-4 h-4 text-gray-500" />
            <select className="px-3 py-1 border border-gray-300 rounded text-sm">
              <option>Last 30 days</option>
              <option>Last 7 days</option>
              <option>This week</option>
              <option>All time</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <DollarSign className="w-8 h-8 text-green-600" />
              <span className="text-2xl font-bold text-green-600">+$1,250</span>
            </div>
            <h3 className="font-semibold text-gray-900">Total Profit</h3>
            <p className="text-sm text-gray-600">Last 30 days</p>
          </div>
          
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Target className="w-8 h-8 text-blue-600" />
              <span className="text-2xl font-bold text-blue-600">68.5%</span>
            </div>
            <h3 className="font-semibold text-gray-900">Win Rate</h3>
            <p className="text-sm text-gray-600">All time</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <TrendingUp className="w-8 h-8 text-purple-600" />
              <span className="text-2xl font-bold text-purple-600">15.3%</span>
            </div>
            <h3 className="font-semibold text-gray-900">ROI</h3>
            <p className="text-sm text-gray-600">Return on investment</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <BarChart3 className="w-8 h-8 text-orange-600" />
              <span className="text-2xl font-bold text-orange-600">156</span>
            </div>
            <h3 className="font-semibold text-gray-900">Total Bets</h3>
            <p className="text-sm text-gray-600">This month</p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-xl font-semibold mb-4">Profit/Loss Chart</h2>
            <div className="text-center py-12 text-gray-500">
              <BarChart3 className="w-12 h-12 mx-auto mb-4 text-gray-300" />
              <p>Performance charts coming soon</p>
              <p className="text-sm">Visualize your betting performance over time</p>
            </div>
          </div>

          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-xl font-semibold mb-4">Sport Breakdown</h2>
            <div className="space-y-4">
              <div className="flex justify-between items-center p-3 bg-gray-50 rounded">
                <span className="font-medium">NFL</span>
                <div className="text-right">
                  <div className="text-sm text-green-600 font-semibold">+$450</div>
                  <div className="text-xs text-gray-500">72% win rate</div>
                </div>
              </div>
              <div className="flex justify-between items-center p-3 bg-gray-50 rounded">
                <span className="font-medium">NBA</span>
                <div className="text-right">
                  <div className="text-sm text-green-600 font-semibold">+$320</div>
                  <div className="text-xs text-gray-500">65% win rate</div>
                </div>
              </div>
              <div className="flex justify-between items-center p-3 bg-gray-50 rounded">
                <span className="font-medium">MLB</span>
                <div className="text-right">
                  <div className="text-sm text-red-600 font-semibold">-$125</div>
                  <div className="text-xs text-gray-500">58% win rate</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-xl font-semibold mb-4">Recent Performance Insights</h2>
          <div className="space-y-3">
            <div className="flex items-center p-3 bg-green-50 border border-green-200 rounded">
              <TrendingUp className="w-5 h-5 text-green-600 mr-3" />
              <span className="text-green-800">Your NFL betting has improved 25% this month</span>
            </div>
            <div className="flex items-center p-3 bg-blue-50 border border-blue-200 rounded">
              <Target className="w-5 h-5 text-blue-600 mr-3" />
              <span className="text-blue-800">Best performance on weekend games (78% win rate)</span>
            </div>
            <div className="flex items-center p-3 bg-yellow-50 border border-yellow-200 rounded">
              <TrendingDown className="w-5 h-5 text-yellow-600 mr-3" />
              <span className="text-yellow-800">Consider reducing bet sizes on underdog picks</span>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}