'use client';

import React, { useState, useEffect } from 'react';
import { 
  Calendar, 
  TrendingUp, 
  TrendingDown, 
  Clock, 
  CheckCircle, 
  XCircle, 
  DollarSign,
  Filter,
  Search,
  Trophy,
  Target,
  BarChart3,
  Download,
  RefreshCw,
  Layers,
  AlertCircle,
  Wifi,
  WifiOff
} from 'lucide-react';
import { useAuth } from './Auth';
import { apiClient } from '@/lib/api';
import { useWebSocket } from '@/hooks/useWebSocket';

interface Bet {
  id: string;
  user_id: number;
  game_id: string | null;
  bet_type: string;
  selection: string;
  odds: number;
  amount: number;
  potential_win: number;
  status: string;
  placed_at: string;
  settled_at: string | null;
  result_amount: number | null;
  parlay_id: string | null;
}

interface BetStats {
  total_bets: number;
  total_wagered: number;
  total_won: number;
  total_lost: number;
  net_profit: number;
  win_rate: number;
  average_bet: number;
  average_odds: number;
  best_win: number;
  worst_loss: number;
  current_streak: number;
  longest_win_streak: number;
  longest_loss_streak: number;
}

const BetHistory: React.FC = () => {
  const { user, token } = useAuth();
  const { isConnected } = useWebSocket();
  const [bets, setBets] = useState<Bet[]>([]);
  const [stats, setStats] = useState<BetStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterBetType, setFilterBetType] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [showStats, setShowStats] = useState(true);

  useEffect(() => {
    if (user && token) {
      fetchBetHistory();
      fetchBetStats();
    }
  }, [user, token, filterStatus, filterBetType]);

  const fetchBetHistory = async () => {
    try {
      setLoading(true);
      const filters: any = {
        limit: 50,
        offset: 0
      };

      if (filterStatus !== 'all') {
        filters.status = filterStatus;
      }
      if (filterBetType !== 'all') {
        filters.bet_type = filterBetType;
      }

      const response = await apiClient.post('/api/bets/history', filters, token);
      if (response.status === 'success') {
        setBets(response.bets);
      }
    } catch (error) {
      console.error('Error fetching bet history:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchBetStats = async () => {
    try {
      const response = await apiClient.get('/api/bets/stats', token);
      if (response.status === 'success') {
        setStats(response.stats);
      }
    } catch (error) {
      console.error('Error fetching bet stats:', error);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'won':
        return <CheckCircle className="w-5 h-5 text-green-600" />;
      case 'lost':
        return <XCircle className="w-5 h-5 text-red-600" />;
      case 'pending':
        return <Clock className="w-5 h-5 text-yellow-600" />;
      case 'cancelled':
        return <XCircle className="w-5 h-5 text-gray-600" />;
      default:
        return <Clock className="w-5 h-5 text-gray-600" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'won':
        return 'bg-green-100 text-green-800';
      case 'lost':
        return 'bg-red-100 text-red-800';
      case 'pending':
        return 'bg-yellow-100 text-yellow-800';
      case 'cancelled':
        return 'bg-gray-100 text-gray-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const formatOdds = (odds: number) => {
    return odds > 0 ? `+${odds}` : `${odds}`;
  };

  const filteredBets = bets.filter(bet => {
    if (searchTerm) {
      return bet.selection.toLowerCase().includes(searchTerm.toLowerCase()) ||
             bet.bet_type.toLowerCase().includes(searchTerm.toLowerCase());
    }
    return true;
  });

  const StatCard: React.FC<{
    title: string;
    value: string | number;
    icon: React.ReactNode;
    trend?: 'up' | 'down' | 'neutral';
    subtitle?: string;
  }> = ({ title, value, icon, trend, subtitle }) => (
    <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-gray-600">{title}</p>
          <p className="text-2xl font-bold text-gray-900 mt-2">{value}</p>
          {subtitle && (
            <p className="text-sm text-gray-500 mt-1">{subtitle}</p>
          )}
        </div>
        <div className={`p-2 rounded-lg ${
          trend === 'up' ? 'bg-green-50' : 
          trend === 'down' ? 'bg-red-50' : 'bg-blue-50'
        }`}>
          {icon}
        </div>
      </div>
    </div>
  );

  if (loading && bets.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-lg">Loading bet history...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center space-x-3">
            <h1 className="text-3xl font-bold text-gray-900">Bet History</h1>
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
          <p className="text-gray-600 mt-2">Track your betting performance and statistics</p>
        </div>

        {/* Stats Grid */}
        {stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            <StatCard
              title="Total Bets"
              value={stats.total_bets}
              icon={<Target className="w-6 h-6 text-blue-600" />}
            />
            <StatCard
              title="Win Rate"
              value={`${stats.win_rate}%`}
              icon={<Trophy className="w-6 h-6 text-green-600" />}
              trend={stats.win_rate >= 50 ? 'up' : 'down'}
            />
            <StatCard
              title="Net Profit"
              value={`$${stats.net_profit}`}
              icon={<DollarSign className="w-6 h-6 text-green-600" />}
              trend={stats.net_profit >= 0 ? 'up' : 'down'}
            />
            <StatCard
              title="Current Streak"
              value={Math.abs(stats.current_streak)}
              icon={<BarChart3 className="w-6 h-6 text-purple-600" />}
              subtitle={stats.current_streak >= 0 ? 'Win streak' : 'Loss streak'}
              trend={stats.current_streak >= 0 ? 'up' : 'down'}
            />
          </div>
        )}

        {/* Filters and Search */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
            <div className="flex-1 max-w-md">
              <div className="relative">
                <Search className="w-5 h-5 text-gray-400 absolute left-3 top-1/2 transform -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Search bets..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            </div>
            
            <button
              onClick={() => setShowFilters(!showFilters)}
              className="flex items-center space-x-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              <Filter className="w-4 h-4" />
              <span>Filters</span>
            </button>
          </div>

          {showFilters && (
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4 pt-4 border-t border-gray-200">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Status</label>
                <select
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="all">All Statuses</option>
                  <option value="pending">Pending</option>
                  <option value="won">Won</option>
                  <option value="lost">Lost</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Bet Type</label>
                <select
                  value={filterBetType}
                  onChange={(e) => setFilterBetType(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="all">All Types</option>
                  <option value="moneyline">Moneyline</option>
                  <option value="spread">Spread</option>
                  <option value="total">Total</option>
                  <option value="parlay">Parlay</option>
                </select>
              </div>
            </div>
          )}
        </div>

        {/* Bet List */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Recent Bets</h2>
          </div>
          
          {filteredBets.length === 0 ? (
            <div className="p-12 text-center">
              <Trophy className="w-12 h-12 text-gray-400 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-2">No bets found</h3>
              <p className="text-gray-500">
                {searchTerm || filterStatus !== 'all' || filterBetType !== 'all'
                  ? 'Try adjusting your search or filters'
                  : 'Start placing bets to see your history here'
                }
              </p>
            </div>
          ) : (
            <div className="divide-y divide-gray-200">
              {filteredBets.map((bet) => (
                <div key={bet.id} className="p-6 hover:bg-gray-50 transition-colors">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center space-x-3 mb-2">
                        {getStatusIcon(bet.status)}
                        <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(bet.status)}`}>
                          {bet.status.charAt(0).toUpperCase() + bet.status.slice(1)}
                        </span>
                        <span className="text-sm text-gray-500 capitalize">
                          {bet.bet_type}
                        </span>
                        {bet.parlay_id && (
                          <span className="px-2 py-1 bg-purple-100 text-purple-800 rounded-full text-xs font-medium">
                            Parlay
                          </span>
                        )}
                      </div>
                      
                      <h3 className="text-lg font-medium text-gray-900 mb-1">
                        {bet.selection}
                      </h3>
                      
                      <div className="flex items-center space-x-4 text-sm text-gray-600">
                        <span>Odds: {formatOdds(bet.odds)}</span>
                        <span>•</span>
                        <span>{formatDate(bet.placed_at)}</span>
                        {bet.game_id && (
                          <>
                            <span>•</span>
                            <span>Game: {bet.game_id}</span>
                          </>
                        )}
                      </div>
                    </div>
                    
                    <div className="text-right">
                      <p className="text-lg font-semibold text-gray-900">
                        ${bet.amount.toFixed(2)}
                      </p>
                      <p className="text-sm text-gray-500">
                        Potential: ${bet.potential_win.toFixed(2)}
                      </p>
                      {bet.result_amount !== null && (
                        <p className={`text-sm font-medium ${
                          bet.status === 'won' ? 'text-green-600' : 'text-red-600'
                        }`}>
                          {bet.status === 'won' ? '+' : '-'}${Math.abs(bet.result_amount || bet.amount).toFixed(2)}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Load More Button */}
        {filteredBets.length >= 50 && (
          <div className="mt-6 text-center">
            <button
              onClick={() => {
                // Implement load more functionality
                console.log('Load more bets');
              }}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
            >
              Load More
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default BetHistory;