'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { BarChart3, TrendingUp, TrendingDown, DollarSign, Target, Calendar, Info } from 'lucide-react';
import { sportsAPI } from '@/lib/api';

interface PerformanceData {
  status: string;
  period_days: number;
  overview: {
    total_bets: number;
    total_wagered: number;
    total_profit: number;
    win_rate: number;
    roi: number;
    won_bets: number;
    lost_bets: number;
    pending_bets: number;
  };
  sport_breakdown: Array<{
    sport: string;
    sport_name: string;
    total_bets: number;
    total_wagered: number;
    profit_loss: number;
    win_rate: number;
    roi: number;
  }>;
  bet_type_breakdown: Array<{
    bet_type: string;
    bet_type_name: string;
    total_bets: number;
    total_wagered: number;
    profit_loss: number;
    win_rate: number;
    roi: number;
  }>;
  performance_trend: {
    recent_period: {
      win_rate: number;
      profit: number;
      total_bets: number;
    };
    previous_period: {
      win_rate: number;
      profit: number;
      total_bets: number;
    };
    win_rate_change: number;
    profit_change: number;
    trend_direction: string;
  };
  insights: Array<{
    type: string;
    icon: string;
    message: string;
  }>;
}

export default function PerformancePage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  const [performanceData, setPerformanceData] = useState<PerformanceData | null>(null);
  const [isLoadingData, setIsLoadingData] = useState(true);
  const [selectedPeriod, setSelectedPeriod] = useState(30);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchPerformanceData();
    }
  }, [isAuthenticated, selectedPeriod]);

  const fetchPerformanceData = async () => {
    try {
      setIsLoadingData(true);
      setError('');
      
      const token = localStorage.getItem('auth_token');
      const response = await sportsAPI.getUserPerformance(selectedPeriod, token);

      console.log('Performance API response:', response);
      console.log('Overview data:', response?.overview);

      if (response.status === 'success') {
        // Transform the API response to match expected format
        const transformedData = {
          status: response.status,
          period_days: response.metrics?.period_days || 30,
          overview: {
            total_bets: response.metrics?.total_predictions || 0,
            total_wagered: response.metrics?.total_wagered || 0,
            total_profit: response.metrics?.net_profit || 0,
            win_rate: Math.round(response.metrics?.overall_accuracy || 0),
            roi: response.metrics?.total_wagered > 0 ? Math.round((response.metrics?.net_profit / response.metrics?.total_wagered) * 100) : 0,
            won_bets: Math.round((response.metrics?.resolved_predictions || 0) * (response.metrics?.success_rate || 0)),
            lost_bets: (response.metrics?.resolved_predictions || 0) - Math.round((response.metrics?.resolved_predictions || 0) * (response.metrics?.success_rate || 0)),
            pending_bets: response.metrics?.pending_predictions || 0
          },
          sport_breakdown: response.metrics?.by_sport ? Object.entries(response.metrics.by_sport).map(([sport, data]: [string, any]) => ({
            sport: sport,
            sport_name: sport.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
            total_bets: data.count || 0,
            total_wagered: data.total_wagered || 0,
            profit_loss: data.net_profit || 0,
            win_rate: Math.round(data.win_rate || 0),
            roi: data.total_wagered > 0 ? Math.round((data.net_profit / data.total_wagered) * 100) : 0
          })) : [],
          bet_type_breakdown: response.metrics?.by_type ? Object.entries(response.metrics.by_type).map(([type, data]: [string, any]) => ({
            bet_type: type,
            bet_type_name: type.charAt(0).toUpperCase() + type.slice(1),
            total_bets: data.count || 0,
            total_wagered: data.total_wagered || 0,
            profit_loss: data.net_profit || 0,
            win_rate: Math.round(data.win_rate || 0),
            roi: data.total_wagered > 0 ? Math.round((data.net_profit / data.total_wagered) * 100) : 0
          })) : [],
          performance_trend: response.metrics?.trends ? {
            recent_period: {
              win_rate: Math.round(response.metrics.trends.last_7_days_accuracy || 0),
              profit: 0,
              total_bets: 0
            },
            previous_period: {
              win_rate: 0,
              profit: 0,
              total_bets: 0
            },
            win_rate_change: 0,
            profit_change: 0,
            trend_direction: response.metrics.trends.improvement_trend || 'stable'
          } : null,
          insights: []
        };

        console.log('Transformed data:', transformedData);
        setPerformanceData(transformedData);
      } else {
        setError('Failed to load performance data');
      }
    } catch (error) {
      console.error('Error fetching performance data:', error);
      setError('Failed to load performance data');
    } finally {
      setIsLoadingData(false);
    }
  };

  const getIconComponent = (iconName: string) => {
    switch (iconName) {
      case 'trending-up': return TrendingUp;
      case 'trending-down': return TrendingDown;
      case 'target': return Target;
      case 'info': return Info;
      default: return Info;
    }
  };

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2
    }).format(amount);
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

  if (error || !performanceData) {
    return (
      <Layout requiresAuth>
        <div className="space-y-6">
          <h1 className="text-3xl font-bold text-gray-900">Performance Analytics</h1>
          
          {error ? (
            <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
              <p className="text-red-600 mb-4">{error}</p>
              <button 
                onClick={fetchPerformanceData}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
              >
                Try Again
              </button>
            </div>
          ) : (
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-12 text-center">
              <BarChart3 className="w-16 h-16 mx-auto mb-4 text-gray-300" />
              <h3 className="text-xl font-semibold text-gray-600 mb-2">No Betting Data Yet</h3>
              <p className="text-gray-500 mb-6">Start placing bets to see your performance analytics</p>
              <button 
                onClick={() => router.push('/odds')}
                className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                View Live Odds
              </button>
            </div>
          )}
        </div>
      </Layout>
    );
  }

  const { overview, sport_breakdown, bet_type_breakdown, performance_trend, insights } = performanceData;

  // Add safety checks for overview data
  if (!overview) {
    return (
      <Layout requiresAuth>
        <div className="space-y-6">
          <h1 className="text-3xl font-bold text-gray-900">Performance Analytics</h1>
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6 text-center">
            <p className="text-yellow-600 mb-4">Performance data is incomplete</p>
            <button
              onClick={fetchPerformanceData}
              className="px-4 py-2 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 transition-colors"
            >
              Reload Data
            </button>
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold text-gray-900">Performance Analytics</h1>
          <div className="flex items-center space-x-2">
            <Calendar className="w-4 h-4 text-gray-500" />
            <select
              value={selectedPeriod}
              onChange={(e) => setSelectedPeriod(Number(e.target.value))}
              className="px-3 py-1 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 3 months</option>
              <option value={365}>All time</option>
            </select>
          </div>
        </div>

        {/* Overview Stats */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Target className={`w-8 h-8 ${(overview.win_rate || 0) >= 70 ? 'text-green-600' : (overview.win_rate || 0) >= 50 ? 'text-yellow-600' : 'text-red-600'}`} />
              <span className={`text-2xl font-bold ${(overview.win_rate || 0) >= 70 ? 'text-green-600' : (overview.win_rate || 0) >= 50 ? 'text-yellow-600' : 'text-red-600'}`}>
                {overview.win_rate || 0}%
              </span>
            </div>
            <h3 className="font-semibold text-gray-900">Prediction Accuracy</h3>
            <p className="text-sm text-gray-600">Overall success rate</p>
          </div>
          
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Target className="w-8 h-8 text-blue-600" />
              <span className="text-2xl font-bold text-blue-600">{overview.win_rate || 0}%</span>
            </div>
            <h3 className="font-semibold text-gray-900">Win Rate</h3>
            <p className="text-sm text-gray-600">{overview.won_bets || 0}W - {overview.lost_bets || 0}L</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <BarChart3 className="w-8 h-8 text-purple-600" />
              <span className="text-2xl font-bold text-purple-600">{overview.total_bets || 0}</span>
            </div>
            <h3 className="font-semibold text-gray-900">Total Predictions</h3>
            <p className="text-sm text-gray-600">Resolved predictions</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <TrendingUp className="w-8 h-8 text-orange-600" />
              <span className="text-2xl font-bold text-orange-600">{overview.pending_bets || 0}</span>
            </div>
            <h3 className="font-semibold text-gray-900">Pending</h3>
            <p className="text-sm text-gray-600">Awaiting results</p>
          </div>
        </div>

        {/* Performance Trend */}
        {performance_trend && (
          <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
            <h2 className="text-xl font-semibold mb-4">Performance Trend</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="text-center">
                <p className="text-sm text-gray-600">Last 7 Days</p>
                <p className="text-lg font-semibold">{performance_trend.recent_period.win_rate}% Win Rate</p>
                <p className={`text-sm ${performance_trend.recent_period.profit >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {formatCurrency(performance_trend.recent_period.profit)}
                </p>
              </div>
              <div className="text-center">
                <p className="text-sm text-gray-600">Previous 7 Days</p>
                <p className="text-lg font-semibold">{performance_trend.previous_period.win_rate}% Win Rate</p>
                <p className={`text-sm ${performance_trend.previous_period.profit >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {formatCurrency(performance_trend.previous_period.profit)}
                </p>
              </div>
              <div className="text-center">
                <p className="text-sm text-gray-600">Trend</p>
                <p className={`text-lg font-semibold capitalize ${
                  performance_trend.trend_direction === 'improving' ? 'text-green-600' : 
                  performance_trend.trend_direction === 'declining' ? 'text-red-600' : 'text-yellow-600'
                }`}>
                  {performance_trend.trend_direction}
                </p>
                <p className="text-sm text-gray-600">
                  {performance_trend.win_rate_change >= 0 ? '+' : ''}{performance_trend.win_rate_change}% change
                </p>
              </div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Sport Breakdown */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-xl font-semibold mb-4">Sport Breakdown</h2>
            {sport_breakdown && sport_breakdown.length > 0 ? (
              <div className="space-y-4">
                {sport_breakdown.slice(0, 5).map((sport, index) => (
                  <div key={sport.sport} className="flex justify-between items-center p-3 bg-gray-50 rounded">
                    <span className="font-medium">{sport.sport_name}</span>
                    <div className="text-right">
                      <div className={`text-sm font-semibold ${sport.profit_loss >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                        {sport.profit_loss >= 0 ? '+' : ''}{formatCurrency(sport.profit_loss)}
                      </div>
                      <div className="text-xs text-gray-500">{sport.win_rate}% win rate</div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500">
                <p>No sport data available yet</p>
                <p className="text-sm">Place bets on different sports to see breakdown</p>
              </div>
            )}
          </div>

          {/* Bet Type Breakdown */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-xl font-semibold mb-4">Bet Type Breakdown</h2>
            {bet_type_breakdown && bet_type_breakdown.length > 0 ? (
              <div className="space-y-4">
                {bet_type_breakdown.slice(0, 5).map((betType, index) => (
                  <div key={betType.bet_type} className="flex justify-between items-center p-3 bg-gray-50 rounded">
                    <span className="font-medium">{betType.bet_type_name}</span>
                    <div className="text-right">
                      <div className={`text-sm font-semibold ${betType.profit_loss >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                        {betType.profit_loss >= 0 ? '+' : ''}{formatCurrency(betType.profit_loss)}
                      </div>
                      <div className="text-xs text-gray-500">{betType.win_rate}% win rate</div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500">
                <p>No bet type data available yet</p>
                <p className="text-sm">Try different bet types to see breakdown</p>
              </div>
            )}
          </div>
        </div>

        {/* Performance Insights */}
        {insights && insights.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-xl font-semibold mb-4">Performance Insights</h2>
            <div className="space-y-3">
              {insights.map((insight, index) => {
                const IconComponent = getIconComponent(insight.icon);
                const bgColor = insight.type === 'positive' ? 'bg-green-50 border-green-200' : 
                               insight.type === 'warning' ? 'bg-yellow-50 border-yellow-200' : 
                               'bg-blue-50 border-blue-200';
                const textColor = insight.type === 'positive' ? 'text-green-800' :
                                 insight.type === 'warning' ? 'text-yellow-800' :
                                 'text-blue-800';
                const iconColor = insight.type === 'positive' ? 'text-green-600' :
                                 insight.type === 'warning' ? 'text-yellow-600' :
                                 'text-blue-600';

                return (
                  <div key={index} className={`flex items-center p-3 border rounded ${bgColor}`}>
                    <IconComponent className={`w-5 h-5 mr-3 ${iconColor}`} />
                    <span className={textColor}>{insight.message}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}