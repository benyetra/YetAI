'use client';

import React, { useState } from 'react';
import { X, DollarSign, TrendingUp, TrendingDown, User, CheckCircle, Loader } from 'lucide-react';
import { useAuth } from './Auth';
import { apiClient } from '@/lib/api';

interface PropBet {
  player_name: string;
  market_key: string;
  market_display: string;
  line: number;
  selection: 'over' | 'under';
  odds: number;
  game_id: string;
  sport: string;
  home_team: string;
  away_team: string;
  commence_time: string;
}

interface PlayerPropBetModalProps {
  isOpen: boolean;
  onClose: () => void;
  propBet: PropBet | null;
}

export default function PlayerPropBetModal({
  isOpen,
  onClose,
  propBet
}: PlayerPropBetModalProps) {
  const { user, token } = useAuth();
  const [amount, setAmount] = useState<string>('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [betPlaced, setBetPlaced] = useState(false);
  const [error, setError] = useState<string>('');
  const [showConfirmation, setShowConfirmation] = useState(false);

  // Quick bet amounts
  const quickAmounts = [10, 25, 50, 100, 250];

  // Calculate potential winnings
  const calculatePotentialWin = (betAmount: number, odds: number): number => {
    if (odds > 0) {
      return betAmount * (odds / 100);
    } else {
      return betAmount * (100 / Math.abs(odds));
    }
  };

  const potentialWin = amount ? calculatePotentialWin(parseFloat(amount), propBet?.odds || 0) : 0;
  const totalPayout = amount ? parseFloat(amount) + potentialWin : 0;

  const formatOdds = (odds: number): string => {
    return odds > 0 ? `+${odds}` : `${odds}`;
  };

  const validateBet = (): boolean => {
    setError('');

    if (!amount || isNaN(parseFloat(amount))) {
      setError('Please enter a valid bet amount');
      return false;
    }
    if (parseFloat(amount) < 1) {
      setError('Minimum bet amount is $1');
      return false;
    }
    if (parseFloat(amount) > 10000) {
      setError('Maximum bet amount is $10,000');
      return false;
    }
    return true;
  };

  const handlePlaceBet = () => {
    if (!validateBet() || !propBet) return;
    setShowConfirmation(true);
  };

  const confirmBet = async () => {
    if (!propBet || !user) return;

    setIsProcessing(true);
    setError('');

    try {
      const betData = {
        game_id: propBet.game_id,
        bet_type: 'prop',
        selection: `${propBet.player_name} ${propBet.selection} ${propBet.line} ${propBet.market_display}`,
        odds: propBet.odds,
        amount: parseFloat(amount),
        home_team: propBet.home_team,
        away_team: propBet.away_team,
        sport: propBet.sport,
        commence_time: propBet.commence_time,
        // Player prop specific fields
        player_name: propBet.player_name,
        prop_market: propBet.market_key,
        prop_line: propBet.line,
        prop_selection: propBet.selection
      };

      console.log('Placing player prop bet:', betData);

      const response = await apiClient.post('/api/bets/place', betData, token);

      if (response.status === 'success') {
        setBetPlaced(true);
        setShowConfirmation(false);

        // Close modal after showing success message
        setTimeout(() => {
          onClose();
          // Reset state
          setAmount('');
          setBetPlaced(false);
          setError('');
        }, 2500);
      } else {
        setError(response.detail || 'Failed to place bet');
        setShowConfirmation(false);
      }
    } catch (error: any) {
      console.error('Player prop bet placement error:', error);
      setError(error.message || 'Failed to place bet. Please try again.');
      setShowConfirmation(false);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleClose = () => {
    if (!isProcessing) {
      setAmount('');
      setError('');
      setShowConfirmation(false);
      setBetPlaced(false);
      onClose();
    }
  };

  if (!isOpen || !propBet) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center p-4 z-50">
      <div className="bg-gradient-to-b from-gray-800 to-gray-900 rounded-2xl max-w-md w-full shadow-2xl border border-gray-700">
        {/* Header */}
        <div className="p-6 border-b border-gray-700 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-white flex items-center space-x-2">
              <User className="w-5 h-5 text-purple-400" />
              <span>Place Player Prop Bet</span>
            </h2>
            <p className="text-sm text-gray-400 mt-1">
              {propBet.away_team} @ {propBet.home_team}
            </p>
          </div>
          <button
            onClick={handleClose}
            disabled={isProcessing}
            className="p-2 hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-50"
          >
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        {/* Success Message */}
        {betPlaced && (
          <div className="p-6 bg-green-900/30 border-b border-green-700/50">
            <div className="flex items-center space-x-3">
              <CheckCircle className="w-6 h-6 text-green-400" />
              <div>
                <p className="font-medium text-green-300">Bet Placed Successfully!</p>
                <p className="text-sm text-green-400/80">
                  Your ${amount} bet has been confirmed.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Bet Details */}
        {!betPlaced && !showConfirmation && (
          <div className="p-6 space-y-6">
            {/* Player & Prop */}
            <div className="bg-gray-700/30 rounded-lg p-4 border border-gray-600">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <p className="text-lg font-bold text-white">{propBet.player_name}</p>
                  <p className="text-sm text-gray-400">{propBet.market_display}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm text-gray-400">Line</p>
                  <p className="text-lg font-bold text-white">{propBet.line}</p>
                </div>
              </div>

              <div className="flex items-center justify-between pt-3 border-t border-gray-600">
                <div className="flex items-center space-x-2">
                  {propBet.selection === 'over' ? (
                    <TrendingUp className="w-4 h-4 text-green-400" />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-red-400" />
                  )}
                  <span className="text-white font-medium capitalize">{propBet.selection}</span>
                </div>
                <span className={`text-lg font-bold ${propBet.odds > 0 ? 'text-green-400' : 'text-white'}`}>
                  {formatOdds(propBet.odds)}
                </span>
              </div>
            </div>

            {/* Bet Amount */}
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Bet Amount
              </label>
              <div className="relative">
                <DollarSign className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type="number"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder="0.00"
                  className="w-full pl-10 pr-4 py-3 bg-gray-700/50 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  min="1"
                  max="10000"
                  step="0.01"
                />
              </div>

              {/* Quick Amounts */}
              <div className="flex gap-2 mt-3">
                {quickAmounts.map((quickAmount) => (
                  <button
                    key={quickAmount}
                    onClick={() => setAmount(quickAmount.toString())}
                    className="flex-1 px-3 py-2 bg-gray-700/50 hover:bg-gray-600 border border-gray-600 rounded-lg text-sm text-white transition-colors"
                  >
                    ${quickAmount}
                  </button>
                ))}
              </div>
            </div>

            {/* Potential Win */}
            {amount && parseFloat(amount) > 0 && (
              <div className="bg-gradient-to-r from-purple-900/30 to-blue-900/30 rounded-lg p-4 border border-purple-700/50">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-gray-400">Potential Win:</span>
                  <span className="text-xl font-bold text-green-400">
                    ${potentialWin.toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-400">Total Payout:</span>
                  <span className="text-white font-semibold">
                    ${totalPayout.toFixed(2)}
                  </span>
                </div>
              </div>
            )}

            {/* Error Message */}
            {error && (
              <div className="bg-red-900/30 border border-red-700 rounded-lg p-3">
                <p className="text-sm text-red-300">{error}</p>
              </div>
            )}

            {/* Place Bet Button */}
            <button
              onClick={handlePlaceBet}
              disabled={!amount || parseFloat(amount) <= 0 || isProcessing}
              className="w-full py-4 bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 disabled:from-gray-600 disabled:to-gray-700 disabled:cursor-not-allowed text-white font-bold rounded-lg transition-all shadow-lg disabled:shadow-none"
            >
              Place Bet
            </button>
          </div>
        )}

        {/* Confirmation */}
        {showConfirmation && !betPlaced && (
          <div className="p-6 space-y-6">
            <div className="text-center">
              <p className="text-lg font-semibold text-white mb-4">
                Confirm Your Bet
              </p>
              <div className="bg-gray-700/30 rounded-lg p-4 border border-gray-600 space-y-3 text-left">
                <div className="flex justify-between">
                  <span className="text-gray-400">Player:</span>
                  <span className="text-white font-medium">{propBet.player_name}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Prop:</span>
                  <span className="text-white font-medium">{propBet.market_display}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Selection:</span>
                  <span className="text-white font-medium capitalize">
                    {propBet.selection} {propBet.line}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Odds:</span>
                  <span className="text-white font-bold">{formatOdds(propBet.odds)}</span>
                </div>
                <div className="flex justify-between border-t border-gray-600 pt-3">
                  <span className="text-gray-400">Bet Amount:</span>
                  <span className="text-white font-bold">${amount}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Potential Win:</span>
                  <span className="text-green-400 font-bold">${potentialWin.toFixed(2)}</span>
                </div>
              </div>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setShowConfirmation(false)}
                disabled={isProcessing}
                className="flex-1 py-3 bg-gray-700 hover:bg-gray-600 text-white font-semibold rounded-lg transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmBet}
                disabled={isProcessing}
                className="flex-1 py-3 bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white font-bold rounded-lg transition-all shadow-lg disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
              >
                {isProcessing ? (
                  <>
                    <Loader className="w-5 h-5 animate-spin" />
                    <span>Processing...</span>
                  </>
                ) : (
                  <span>Confirm Bet</span>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
