'use client';

import React, { useState, useEffect } from 'react';
import { Layers, Clock, CheckCircle, XCircle, DollarSign, Calendar, Share2 } from 'lucide-react';
import BetShareModal from './BetShareModal';

interface ParlayLeg {
  id: string;
  game_id: string;
  bet_type: string;
  selection: string;
  odds: number;
  status: string;
}

interface Parlay {
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

interface ParlayListProps {
  refreshTrigger?: number;
}

export default function ParlayList({ refreshTrigger = 0 }: ParlayListProps) {
  const [parlays, setParlays] = useState<Parlay[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');
  const [filter, setFilter] = useState<string>('all');
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [selectedParlayForShare, setSelectedParlayForShare] = useState<any>(null);

  const fetchParlays = async () => {
    try {
      setLoading(true);
      const token = localStorage.getItem('auth_token');
      
      const response = await fetch('http://localhost:8000/api/bets/parlays', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      const result = await response.json();

      if (result.status === 'success') {
        setParlays(result.parlays || []);
      } else {
        setError('Failed to fetch parlays');
      }
    } catch (error) {
      setError('Failed to fetch parlays');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchParlays();
  }, [refreshTrigger]);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'won':
        return <CheckCircle className="w-5 h-5 text-green-500" />;
      case 'lost':
        return <XCircle className="w-5 h-5 text-red-500" />;
      case 'pending':
        return <Clock className="w-5 h-5 text-yellow-500" />;
      default:
        return <Clock className="w-5 h-5 text-gray-500" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'won':
        return 'text-green-600 bg-green-50';
      case 'lost':
        return 'text-red-600 bg-red-50';
      case 'pending':
        return 'text-yellow-600 bg-yellow-50';
      default:
        return 'text-gray-600 bg-gray-50';
    }
  };

  const formatOdds = (odds: number) => {
    return odds > 0 ? `+${odds}` : `${odds}`;
  };

  const openShareModal = (parlay: Parlay) => {
    // Convert parlay to bet format for sharing
    const betForShare = {
      id: parlay.id,
      bet_type: 'parlay',
      selection: `Parlay (${parlay.leg_count} legs)`,
      odds: parlay.total_odds,
      amount: parlay.amount,
      potential_win: parlay.potential_win,
      status: parlay.status,
      placed_at: parlay.placed_at,
      result_amount: parlay.result_amount,
      legs: parlay.legs
    };
    setSelectedParlayForShare(betForShare);
    setShareModalOpen(true);
  };

  const closeShareModal = () => {
    setSelectedParlayForShare(null);
    setShareModalOpen(false);
  };

  const filteredParlays = parlays.filter(parlay => {
    if (filter === 'all') return true;
    return parlay.status === filter;
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-12 text-red-600">
        <XCircle className="w-12 h-12 mx-auto mb-4" />
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Filter Tabs */}
      <div className="flex space-x-1 bg-gray-100 p-1 rounded-lg">
        {[
          { key: 'all', label: 'All Parlays' },
          { key: 'pending', label: 'Active' },
          { key: 'won', label: 'Won' },
          { key: 'lost', label: 'Lost' }
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setFilter(tab.key)}
            className={`flex-1 px-4 py-2 text-sm font-medium rounded-md transition-colors ${
              filter === tab.key
                ? 'bg-white text-blue-600 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {filteredParlays.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <Layers className="w-12 h-12 mx-auto mb-4 text-gray-300" />
          <p>No parlays found</p>
          <p className="text-sm">
            {filter === 'all' 
              ? 'Create your first parlay to get started'
              : `No ${filter} parlays`
            }
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredParlays.map((parlay) => (
            <div key={parlay.id} className="bg-white border border-gray-200 rounded-lg p-6">
              {/* Parlay Header */}
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center space-x-3">
                  <div className="flex items-center space-x-2">
                    {getStatusIcon(parlay.status)}
                    <span className={`px-2 py-1 text-xs font-medium rounded-full ${getStatusColor(parlay.status)}`}>
                      {parlay.status.charAt(0).toUpperCase() + parlay.status.slice(1)}
                    </span>
                  </div>
                  <span className="text-sm text-gray-500">
                    {parlay.leg_count} Leg Parlay
                  </span>
                </div>
                <div className="flex items-center space-x-3">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      openShareModal(parlay);
                    }}
                    className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                    title="Share this parlay"
                  >
                    <Share2 className="w-4 h-4" />
                  </button>
                  <div className="text-right">
                    <div className="text-sm text-gray-500">
                      <Calendar className="w-4 h-4 inline mr-1" />
                      {new Date(parlay.placed_at).toLocaleDateString()}
                    </div>
                  </div>
                </div>
              </div>

              {/* Legs */}
              <div className="space-y-2 mb-4">
                {parlay.legs.map((leg, index) => (
                  <div key={leg.id || index} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                    <div className="flex-1">
                      <div className="flex items-center space-x-2">
                        <span className="text-sm font-medium">{leg.selection}</span>
                        <span className={`px-1.5 py-0.5 text-xs rounded ${getStatusColor(leg.status)}`}>
                          {leg.status}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 capitalize">{leg.bet_type}</p>
                    </div>
                    <div className="text-right">
                      <span className="text-sm font-mono">{formatOdds(leg.odds)}</span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Parlay Summary */}
              <div className="border-t pt-4">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Bet Amount</p>
                    <p className="text-sm font-semibold">${parlay.amount.toFixed(2)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Parlay Odds</p>
                    <p className="text-sm font-mono">{formatOdds(parlay.total_odds)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Potential Win</p>
                    <p className="text-sm font-semibold text-green-600">
                      ${parlay.potential_win.toFixed(2)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 mb-1">
                      {parlay.status === 'won' ? 'Won' : parlay.status === 'lost' ? 'Lost' : 'Potential Payout'}
                    </p>
                    <p className={`text-sm font-semibold ${
                      parlay.status === 'won' ? 'text-green-600' : 
                      parlay.status === 'lost' ? 'text-red-600' : 
                      'text-blue-600'
                    }`}>
                      ${(
                        parlay.status === 'won' ? (parlay.result_amount || parlay.potential_win) :
                        parlay.status === 'lost' ? 0 :
                        parlay.potential_win + parlay.amount
                      ).toFixed(2)}
                    </p>
                  </div>
                </div>

                {parlay.settled_at && (
                  <div className="mt-3 pt-3 border-t border-gray-100">
                    <p className="text-xs text-gray-500">
                      Settled on {new Date(parlay.settled_at).toLocaleDateString()} at {new Date(parlay.settled_at).toLocaleTimeString()}
                    </p>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Bet Share Modal */}
      {selectedParlayForShare && (
        <BetShareModal
          bet={selectedParlayForShare}
          isOpen={shareModalOpen}
          onClose={closeShareModal}
        />
      )}
    </div>
  );
}