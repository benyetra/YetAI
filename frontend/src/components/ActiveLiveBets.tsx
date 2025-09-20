'use client';

import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/api';
import { useAuth } from './Auth';
import {
  DollarSign, Clock, Share2
} from 'lucide-react';
import BetShareModal from './BetShareModal';


interface ActiveLiveBetsProps {
  onUpdate?: () => void;
}

export default function ActiveLiveBets({ onUpdate }: ActiveLiveBetsProps) {
  const { token } = useAuth();
  const [pendingBets, setPendingBets] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshInterval, setRefreshInterval] = useState<NodeJS.Timeout | null>(null);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [selectedBetForShare, setSelectedBetForShare] = useState<any>(null);

  useEffect(() => {
    loadPendingBets(); // Only load pending bets, not duplicating data

    // Set up auto-refresh every 15 seconds for pending bets only
    const interval = setInterval(() => {
      loadPendingBets();
    }, 15000);
    setRefreshInterval(interval);

    return () => {
      if (interval) clearInterval(interval);
    };
  }, []);


  const loadPendingBets = async () => {
    try {
      const response = await apiClient.post('/api/bets/history', {
        status: 'pending',
        limit: 50
      }, token);
      
      if (response.status === 'success') {
        setPendingBets(response.history || []);
      }
    } catch (error) {
      console.error('Failed to load pending bets:', error);
    } finally {
      setLoading(false);
    }
  };


  const formatOdds = (odds: number | null) => {
    if (!odds) return '--';
    return odds > 0 ? `+${odds}` : odds.toString();
  };


  const formatPendingBetTitle = (bet: any) => {
    // Handle parlays differently
    if (bet.bet_type === 'parlay') {
      return `${bet.leg_count}-Leg Parlay`;
    }

    if (bet?.home_team && bet?.away_team) {
      const gameInfo = `${bet.away_team} @ ${bet.home_team}`;
      if (bet.bet_type === 'moneyline') {
        return `${bet.selection} to Win (${gameInfo})`;
      } else if (bet.bet_type === 'spread') {
        return `${bet.selection} (${gameInfo})`;
      } else if (bet.bet_type === 'total') {
        return `${(bet.selection || '').toUpperCase()} (${gameInfo})`;
      }
    }
    return `${(bet?.bet_type || '').toUpperCase()} - ${(bet?.selection || '').toUpperCase()}`;
  };

  const renderParlayLegs = (bet: any) => {
    if (!bet.legs || bet.legs.length === 0) return null;

    return (
      <div className="mt-4 p-4 bg-gray-50 rounded-lg">
        <div className="text-sm font-medium text-gray-700 mb-3">Legs:</div>
        <div className="space-y-2">
          {bet.legs.map((leg: any, index: number) => (
            <div key={leg.id} className="flex items-center justify-between text-sm">
              <div className="flex items-center space-x-2">
                <span className="text-gray-500">{index + 1}.</span>
                <span className="font-medium">{leg.selection}</span>
                <span className="text-blue-600">
                  {leg.odds > 0 ? `+${leg.odds}` : leg.odds}
                </span>
              </div>
              {leg.home_team && leg.away_team && (
                <div className="text-xs text-gray-500">
                  {leg.away_team} @ {leg.home_team}
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="mt-3 pt-3 border-t border-gray-200 flex justify-between text-sm">
          <span className="font-medium">Combined Odds:</span>
          <span className="font-bold text-green-600">
            {bet.total_odds && bet.total_odds !== 'NaN' ? `+${bet.total_odds}` : 'N/A'}
          </span>
        </div>
      </div>
    );
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

  if (pendingBets.length === 0) {
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
                      {bet.bet_type !== 'parlay' && (
                        <span className="text-sm text-gray-600">
                          @ {formatOdds(bet.odds)}
                        </span>
                      )}
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

              {/* Render parlay legs if this is a parlay */}
              {bet.bet_type === 'parlay' && renderParlayLegs(bet)}
            </div>
          </div>
        ))}

      </div>


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