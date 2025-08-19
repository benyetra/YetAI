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
  Activity,
  Wifi,
  WifiOff,
  X,
  Eye,
  Share2
} from 'lucide-react';
import { useAuth } from './Auth';
import { apiClient } from '@/lib/api';
import { useWebSocket } from '@/hooks/useWebSocket';
import BetShareModal from './BetShareModal';

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
  // Additional game details for better display
  home_team?: string;
  away_team?: string;
  sport?: string;
  commence_time?: string;
  // Parlay-specific fields
  total_odds?: number;
  leg_count?: number;
  legs?: any[];
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

interface ParlayLeg {
  id: string;
  game_id: string;
  bet_type: string;
  selection: string;
  odds: number;
  status: string;
  home_team?: string;
  away_team?: string;
  sport?: string;
}

interface ParlayDetails {
  id: string;
  amount: number;
  potential_win: number;
  status: string;
  placed_at: string;
  settled_at?: string;
  result_amount?: number;
  legs: ParlayLeg[];
  leg_count: number;
  total_odds: number;
}

const BetHistory: React.FC = () => {
  const { user, token } = useAuth();
  const { isConnected } = useWebSocket();
  const [bets, setBets] = useState<Bet[]>([]);
  const [liveBets, setLiveBets] = useState<any[]>([]);
  const [stats, setStats] = useState<BetStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterBetType, setFilterBetType] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [showStats, setShowStats] = useState(true);
  const [selectedParlay, setSelectedParlay] = useState<ParlayDetails | null>(null);
  const [parlayModalLoading, setParlayModalLoading] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [selectedBetForShare, setSelectedBetForShare] = useState<Bet | null>(null);

  useEffect(() => {
    if (user && token) {
      fetchBetHistory();
      fetchLiveBets();
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

  const fetchLiveBets = async () => {
    try {
      const response = await apiClient.get('/api/live-bets/active?include_settled=true', token);
      if (response.status === 'success') {
        setLiveBets(response.bets || []);
      }
    } catch (error) {
      console.error('Error fetching live bets:', error);
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

  const fetchParlayDetails = async (parlayId: string) => {
    try {
      setParlayModalLoading(true);
      const response = await fetch(`http://localhost:8000/api/bets/parlay/${parlayId}`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      const result = await response.json();
      
      if (result.status === 'success') {
        setSelectedParlay(result.parlay);
      } else {
        console.error('Failed to fetch parlay details:', result.detail);
      }
    } catch (error) {
      console.error('Error fetching parlay details:', error);
    } finally {
      setParlayModalLoading(false);
    }
  };

  const handleParlayClick = (parlayId: string) => {
    fetchParlayDetails(parlayId);
  };

  const closeModal = () => {
    setSelectedParlay(null);
  };

  const openShareModal = (bet: Bet) => {
    setSelectedBetForShare(bet);
    setShareModalOpen(true);
  };

  const closeShareModal = () => {
    setSelectedBetForShare(null);
    setShareModalOpen(false);
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'won':
        return <CheckCircle className="w-5 h-5 text-green-600" />;
      case 'lost':
        return <XCircle className="w-5 h-5 text-red-600" />;
      case 'pending':
        return <Clock className="w-5 h-5 text-yellow-600" />;
      case 'live':
        return <Activity className="w-5 h-5 text-green-500" />;
      case 'cashed_out':
        return <DollarSign className="w-5 h-5 text-blue-600" />;
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
      case 'live':
        return 'bg-green-100 text-green-800';
      case 'cashed_out':
        return 'bg-blue-100 text-blue-800';
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
    if (isNaN(odds) || odds === null || odds === undefined) {
      return 'N/A';
    }
    const roundedOdds = Math.round(odds);
    return roundedOdds > 0 ? `+${roundedOdds}` : `${roundedOdds}`;
  };

  const formatBetTitle = (bet: Bet) => {
    // Handle parlay bets specially
    if (bet.bet_type === 'parlay') {
      const legCount = bet.leg_count || bet.legs?.length || 0;
      return `${legCount}-Leg Parlay`;
    }
    
    // If we have team information, show a proper game description
    if (bet.home_team && bet.away_team) {
      const gameInfo = `${bet.away_team} @ ${bet.home_team}`;
      
      if (bet.bet_type === 'moneyline') {
        const team = bet.selection === 'home' ? bet.home_team : bet.away_team;
        return `${team} to Win (${gameInfo})`;
      } else if (bet.bet_type === 'spread') {
        const team = bet.selection === 'home' ? bet.home_team : bet.away_team;
        return `${team} Spread (${gameInfo})`;
      } else if (bet.bet_type === 'total') {
        return `${(bet.selection || '').toUpperCase()} (${gameInfo})`;
      }
    }
    
    // Fallback to generic description
    return `${(bet.bet_type || 'BET').toUpperCase()} - ${(bet.selection || 'UNKNOWN').toUpperCase()}`;
  };

  const formatBetSubtitle = (bet: Bet) => {
    const parts = [];
    
    if (bet.sport) {
      parts.push(bet.sport);
    }
    
    if (bet.commence_time) {
      const gameTime = new Date(bet.commence_time).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
      parts.push(gameTime);
    }
    
    return parts.join(' • ');
  };

  // Convert live bets to the same format as regular bets for display
  const normalizedLiveBets = liveBets.map(liveBet => ({
    id: liveBet.id,
    user_id: liveBet.user_id,
    game_id: liveBet.game_id,
    bet_type: `live_${liveBet.bet_type}`, // Mark as live bet
    selection: liveBet.selection,
    odds: liveBet.original_odds,
    amount: liveBet.amount,
    potential_win: liveBet.potential_win,
    status: liveBet.status,
    placed_at: liveBet.placed_at,
    settled_at: liveBet.settled_at,
    result_amount: liveBet.result_amount,
    parlay_id: null,
    // Additional live bet fields for display
    current_odds: liveBet.current_odds,
    cash_out_value: liveBet.cash_out_value,
    cash_out_available: liveBet.cash_out_available
  }));

  // Combine regular bets and live bets
  const allBets = [...bets, ...normalizedLiveBets];

  const filteredBets = allBets.filter(bet => {
    // Status filter
    if (filterStatus !== 'all' && bet.status !== filterStatus) {
      return false;
    }
    
    // Bet type filter (handle live bet prefixes)
    if (filterBetType !== 'all') {
      const betType = bet.bet_type.replace('live_', '');
      if (betType !== filterBetType) {
        return false;
      }
    }
    
    // Search filter
    if (searchTerm) {
      return (bet.selection || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
             (bet.bet_type || '').toLowerCase().includes(searchTerm.toLowerCase());
    }
    
    return true;
  }).sort((a, b) => new Date(b.placed_at).getTime() - new Date(a.placed_at).getTime());

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
                <div 
                  key={bet.id} 
                  className={`p-6 transition-colors ${
                    bet.bet_type === 'parlay' ? 'hover:bg-gray-50 cursor-pointer' : 'hover:bg-gray-50'
                  }`}
                  onClick={() => bet.bet_type === 'parlay' && handleParlayClick(bet.id)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center space-x-3 mb-2">
                        {getStatusIcon(bet.status)}
                        <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(bet.status)}`}>
                          {bet.status.charAt(0).toUpperCase() + bet.status.slice(1)}
                        </span>
                        <span className="text-sm text-gray-500 capitalize">
                          {bet.bet_type.replace('live_', '')}
                        </span>
                        {bet.bet_type.startsWith('live_') && (
                          <span className="px-2 py-1 bg-red-100 text-red-800 rounded-full text-xs font-medium flex items-center space-x-1">
                            <Activity className="w-3 h-3" />
                            <span>Live</span>
                          </span>
                        )}
                        {bet.bet_type === 'parlay' && (
                          <span className="px-2 py-1 bg-purple-100 text-purple-800 rounded-full text-xs font-medium flex items-center space-x-1">
                            <Layers className="w-3 h-3" />
                            <span>Parlay</span>
                            <Eye className="w-3 h-3" />
                          </span>
                        )}
                      </div>
                      
                      <h3 className="text-lg font-medium text-gray-900 mb-1">
                        {formatBetTitle(bet)}
                      </h3>
                      
                      {formatBetSubtitle(bet) && (
                        <p className="text-sm text-gray-500 mb-2">{formatBetSubtitle(bet)}</p>
                      )}
                      
                      <div className="flex items-center space-x-4 text-sm text-gray-600">
                        <span>Odds: {formatOdds(bet.bet_type === 'parlay' ? bet.total_odds : bet.odds)}</span>
                        <span>•</span>
                        <span>{formatDate(bet.placed_at)}</span>
                        {bet.game_id && (
                          <>
                            <span>•</span>
                            <span>Game: {bet.game_id}</span>
                          </>
                        )}
                      </div>
                      
                      {bet.bet_type === 'parlay' && (
                        <p className="text-sm text-blue-600 mt-2">
                          Click to view parlay details
                        </p>
                      )}
                    </div>
                    
                    <div className="text-right">
                      <div className="flex items-center justify-end space-x-2 mb-2">
                        <button
                          onClick={() => openShareModal(bet)}
                          className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                          title="Share this bet"
                        >
                          <Share2 className="w-4 h-4" />
                        </button>
                      </div>
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
                // TODO: Add load more functionality
              }}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
            >
              Load More
            </button>
          </div>
        )}
        
        {/* Parlay Details Modal */}
        {selectedParlay && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg max-w-2xl w-full max-h-[90vh] overflow-y-auto">
              <div className="sticky top-0 bg-white border-b border-gray-200 p-6 flex items-center justify-between">
                <h2 className="text-2xl font-bold text-gray-900">Parlay Details</h2>
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => openShareModal({
                      ...selectedParlay,
                      bet_type: 'parlay',
                      selection: `Parlay (${selectedParlay.leg_count} legs)`,
                      odds: selectedParlay.total_odds,
                      legs: selectedParlay.legs
                    })}
                    className="p-2 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                    title="Share this parlay"
                  >
                    <Share2 className="w-5 h-5" />
                  </button>
                  <button
                    onClick={closeModal}
                    className="text-gray-400 hover:text-gray-600"
                  >
                    <X className="w-6 h-6" />
                  </button>
                </div>
              </div>
              
              {parlayModalLoading ? (
                <div className="p-8 text-center">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
                  <p className="mt-2 text-gray-600">Loading parlay details...</p>
                </div>
              ) : (
                <div className="p-6">
                  {/* Parlay Header */}
                  <div className="bg-gray-50 rounded-lg p-4 mb-6">
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center space-x-3">
                        <div className="flex items-center space-x-2">
                          {getStatusIcon(selectedParlay.status)}
                          <span className={`px-2 py-1 text-xs font-medium rounded-full ${getStatusColor(selectedParlay.status)}`}>
                            {selectedParlay.status.charAt(0).toUpperCase() + selectedParlay.status.slice(1)}
                          </span>
                        </div>
                        <span className="text-sm text-gray-500">
                          {selectedParlay.leg_count} Leg Parlay
                        </span>
                      </div>
                      <div className="text-right">
                        <div className="text-sm text-gray-500">
                          {formatDate(selectedParlay.placed_at)}
                        </div>
                      </div>
                    </div>
                    
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div>
                        <p className="text-xs text-gray-500 mb-1">Bet Amount</p>
                        <p className="text-sm font-semibold">${selectedParlay.amount.toFixed(2)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500 mb-1">Parlay Odds</p>
                        <p className="text-sm font-mono">{formatOdds(selectedParlay.total_odds)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500 mb-1">Potential Win</p>
                        <p className="text-sm font-semibold text-green-600">
                          ${selectedParlay.potential_win.toFixed(2)}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500 mb-1">
                          {selectedParlay.status === 'won' ? 'Won' : selectedParlay.status === 'lost' ? 'Lost' : 'Potential Payout'}
                        </p>
                        <p className={`text-sm font-semibold ${
                          selectedParlay.status === 'won' ? 'text-green-600' : 
                          selectedParlay.status === 'lost' ? 'text-red-600' : 
                          'text-blue-600'
                        }`}>
                          ${(
                            selectedParlay.status === 'won' ? (selectedParlay.result_amount || selectedParlay.potential_win) :
                            selectedParlay.status === 'lost' ? 0 :
                            selectedParlay.potential_win + selectedParlay.amount
                          ).toFixed(2)}
                        </p>
                      </div>
                    </div>
                  </div>
                  
                  {/* Parlay Legs */}
                  <div className="space-y-3">
                    <h3 className="text-lg font-semibold text-gray-900 mb-4">Legs</h3>
                    {selectedParlay.legs.map((leg, index) => (
                      <div key={leg.id || index} className="border border-gray-200 rounded-lg p-4">
                        <div className="flex items-center justify-between">
                          <div className="flex-1">
                            <div className="flex items-center space-x-2 mb-1">
                              <span className="text-sm font-medium">{leg.selection}</span>
                              <span className={`px-1.5 py-0.5 text-xs rounded ${getStatusColor(leg.status)}`}>
                                {leg.status}
                              </span>
                            </div>
                            <p className="text-xs text-gray-500 capitalize">{leg.bet_type}</p>
                            {(leg.home_team && leg.away_team) ? (
                              <p className="text-xs text-gray-400">{leg.away_team} @ {leg.home_team}</p>
                            ) : leg.game_id ? (
                              <p className="text-xs text-gray-400">Game: {leg.game_id}</p>
                            ) : null}
                          </div>
                          <div className="text-right">
                            <span className="text-sm font-mono">{formatOdds(leg.odds)}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                  
                  {selectedParlay.settled_at && (
                    <div className="mt-6 pt-4 border-t border-gray-200">
                      <p className="text-xs text-gray-500">
                        Settled on {formatDate(selectedParlay.settled_at)}
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Bet Share Modal */}
        {selectedBetForShare && (
          <BetShareModal
            bet={selectedBetForShare}
            isOpen={shareModalOpen}
            onClose={closeShareModal}
          />
        )}
      </div>
    </div>
  );
};

export default BetHistory;