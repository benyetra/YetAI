'use client';

import React, { useState, useEffect } from 'react';
import {
  X,
  DollarSign,
  TrendingUp,
  Brain,
  AlertCircle,
  Trophy,
  Zap,
  Calculator,
  ChevronDown,
  Info,
  Lock,
  CheckCircle,
  XCircle,
  ExternalLink
} from 'lucide-react';
import { useAuth } from './Auth';
import { apiClient, sportsAPI } from '@/lib/api';

// Types
interface Game {
  id: string;
  sport: string;
  sport_key?: string;  // Added for sportsbook linking
  home_team: string;
  away_team: string;
  commence_time: string;
  home_odds: number;
  away_odds: number;
  spread: number;
  home_spread?: number;
  away_spread?: number;
  total: number;
}

interface BetSlip {
  game: Game;
  betType: 'moneyline' | 'spread' | 'total';
  selection: string;
  odds: number;
  amount: number;
  potentialWin: number;
}

interface AIRecommendation {
  confidence: number;
  suggestedBet: string;
  reasoning: string;
  riskLevel: 'low' | 'medium' | 'high';
  suggestedAmount?: number;
}

// Modal Component
export default function BetModal({
  isOpen,
  onClose,
  game,
  initialBetType = 'moneyline'
}: {
  isOpen: boolean;
  onClose: () => void;
  game: Game | null;
  initialBetType?: 'moneyline' | 'spread' | 'total';
}) {
  const { user, token } = useAuth();
  const [betType, setBetType] = useState<'moneyline' | 'spread' | 'total'>(initialBetType);
  const [selection, setSelection] = useState<string>('');
  const [amount, setAmount] = useState<string>('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [betPlaced, setBetPlaced] = useState(false);
  const [error, setError] = useState<string>('');
  const [aiRecommendation, setAiRecommendation] = useState<AIRecommendation | null>(null);
  const [showAiInsights, setShowAiInsights] = useState(true);
  const [loadingFanDuel, setLoadingFanDuel] = useState(false);

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

  // Get odds based on selection
  const getOdds = (): number => {
    if (!game || !selection) return 0;
    
    if (betType === 'moneyline') {
      return selection === game.home_team ? game.home_odds : game.away_odds;
    } else if (betType === 'spread') {
      // Simplified spread odds (usually -110)
      return -110;
    } else if (betType === 'total') {
      // Simplified total odds (usually -110)
      return -110;
    }
    return 0;
  };

  const potentialWin = amount ? calculatePotentialWin(parseFloat(amount), getOdds()) : 0;
  const totalReturn = amount ? parseFloat(amount) + potentialWin : 0;

  // Reset state when modal opens/closes
  useEffect(() => {
    if (isOpen && game) {
      setSelection('');
      setAmount('');
      setError('');
      setBetPlaced(false);
      setShowConfirmation(false);
      
      // Generate AI recommendation
      generateAIRecommendation();
    }
  }, [isOpen, game]);

  // AI recommendation disabled to avoid showing fake recommendations
  const generateAIRecommendation = () => {
    if (!game) return;
    
    // Don't generate fake AI recommendations
    setAiRecommendation(null);
  };

  const handleAmountChange = (value: string) => {
    // Only allow numbers and decimal point
    if (value === '' || /^\d*\.?\d*$/.test(value)) {
      setAmount(value);
      setError('');
    }
  };

  const validateBet = (): boolean => {
    if (!selection) {
      setError('Please select a team or option');
      return false;
    }
    if (!amount || parseFloat(amount) <= 0) {
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

  const handlePlaceBet = async () => {
    if (!validateBet() || !game) return;
    
    setShowConfirmation(true);
  };

  const confirmBet = async () => {
    if (!game || !user) return;
    
    setIsProcessing(true);
    setError('');
    
    try {
      const betData = {
        game_id: game.id,
        bet_type: betType,
        selection: selection,
        odds: getOdds(),
        amount: parseFloat(amount),
        home_team: game.home_team,
        away_team: game.away_team,
        sport: game.sport,
        commence_time: game.commence_time
      };
      
      console.log('Placing bet:', betData);
      
      // Make actual API call
      const response = await apiClient.post('/api/bets/place', betData, token);
      
      if (response.status === 'success') {
        setBetPlaced(true);
        setShowConfirmation(false);
        
        // Close modal after showing success message
        setTimeout(() => {
          onClose();
        }, 2000);
      } else {
        setError(response.detail || 'Failed to place bet');
        setShowConfirmation(false);
      }
      
    } catch (error: any) {
      console.error('Bet placement error:', error);
      setError(error.message || 'Failed to place bet. Please try again.');
      setShowConfirmation(false);
    } finally {
      setIsProcessing(false);
    }
  };

  const handlePlaceOnFanDuel = async () => {
    if (!game || !selection) return;

    try {
      setLoadingFanDuel(true);

      // Map bet type to API format
      const betTypeMap = {
        'moneyline': 'h2h',
        'spread': 'spreads',
        'total': 'totals'
      };

      // Generate sport_key from sport if not available
      const sportKey = game.sport_key || `${game.sport.toLowerCase()}_${game.sport.toLowerCase()}`;

      const response = await sportsAPI.getSportsbookLink({
        sportsbook: 'fanduel',
        sport_key: sportKey,
        home_team: game.home_team,
        away_team: game.away_team,
        bet_type: betTypeMap[betType],
        bet_selection: selection
      });

      if (response.status === 'success' && response.link) {
        // Open FanDuel in new tab
        window.open(response.link, '_blank');
      } else {
        console.error('Failed to generate FanDuel link:', response);
        setError('Could not generate FanDuel link. Please try again.');
      }
    } catch (error) {
      console.error('Error opening FanDuel:', error);
      setError('Failed to open FanDuel. Please try again.');
    } finally {
      setLoadingFanDuel(false);
    }
  };

  if (!isOpen || !game) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-gray-200 p-6 flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">Place Your Bet</h2>
            <p className="text-sm text-gray-500 mt-1">
              {game.away_team} @ {game.home_team}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>

        {/* Success Message */}
        {betPlaced && (
          <div className="p-6 bg-green-50 border-b border-green-200">
            <div className="flex items-center space-x-3">
              <CheckCircle className="w-6 h-6 text-green-600" />
              <div>
                <p className="font-medium text-green-900">Bet Placed Successfully!</p>
                <p className="text-sm text-green-700">
                  Your bet of ${amount} has been confirmed.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* AI Insights - Premium Feature */}
        {user?.subscription_tier !== 'free' && aiRecommendation && showAiInsights && !showConfirmation && (
          <div className="p-6 bg-gradient-to-r from-purple-50 to-blue-50 border-b border-purple-100">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center space-x-2">
                <Brain className="w-5 h-5 text-purple-600" />
                <h3 className="font-bold text-gray-900">AI Insights</h3>
                <span className={`text-xs px-2 py-1 rounded font-medium ${
                  aiRecommendation.riskLevel === 'low' ? 'bg-green-100 text-green-700' :
                  aiRecommendation.riskLevel === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                  'bg-red-100 text-red-700'
                }`}>
                  {aiRecommendation.riskLevel.toUpperCase()} RISK
                </span>
              </div>
              <button
                onClick={() => setShowAiInsights(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Recommended Bet:</span>
                <span className="font-medium text-gray-900">{aiRecommendation.suggestedBet}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Confidence:</span>
                <span className="font-bold text-purple-600">
                  {Math.round(aiRecommendation.confidence * 100)}%
                </span>
              </div>
              <p className="text-sm text-gray-600 mt-2">{aiRecommendation.reasoning}</p>
              {aiRecommendation.suggestedAmount && (
                <button
                  onClick={() => {
                    setAmount(aiRecommendation.suggestedAmount!.toString());
                    setSelection(aiRecommendation.suggestedBet);
                  }}
                  className="mt-3 text-sm text-purple-600 hover:text-purple-700 font-medium"
                >
                  Apply AI Suggestion →
                </button>
              )}
            </div>
          </div>
        )}

        {/* Bet Type Selector */}
        <div className="p-6 border-b border-gray-200">
          <label className="block text-sm font-medium text-gray-700 mb-3">Bet Type</label>
          <div className="grid grid-cols-3 gap-3">
            <button
              onClick={() => setBetType('moneyline')}
              className={`p-3 rounded-lg border-2 transition-all ${
                betType === 'moneyline'
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <p className="font-medium">Moneyline</p>
              <p className="text-xs mt-1 opacity-75">Pick the winner</p>
            </button>
            <button
              onClick={() => setBetType('spread')}
              className={`p-3 rounded-lg border-2 transition-all ${
                betType === 'spread'
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <p className="font-medium">Spread</p>
              <p className="text-xs mt-1 opacity-75">
                {(() => {
                  const homeSpreadValue = game.home_spread ?? game.spread;
                  return `${homeSpreadValue > 0 ? '+' : ''}${homeSpreadValue}`;
                })()}
              </p>
            </button>
            <button
              onClick={() => setBetType('total')}
              className={`p-3 rounded-lg border-2 transition-all ${
                betType === 'total'
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <p className="font-medium">Total</p>
              <p className="text-xs mt-1 opacity-75">O/U {game.total}</p>
            </button>
          </div>
        </div>

        {/* Selection */}
        <div className="p-6 border-b border-gray-200">
          <label className="block text-sm font-medium text-gray-700 mb-3">Your Selection</label>
          
          {betType === 'moneyline' && (
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setSelection(game.away_team)}
                className={`p-4 rounded-lg border-2 transition-all ${
                  selection === game.away_team
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <p className="font-medium text-gray-900">{game.away_team}</p>
                <p className="text-lg font-bold text-blue-600 mt-1">
                  {game.away_odds > 0 ? '+' : ''}{game.away_odds}
                </p>
              </button>
              <button
                onClick={() => setSelection(game.home_team)}
                className={`p-4 rounded-lg border-2 transition-all ${
                  selection === game.home_team
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <p className="font-medium text-gray-900">{game.home_team}</p>
                <p className="text-lg font-bold text-blue-600 mt-1">
                  {game.home_odds > 0 ? '+' : ''}{game.home_odds}
                </p>
              </button>
            </div>
          )}
          
          {betType === 'spread' && (
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => {
                  const awaySpreadValue = game.away_spread ?? -game.spread;
                  setSelection(`${game.away_team} ${awaySpreadValue > 0 ? '+' : ''}${awaySpreadValue}`);
                }}
                className={`p-4 rounded-lg border-2 transition-all ${
                  selection.includes(game.away_team)
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <p className="font-medium text-gray-900">{game.away_team}</p>
                <p className="text-lg font-bold text-blue-600 mt-1">
                  {(() => {
                    const awaySpreadValue = game.away_spread ?? -game.spread;
                    return `${awaySpreadValue > 0 ? '+' : ''}${awaySpreadValue} (-110)`;
                  })()}
                </p>
              </button>
              <button
                onClick={() => {
                  const homeSpreadValue = game.home_spread ?? game.spread;
                  setSelection(`${game.home_team} ${homeSpreadValue > 0 ? '+' : ''}${homeSpreadValue}`);
                }}
                className={`p-4 rounded-lg border-2 transition-all ${
                  selection.includes(game.home_team)
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <p className="font-medium text-gray-900">{game.home_team}</p>
                <p className="text-lg font-bold text-blue-600 mt-1">
                  {(() => {
                    const homeSpreadValue = game.home_spread ?? game.spread;
                    return `${homeSpreadValue > 0 ? '+' : ''}${homeSpreadValue} (-110)`;
                  })()}
                </p>
              </button>
            </div>
          )}
          
          {betType === 'total' && (
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setSelection(`Over ${game.total}`)}
                className={`p-4 rounded-lg border-2 transition-all ${
                  selection.includes('Over')
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <p className="font-medium text-gray-900">Over</p>
                <p className="text-lg font-bold text-blue-600 mt-1">
                  {game.total} (-110)
                </p>
              </button>
              <button
                onClick={() => setSelection(`Under ${game.total}`)}
                className={`p-4 rounded-lg border-2 transition-all ${
                  selection.includes('Under')
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <p className="font-medium text-gray-900">Under</p>
                <p className="text-lg font-bold text-blue-600 mt-1">
                  {game.total} (-110)
                </p>
              </button>
            </div>
          )}
        </div>

        {/* Bet Amount */}
        <div className="p-6 border-b border-gray-200">
          <label className="block text-sm font-medium text-gray-700 mb-3">Bet Amount</label>
          
          {/* Quick amounts */}
          <div className="flex space-x-2 mb-4">
            {quickAmounts.map((quickAmount) => (
              <button
                key={quickAmount}
                onClick={() => setAmount(quickAmount.toString())}
                className={`px-4 py-2 rounded-lg border transition-all ${
                  amount === quickAmount.toString()
                    ? 'border-blue-500 bg-blue-50 text-blue-700'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                ${quickAmount}
              </button>
            ))}
          </div>
          
          {/* Custom amount input */}
          <div className="relative">
            <DollarSign className="w-5 h-5 text-gray-400 absolute left-3 top-1/2 transform -translate-y-1/2" />
            <input
              type="text"
              value={amount}
              onChange={(e) => handleAmountChange(e.target.value)}
              placeholder="Enter amount"
              className="w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-lg"
            />
          </div>
          
          {/* Potential winnings */}
          {amount && parseFloat(amount) > 0 && (
            <div className="mt-4 p-4 bg-gray-50 rounded-lg">
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Bet Amount:</span>
                  <span className="font-medium">${parseFloat(amount).toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Potential Win:</span>
                  <span className="font-medium text-green-600">
                    +${potentialWin.toFixed(2)}
                  </span>
                </div>
                <div className="pt-2 border-t border-gray-200 flex justify-between">
                  <span className="font-medium text-gray-900">Total Return:</span>
                  <span className="font-bold text-lg text-gray-900">
                    ${totalReturn.toFixed(2)}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Error Message */}
        {error && (
          <div className="px-6 py-3 bg-red-50 border-b border-red-200">
            <div className="flex items-center space-x-2">
              <AlertCircle className="w-5 h-5 text-red-600" />
              <p className="text-sm text-red-800">{error}</p>
            </div>
          </div>
        )}

        {/* Confirmation Dialog */}
        {showConfirmation && (
          <div className="p-6 bg-yellow-50 border-b border-yellow-200">
            <h3 className="font-bold text-gray-900 mb-3 flex items-center">
              <AlertCircle className="w-5 h-5 text-yellow-600 mr-2" />
              Confirm Your Bet
            </h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Selection:</span>
                <span className="font-medium">{selection}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Odds:</span>
                <span className="font-medium">{getOdds()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Amount:</span>
                <span className="font-medium">${parseFloat(amount).toFixed(2)}</span>
              </div>
              <div className="flex justify-between pt-2 border-t border-yellow-200">
                <span className="font-medium">Potential Return:</span>
                <span className="font-bold text-green-600">${totalReturn.toFixed(2)}</span>
              </div>
            </div>
            <div className="flex space-x-3 mt-4">
              <button
                onClick={confirmBet}
                disabled={isProcessing}
                className="flex-1 bg-green-600 text-white py-3 rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors"
              >
                {isProcessing ? 'Processing...' : 'Confirm Bet'}
              </button>
              <button
                onClick={() => setShowConfirmation(false)}
                disabled={isProcessing}
                className="flex-1 bg-gray-200 text-gray-700 py-3 rounded-lg hover:bg-gray-300 disabled:opacity-50 font-medium transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Action Buttons */}
        {!showConfirmation && !betPlaced && (
          <div className="p-6 bg-gray-50 space-y-3">
            {/* YetAI Internal Bet */}
            <button
              onClick={handlePlaceBet}
              disabled={!selection || !amount || parseFloat(amount) <= 0}
              className="w-full bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors"
            >
              Place Bet on YetAI
            </button>

            {/* Divider */}
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-gray-300"></div>
              </div>
              <div className="relative flex justify-center text-sm">
                <span className="px-2 bg-gray-50 text-gray-500">or</span>
              </div>
            </div>

            {/* FanDuel External Bet */}
            <button
              onClick={handlePlaceOnFanDuel}
              disabled={!selection || loadingFanDuel}
              className="w-full bg-green-600 text-white py-3 rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors flex items-center justify-center space-x-2"
            >
              {loadingFanDuel ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  <span>Opening FanDuel...</span>
                </>
              ) : (
                <>
                  <span>Place Bet on FanDuel</span>
                  <ExternalLink className="w-4 h-4" />
                </>
              )}
            </button>

            {/* Responsible Gambling Notice */}
            <p className="text-xs text-gray-500 text-center mt-4">
              Please bet responsibly. If you need help, call 1-800-GAMBLER.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}