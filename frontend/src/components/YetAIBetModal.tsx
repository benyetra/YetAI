'use client';

import React, { useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import {
  X,
  DollarSign,
  TrendingUp,
  Brain,
  AlertCircle,
  Trophy,
  Calculator,
  CheckCircle,
  XCircle
} from 'lucide-react';
import { useAuth } from './Auth';

// Types
interface YetAIBet {
  id: string;
  sport: string;
  game: string;
  bet_type: string;
  pick: string;
  odds: string;
  confidence: number;
  reasoning: string;
  status: 'pending' | 'won' | 'lost' | 'pushed';
  is_premium: boolean;
  game_time: string;
}

interface YetAIBetModalProps {
  isOpen: boolean;
  onClose: () => void;
  bet: YetAIBet | null;
  onBetPlaced?: () => void;
}

export default function YetAIBetModal({
  isOpen,
  onClose,
  bet,
  onBetPlaced
}: YetAIBetModalProps) {
  const { user, token } = useAuth();
  const [amount, setAmount] = useState<string>('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [betPlaced, setBetPlaced] = useState(false);
  const [error, setError] = useState<string>('');

  // Quick bet amounts
  const quickAmounts = [10, 25, 50, 100, 250];

  // Parse odds from string to number
  const parseOdds = (oddsStr: string): number => {
    const cleanOdds = oddsStr.replace(/[+\-]/g, '');
    const numOdds = parseFloat(cleanOdds);
    return oddsStr.startsWith('-') ? -numOdds : numOdds;
  };

  // Calculate potential winnings
  const calculatePotentialWin = (betAmount: number, oddsStr: string): number => {
    const odds = parseOdds(oddsStr);
    if (odds > 0) {
      return betAmount * (odds / 100);
    } else {
      return betAmount * (100 / Math.abs(odds));
    }
  };

  const handleAmountChange = (value: string) => {
    // Only allow numbers and decimal point
    if (value === '' || /^\d*\.?\d*$/.test(value)) {
      setAmount(value);
      setError('');
    }
  };

  const handleQuickAmount = (quickAmount: number) => {
    setAmount(quickAmount.toString());
    setError('');
  };

  const validateBet = (): boolean => {
    const betAmount = parseFloat(amount);
    
    if (!betAmount || betAmount <= 0) {
      setError('Please enter a valid bet amount');
      return false;
    }
    
    if (betAmount > 10000) {
      setError('Maximum bet amount is $10,000');
      return false;
    }
    
    if (user?.subscription_tier === 'free' && betAmount > 100) {
      setError('Free users have a $100 maximum bet limit');
      return false;
    }
    
    return true;
  };

  const handlePlaceBet = async () => {
    console.log('🎯 Place bet clicked!', { bet, amount, user, token: !!token });

    if (!validateBet() || !bet) {
      console.log('❌ Validation failed or no bet', { validateResult: validateBet(), bet });
      return;
    }

    setIsProcessing(true);
    setError('');

    try {
      // Map bet type to enum format
      const betTypeMapping: { [key: string]: string } = {
        'total (over/under)': 'total',
        'total': 'total',
        'over/under': 'total',
        'spread': 'spread',
        'point spread': 'spread',
        'moneyline': 'moneyline',
        'money line': 'moneyline',
        'parlay': 'parlay',
        'prop': 'prop'
      };

      const normalizedBetType = betTypeMapping[bet.bet_type.toLowerCase()] || 'total';

      const requestPayload = {
        game_id: bet.id, // Using bet ID as game ID for YetAI bets
        bet_type: normalizedBetType,
        selection: bet.pick,
        odds: parseOdds(bet.odds),
        amount: parseFloat(amount),
        home_team: bet.game.split(' @ ')[1] || bet.game.split(' vs ')[1] || 'Home',
        away_team: bet.game.split(' @ ')[0] || bet.game.split(' vs ')[0] || 'Away',
        sport: bet.sport,
        commence_time: new Date(bet.game_time).toISOString()
      };

      console.log('🚀 Making API call:', {
        url: getApiUrl('/api/bets/place'),
        payload: requestPayload,
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const response = await fetch(getApiUrl('/api/bets/place'), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(requestPayload)
      });

      console.log('📡 API Response:', {
        status: response.status,
        statusText: response.statusText,
        ok: response.ok
      });

      if (response.ok) {
        setBetPlaced(true);
        setShowConfirmation(true);
        if (onBetPlaced) {
          onBetPlaced();
        }
      } else {
        const errorData = await response.json();
        console.log('❌ API Error:', errorData);
        setError(errorData.detail || 'Failed to place bet');
      }
    } catch (err) {
      console.log('💥 Exception caught:', err);
      setError('Failed to place bet. Please try again.');
    } finally {
      setIsProcessing(false);
    }
  };

  const resetModal = () => {
    setAmount('');
    setError('');
    setShowConfirmation(false);
    setBetPlaced(false);
    setIsProcessing(false);
  };

  const handleClose = () => {
    resetModal();
    onClose();
  };

  if (!isOpen || !bet) return null;

  const betAmount = parseFloat(amount) || 0;
  const potentialWin = betAmount > 0 ? calculatePotentialWin(betAmount, bet.odds) : 0;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg max-w-lg w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-200">
          <div className="flex items-center space-x-2">
            <Brain className="w-6 h-6 text-blue-600" />
            <h2 className="text-xl font-semibold text-gray-900">Place YetAI Bet</h2>
          </div>
          <button
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        <div className="p-6">
          {betPlaced && showConfirmation ? (
            // Success State
            <div className="text-center py-8">
              <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-900 mb-2">Bet Placed Successfully!</h3>
              <p className="text-gray-600 mb-6">
                Your ${amount} bet on {bet.pick} has been placed.
              </p>
              <button
                onClick={handleClose}
                className="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 transition-colors"
              >
                Close
              </button>
            </div>
          ) : (
            <>
              {/* Bet Details */}
              <div className="bg-blue-50 rounded-lg p-4 mb-6">
                <div className="flex items-center justify-between mb-2">
                  <span className="bg-blue-100 text-blue-800 text-xs font-medium px-2 py-1 rounded">
                    {bet.sport}
                  </span>
                  <span className="text-sm font-medium text-blue-600">
                    {bet.confidence}% Confidence
                  </span>
                </div>
                <h3 className="font-bold text-lg text-gray-900 mb-1">{bet.game}</h3>
                <div className="flex items-center space-x-4">
                  <span className="text-gray-600">{bet.bet_type}:</span>
                  <span className="font-semibold text-blue-600">{bet.pick}</span>
                  <span className="text-gray-500">({bet.odds})</span>
                </div>
                <div className="mt-3 bg-white rounded p-3">
                  <p className="text-sm text-gray-700">{bet.reasoning}</p>
                </div>
              </div>

              {/* Bet Amount */}
              <div className="mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Bet Amount
                </label>
                <div className="relative">
                  <DollarSign className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type="text"
                    value={amount}
                    onChange={(e) => handleAmountChange(e.target.value)}
                    placeholder="0.00"
                    className="w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </div>
                
                {/* Quick Amount Buttons */}
                <div className="flex space-x-2 mt-3">
                  {quickAmounts.map((quickAmount) => (
                    <button
                      key={quickAmount}
                      onClick={() => handleQuickAmount(quickAmount)}
                      className="flex-1 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
                    >
                      ${quickAmount}
                    </button>
                  ))}
                </div>
              </div>

              {/* Bet Summary */}
              {betAmount > 0 && (
                <div className="bg-gray-50 rounded-lg p-4 mb-6">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm text-gray-600">Bet Amount:</span>
                    <span className="font-medium">${betAmount.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm text-gray-600">Potential Win:</span>
                    <span className="font-medium text-green-600">${potentialWin.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between items-center border-t border-gray-200 pt-2">
                    <span className="text-sm font-medium text-gray-900">Total Payout:</span>
                    <span className="font-bold text-lg">${(betAmount + potentialWin).toFixed(2)}</span>
                  </div>
                </div>
              )}

              {/* Error Message */}
              {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center space-x-2">
                  <AlertCircle className="w-5 h-5 text-red-500" />
                  <span className="text-red-700 text-sm">{error}</span>
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex space-x-3">
                <button
                  onClick={handleClose}
                  className="flex-1 py-3 px-4 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handlePlaceBet}
                  disabled={!betAmount || isProcessing}
                  className="flex-1 py-3 px-4 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center justify-center space-x-2"
                >
                  {isProcessing ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                      <span>Placing Bet...</span>
                    </>
                  ) : (
                    <>
                      <Trophy className="w-4 h-4" />
                      <span>Place Bet</span>
                    </>
                  )}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}