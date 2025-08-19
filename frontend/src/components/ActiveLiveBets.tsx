'use client';

import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/api';
import { useAuth } from './Auth';
import { useNotifications } from './NotificationProvider';
import { formatGameStatus } from '@/lib/formatting';
import { 
  DollarSign, TrendingUp, TrendingDown, AlertCircle, 
  Clock, CheckCircle, XCircle, RefreshCw, Share2
} from 'lucide-react';
import BetShareModal from './BetShareModal';

interface LiveBet {
  id: string;
  game_id: string;
  bet_type: string;
  selection: string;
  original_odds: number;
  current_odds: number | null;
  amount: number;
  potential_win: number;
  current_potential_win: number | null;
  status: string;
  placed_at: string;
  game_status_at_placement: string;
  current_game_status: string | null;
  home_score_at_placement: number;
  away_score_at_placement: number;
  current_home_score: number | null;
  current_away_score: number | null;
  cash_out_available: boolean;
  cash_out_value: number | null;
  cashed_out_at: string | null;
  cashed_out_amount: number | null;
  home_team?: string;
  away_team?: string;
  sport?: string;
}

interface CashOutOffer {
  bet_id: string;
  original_amount: number;
  original_potential_win: number;
  current_cash_out_value: number;
  profit_loss: number;
  offer_expires_at: string;
  is_available: boolean;
  reason: string | null;
}

interface ActiveLiveBetsProps {
  onUpdate?: () => void;
}

export default function ActiveLiveBets({ onUpdate }: ActiveLiveBetsProps) {
  const { token } = useAuth();
  const { addNotification } = useNotifications();
  const [bets, setBets] = useState<LiveBet[]>([]);
  const [pendingBets, setPendingBets] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [cashingOut, setCashingOut] = useState<string | null>(null);
  const [cashOutOffers, setCashOutOffers] = useState<{[key: string]: CashOutOffer}>({});
  const [showCashOutModal, setShowCashOutModal] = useState(false);
  const [selectedBet, setSelectedBet] = useState<LiveBet | null>(null);
  const [refreshInterval, setRefreshInterval] = useState<NodeJS.Timeout | null>(null);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [selectedBetForShare, setSelectedBetForShare] = useState<any>(null);

  useEffect(() => {
    loadBets();
    loadPendingBets();
    
    // Set up auto-refresh every 10 seconds for active bets
    const interval = setInterval(() => {
      loadBets();
      loadPendingBets();
      refreshCashOutOffers();
    }, 10000);
    setRefreshInterval(interval);
    
    return () => {
      if (interval) clearInterval(interval);
    };
  }, []);

  const loadBets = async () => {
    try {
      const response = await apiClient.get('/api/live-bets/active', token);
      
      if (response.status === 'success') {
        const activeBets = response.bets || [];
        setBets(activeBets);
        
        // Load cash out offers for active bets
        activeBets.forEach((bet: LiveBet) => {
          if (bet.status === 'active' && bet.cash_out_available) {
            loadCashOutOffer(bet.id);
          }
        });
      }
    } catch (error) {
      console.error('Failed to load active bets:', error);
    }
  };

  const loadPendingBets = async () => {
    try {
      const response = await apiClient.post('/api/bets/history', {
        status: 'pending',
        limit: 50
      }, token);
      
      if (response.status === 'success') {
        setPendingBets(response.bets || []);
      }
    } catch (error) {
      console.error('Failed to load pending bets:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadCashOutOffer = async (betId: string) => {
    try {
      const response = await apiClient.get(`/api/live-bets/cash-out/${betId}`, token);
      
      if (response.status === 'success' && response.offer) {
        setCashOutOffers(prev => ({
          ...prev,
          [betId]: response.offer
        }));
      }
    } catch (error) {
      console.error(`Failed to load cash out offer for bet ${betId}:`, error);
    }
  };

  const refreshCashOutOffers = async () => {
    const activeBets = bets.filter(bet => bet.status === 'active' && bet.cash_out_available);
    for (const bet of activeBets) {
      await loadCashOutOffer(bet.id);
    }
  };

  const executeCashOut = async (betId: string, acceptAmount: number) => {
    setCashingOut(betId);
    
    try {
      const response = await apiClient.post('/api/live-bets/cash-out', {
        bet_id: betId,
        accept_amount: acceptAmount
      }, token);
      
      if (response.status === 'success') {
        addNotification({
          type: 'success',
          title: 'Cash Out Successful!',
          message: `You cashed out for $${response.cash_out_amount.toFixed(2)}`,
          priority: 'high'
        });
        
        setShowCashOutModal(false);
        setSelectedBet(null);
        
        // Reload bets
        await loadBets();
        await loadPendingBets();
        if (onUpdate) onUpdate();
      }
    } catch (error: any) {
      addNotification({
        type: 'error',
        title: 'Cash Out Failed',
        message: error.detail || 'Failed to cash out bet',
        priority: 'high'
      });
    } finally {
      setCashingOut(null);
    }
  };

  const openCashOutModal = (bet: LiveBet) => {
    setSelectedBet(bet);
    setShowCashOutModal(true);
    // Refresh offer before showing modal
    loadCashOutOffer(bet.id);
  };

  const formatOdds = (odds: number | null) => {
    if (!odds) return '--';
    return odds > 0 ? `+${odds}` : odds.toString();
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'active':
        return <Clock className="w-5 h-5 text-green-500" />;
      case 'cashed_out':
        return <DollarSign className="w-5 h-5 text-blue-500" />;
      case 'won':
        return <CheckCircle className="w-5 h-5 text-green-600" />;
      case 'lost':
        return <XCircle className="w-5 h-5 text-red-600" />;
      default:
        return <AlertCircle className="w-5 h-5 text-gray-500" />;
    }
  };

  const getProfitLossColor = (amount: number) => {
    if (amount > 0) return 'text-green-600';
    if (amount < 0) return 'text-red-600';
    return 'text-gray-600';
  };

  const formatPendingBetTitle = (bet: any) => {
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
    return `${(bet.bet_type || '').toUpperCase()} - ${(bet.selection || '').toUpperCase()}`;
  };

  const formatLiveBetTitle = (bet: LiveBet) => {
    if (bet.home_team && bet.away_team) {
      const gameInfo = `${bet.away_team} @ ${bet.home_team}`;
      if (bet.bet_type.toLowerCase() === 'moneyline') {
        const team = bet.selection === 'home' ? bet.home_team : bet.away_team;
        return `${team} to Win (${gameInfo})`;
      } else if (bet.bet_type.toLowerCase() === 'spread') {
        const team = bet.selection === 'home' ? bet.home_team : bet.away_team;
        return `${team} Spread (${gameInfo})`;
      } else if (bet.bet_type.toLowerCase() === 'total') {
        return `${bet.selection.toUpperCase()} Total (${gameInfo})`;
      }
    }
    return `${bet.bet_type.toUpperCase()} - ${bet.selection.toUpperCase()}`;
  };

  const openShareModal = (bet: any) => {
    setSelectedBetForShare(bet);
    setShareModalOpen(true);
  };

  const closeShareModal = () => {
    setSelectedBetForShare(null);
    setShareModalOpen(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-red-600"></div>
      </div>
    );
  }

  if (bets.length === 0 && pendingBets.length === 0) {
    return (
      <div className="text-center py-12">
        <DollarSign className="w-16 h-16 text-gray-400 mx-auto mb-4" />
        <h3 className="text-lg font-semibold text-gray-900 mb-2">No Active Bets</h3>
        <p className="text-gray-600">Place a bet to see it here</p>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-4">
        {/* Pending Regular Bets */}
        {pendingBets.map(bet => (
          <div
            key={bet.id}
            className="bg-white rounded-lg border border-gray-200 overflow-hidden"
          >
            <div className="p-6">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center space-x-3">
                  <Clock className="w-5 h-5 text-yellow-500" />
                  <div>
                    <div className="flex items-center space-x-2">
                      <span className="font-semibold text-gray-900">
                        {formatPendingBetTitle(bet)}
                      </span>
                      <span className="text-sm text-gray-600">
                        @ {formatOdds(bet.odds)}
                      </span>
                    </div>
                    <div className="text-sm text-gray-600 mt-1">
                      Placed: {new Date(bet.placed_at).toLocaleString()}
                    </div>
                    {bet.sport && (
                      <div className="text-xs text-gray-500 mt-1">
                        {bet.sport} • Upcoming Game
                      </div>
                    )}
                  </div>
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
                  <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded-full text-xs font-medium">
                    Pending
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div>
                  <div className="text-sm text-gray-600">Bet Amount</div>
                  <div className="font-semibold">${bet.amount.toFixed(2)}</div>
                </div>
                
                <div>
                  <div className="text-sm text-gray-600">Potential Win</div>
                  <div className="font-semibold text-green-600">
                    ${bet.potential_win.toFixed(2)}
                  </div>
                </div>
                
                {bet.commence_time && (
                  <div>
                    <div className="text-sm text-gray-600">Game Time</div>
                    <div className="font-semibold text-sm">
                      {new Date(bet.commence_time).toLocaleDateString('en-US', {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                      })}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}

        {/* Live Bets */}
        {bets.map(bet => {
          const offer = cashOutOffers[bet.id];
          const isActive = bet.status === 'active';
          
          return (
            <div
              key={bet.id}
              className="bg-white rounded-lg border border-gray-200 overflow-hidden"
            >
              <div className="p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center space-x-3">
                    {getStatusIcon(bet.status)}
                    <div>
                      <div className="flex items-center space-x-2">
                        <span className="font-semibold text-gray-900">
                          {formatLiveBetTitle(bet)}
                        </span>
                        <span className="text-sm text-gray-600">
                          @ {formatOdds(bet.original_odds)}
                        </span>
                      </div>
                      <div className="text-sm text-gray-600 mt-1">
                        Placed: {new Date(bet.placed_at).toLocaleString()}
                      </div>
                    </div>
                  </div>
                  
                  <div className="flex items-start space-x-2">
                    <button
                      onClick={() => openShareModal(bet)}
                      className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                      title="Share this bet"
                    >
                      <Share2 className="w-4 h-4" />
                    </button>
                    
                    {isActive && bet.cash_out_available && offer && (
                      <button
                        onClick={() => openCashOutModal(bet)}
                        disabled={cashingOut === bet.id}
                        className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-700 hover:to-blue-800 transition-all disabled:opacity-50 flex items-center space-x-2"
                      >
                        <DollarSign className="w-4 h-4" />
                        <span>Cash Out ${offer.current_cash_out_value.toFixed(2)}</span>
                      </button>
                    )}
                  </div>
                  
                  {bet.status === 'cashed_out' && bet.cashed_out_amount && (
                    <div className="text-right">
                      <div className="text-sm text-gray-600">Cashed Out</div>
                      <div className="font-semibold text-green-600">
                        ${bet.cashed_out_amount.toFixed(2)}
                      </div>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div>
                    <div className="text-sm text-gray-600">Bet Amount</div>
                    <div className="font-semibold">${bet.amount.toFixed(2)}</div>
                  </div>
                  
                  <div>
                    <div className="text-sm text-gray-600">Potential Win</div>
                    <div className="font-semibold">
                      ${(bet.current_potential_win || bet.potential_win).toFixed(2)}
                    </div>
                  </div>
                  
                  <div>
                    <div className="text-sm text-gray-600">Game Status</div>
                    <div className="font-semibold">
                      {formatGameStatus(bet.current_game_status || bet.game_status_at_placement)}
                    </div>
                  </div>
                  
                  <div>
                    <div className="text-sm text-gray-600">Score</div>
                    <div className="font-semibold">
                      {bet.current_home_score ?? bet.home_score_at_placement} - {' '}
                      {bet.current_away_score ?? bet.away_score_at_placement}
                    </div>
                  </div>
                </div>

                {isActive && offer && (
                  <div className="mt-4 pt-4 border-t border-gray-200">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2">
                        {offer.profit_loss >= 0 ? (
                          <TrendingUp className="w-5 h-5 text-green-500" />
                        ) : (
                          <TrendingDown className="w-5 h-5 text-red-500" />
                        )}
                        <span className={`font-medium ${getProfitLossColor(offer.profit_loss)}`}>
                          {offer.profit_loss >= 0 ? '+' : ''}${offer.profit_loss.toFixed(2)} P/L
                        </span>
                      </div>
                      
                      <div className="text-sm text-gray-600">
                        Cash out value updates every 10s
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Cash Out Modal */}
      {showCashOutModal && selectedBet && cashOutOffers[selectedBet.id] && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-md w-full p-6">
            <h2 className="text-xl font-bold text-gray-900 mb-4">Confirm Cash Out</h2>
            
            <div className="space-y-4">
              <div className="bg-gray-50 rounded-lg p-4">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm text-gray-600">Original Bet</span>
                  <span className="font-semibold">${selectedBet.amount.toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm text-gray-600">Potential Win</span>
                  <span className="font-semibold">${selectedBet.potential_win.toFixed(2)}</span>
                </div>
                <div className="border-t border-gray-200 pt-2 mt-2">
                  <div className="flex justify-between items-center">
                    <span className="text-sm font-medium text-gray-900">Cash Out Value</span>
                    <span className="text-lg font-bold text-green-600">
                      ${cashOutOffers[selectedBet.id].current_cash_out_value.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex justify-between items-center mt-1">
                    <span className="text-sm text-gray-600">Profit/Loss</span>
                    <span className={`font-medium ${
                      getProfitLossColor(cashOutOffers[selectedBet.id].profit_loss)
                    }`}>
                      {cashOutOffers[selectedBet.id].profit_loss >= 0 ? '+' : ''}
                      ${cashOutOffers[selectedBet.id].profit_loss.toFixed(2)}
                    </span>
                  </div>
                </div>
              </div>

              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                <div className="flex items-start">
                  <AlertCircle className="w-5 h-5 text-yellow-600 mr-2 flex-shrink-0 mt-0.5" />
                  <div className="text-sm text-yellow-800">
                    <p className="font-medium mb-1">Are you sure?</p>
                    <p>Once you cash out, this action cannot be undone. The bet will be settled at the cash out value regardless of the final outcome.</p>
                  </div>
                </div>
              </div>

              <div className="flex space-x-3">
                <button
                  onClick={() => executeCashOut(
                    selectedBet.id, 
                    cashOutOffers[selectedBet.id].current_cash_out_value
                  )}
                  disabled={cashingOut === selectedBet.id}
                  className="flex-1 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50 flex items-center justify-center space-x-2"
                >
                  {cashingOut === selectedBet.id ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Processing...</span>
                    </>
                  ) : (
                    <>
                      <CheckCircle className="w-4 h-4" />
                      <span>Confirm Cash Out</span>
                    </>
                  )}
                </button>
                <button
                  onClick={() => {
                    setShowCashOutModal(false);
                    setSelectedBet(null);
                  }}
                  disabled={cashingOut === selectedBet.id}
                  className="flex-1 px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
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
    </>
  );
}