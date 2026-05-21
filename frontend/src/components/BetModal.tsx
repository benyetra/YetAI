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
import { formatOdds, calculatePotentialWin } from '@/lib/formatting';

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

  const sectionLabel = 'type-label block mb-2';
  const optionBase =
    'rounded-lg border p-3 text-left transition-colors border-[var(--border)] hover:border-[var(--border-strong)]';
  const optionSelected =
    'border-[var(--accent)] bg-[var(--accent-soft)] ring-1 ring-[var(--accent)]';

  if (!isOpen || !game) return null;

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
      <div
        className="rounded-xl max-w-lg w-full max-h-[90vh] overflow-y-auto shadow-2xl border border-[var(--border-strong)]"
        style={{ background: 'var(--surface)' }}
      >
        {/* Header */}
        <div
          className="sticky top-0 z-10 flex items-center justify-between p-5 border-b border-[var(--border)]"
          style={{ background: 'var(--surface)' }}
        >
          <div>
            <h2 className="text-xl font-semibold tracking-tight" style={{ color: 'var(--text)' }}>
              Place Your Bet
            </h2>
            <p className="text-sm mt-0.5" style={{ color: 'var(--text-2)' }}>
              {game.away_team} @ {game.home_team}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg transition-colors hover:bg-[var(--surface-2)]"
            aria-label="Close"
          >
            <X className="w-5 h-5" style={{ color: 'var(--text-3)' }} />
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
        <div className="px-5 py-4 border-b border-[var(--border)]">
          <span className={sectionLabel}>Bet Type</span>
          <div className="grid grid-cols-3 gap-2">
            <button
              onClick={() => setBetType('moneyline')}
              className={`${optionBase} ${betType === 'moneyline' ? optionSelected : ''}`}
            >
              <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Moneyline</p>
              <p className="text-xs mt-0.5" style={{ color: 'var(--text-3)' }}>Pick the winner</p>
            </button>
            <button
              onClick={() => setBetType('spread')}
              className={`${optionBase} ${betType === 'spread' ? optionSelected : ''}`}
            >
              <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Spread</p>
              <p className="text-xs mt-0.5 mono" style={{ color: 'var(--text-2)' }}>
                {(() => {
                  const homeSpreadValue = game.home_spread ?? game.spread;
                  return `${homeSpreadValue > 0 ? '+' : ''}${homeSpreadValue}`;
                })()}
              </p>
            </button>
            <button
              onClick={() => setBetType('total')}
              className={`${optionBase} ${betType === 'total' ? optionSelected : ''}`}
            >
              <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Total</p>
              <p className="text-xs mt-0.5 mono" style={{ color: 'var(--text-2)' }}>O/U {game.total}</p>
            </button>
          </div>
        </div>

        {/* Selection */}
        <div className="px-5 py-4 border-b border-[var(--border)]">
          <span className={sectionLabel}>Your Selection</span>

          {betType === 'moneyline' && (
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setSelection(game.away_team)}
                className={`${optionBase} ${selection === game.away_team ? optionSelected : ''}`}
              >
                <p className="text-sm font-semibold leading-snug" style={{ color: 'var(--text)' }}>
                  {game.away_team}
                </p>
                <p className="type-numeric text-base mt-1" style={{ color: 'var(--accent)' }}>
                  {formatOdds(game.away_odds)}
                </p>
              </button>
              <button
                onClick={() => setSelection(game.home_team)}
                className={`${optionBase} ${selection === game.home_team ? optionSelected : ''}`}
              >
                <p className="text-sm font-semibold leading-snug" style={{ color: 'var(--text)' }}>
                  {game.home_team}
                </p>
                <p className="type-numeric text-base mt-1" style={{ color: 'var(--accent)' }}>
                  {formatOdds(game.home_odds)}
                </p>
              </button>
            </div>
          )}

          {betType === 'spread' && (
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => {
                  const awaySpreadValue = game.away_spread ?? -game.spread;
                  setSelection(`${game.away_team} ${awaySpreadValue > 0 ? '+' : ''}${awaySpreadValue}`);
                }}
                className={`${optionBase} ${selection.includes(game.away_team) ? optionSelected : ''}`}
              >
                <p className="text-sm font-semibold leading-snug" style={{ color: 'var(--text)' }}>
                  {game.away_team}
                </p>
                <p className="type-numeric text-base mt-1" style={{ color: 'var(--accent)' }}>
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
                className={`${optionBase} ${selection.includes(game.home_team) ? optionSelected : ''}`}
              >
                <p className="text-sm font-semibold leading-snug" style={{ color: 'var(--text)' }}>
                  {game.home_team}
                </p>
                <p className="type-numeric text-base mt-1" style={{ color: 'var(--accent)' }}>
                  {(() => {
                    const homeSpreadValue = game.home_spread ?? game.spread;
                    return `${homeSpreadValue > 0 ? '+' : ''}${homeSpreadValue} (-110)`;
                  })()}
                </p>
              </button>
            </div>
          )}

          {betType === 'total' && (
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setSelection(`Over ${game.total}`)}
                className={`${optionBase} ${selection.includes('Over') ? optionSelected : ''}`}
              >
                <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Over</p>
                <p className="type-numeric text-base mt-1" style={{ color: 'var(--accent)' }}>
                  {game.total} (-110)
                </p>
              </button>
              <button
                onClick={() => setSelection(`Under ${game.total}`)}
                className={`${optionBase} ${selection.includes('Under') ? optionSelected : ''}`}
              >
                <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Under</p>
                <p className="type-numeric text-base mt-1" style={{ color: 'var(--accent)' }}>
                  {game.total} (-110)
                </p>
              </button>
            </div>
          )}
        </div>

        {/* Bet Amount */}
        <div className="px-5 py-4 border-b border-[var(--border)]">
          <span className={sectionLabel}>Bet Amount</span>

          <div className="flex flex-wrap gap-2 mb-3">
            {quickAmounts.map((quickAmount) => (
              <button
                key={quickAmount}
                onClick={() => setAmount(quickAmount.toString())}
                className={`mono px-3 py-2 rounded-lg border text-sm transition-all ${
                  amount === quickAmount.toString()
                    ? optionSelected
                    : 'border-[var(--border)] hover:border-[var(--border-strong)]'
                }`}
                style={{ color: 'var(--text)' }}
              >
                ${quickAmount}
              </button>
            ))}
          </div>

          <div className="relative">
            <DollarSign
              className="w-5 h-5 absolute left-3 top-1/2 -translate-y-1/2"
              style={{ color: 'var(--text-3)' }}
            />
            <input
              type="text"
              inputMode="decimal"
              value={amount}
              onChange={(e) => handleAmountChange(e.target.value)}
              placeholder="Enter amount"
              className="w-full pl-10 pr-4 py-3 rounded-lg text-lg mono"
            />
          </div>

          {amount && parseFloat(amount) > 0 && (
            <div
              className="mt-3 p-3 rounded-lg border space-y-2"
              style={{ background: 'var(--surface-2)', borderColor: 'var(--border)' }}
            >
              <div className="flex justify-between text-sm">
                <span style={{ color: 'var(--text-2)' }}>Bet Amount</span>
                <span className="mono font-medium" style={{ color: 'var(--text)' }}>
                  ${parseFloat(amount).toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span style={{ color: 'var(--text-2)' }}>Potential Win</span>
                <span className="mono font-medium" style={{ color: 'var(--win)' }}>
                  +${potentialWin.toFixed(2)}
                </span>
              </div>
              <div
                className="pt-2 flex justify-between items-baseline border-t"
                style={{ borderColor: 'var(--border)' }}
              >
                <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                  Total Return
                </span>
                <span className="type-numeric-lg" style={{ color: 'var(--text)' }}>
                  ${totalReturn.toFixed(2)}
                </span>
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
          <div
            className="px-5 py-4 border-b"
            style={{
              background: 'var(--surface-2)',
              borderColor: 'var(--border)',
              borderLeft: '3px solid var(--gold)',
            }}
          >
            <h3 className="text-base font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--text)' }}>
              <AlertCircle className="w-5 h-5 shrink-0" style={{ color: 'var(--gold)' }} />
              Confirm Your Bet
            </h3>
            <div
              className="rounded-lg border p-3 space-y-2.5 text-sm"
              style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
            >
              <div className="flex justify-between gap-4">
                <span style={{ color: 'var(--text-3)' }}>Selection</span>
                <span className="font-medium text-right" style={{ color: 'var(--text)' }}>
                  {selection}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span style={{ color: 'var(--text-3)' }}>Odds</span>
                <span className="mono font-medium" style={{ color: 'var(--text)' }}>
                  {formatOdds(getOdds())}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span style={{ color: 'var(--text-3)' }}>Amount</span>
                <span className="mono font-medium" style={{ color: 'var(--text)' }}>
                  ${parseFloat(amount).toFixed(2)}
                </span>
              </div>
              <div
                className="flex justify-between gap-4 pt-2 border-t"
                style={{ borderColor: 'var(--border)' }}
              >
                <span className="font-semibold" style={{ color: 'var(--text)' }}>
                  Potential Return
                </span>
                <span className="mono font-bold text-base" style={{ color: 'var(--win)' }}>
                  ${totalReturn.toFixed(2)}
                </span>
              </div>
            </div>
            <div className="flex gap-2 mt-4">
              <button
                onClick={confirmBet}
                disabled={isProcessing}
                className="flex-1 py-3 rounded-lg font-semibold text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                style={{ background: 'var(--win)' }}
              >
                {isProcessing ? 'Processing...' : 'Confirm Bet'}
              </button>
              <button
                onClick={() => setShowConfirmation(false)}
                disabled={isProcessing}
                className="btn-secondary flex-1 py-3 rounded-lg font-medium disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Action Buttons */}
        {!showConfirmation && !betPlaced && (
          <div className="px-5 py-4 space-y-3" style={{ background: 'var(--bg-elev)' }}>
            <button
              onClick={handlePlaceBet}
              disabled={!selection || !amount || parseFloat(amount) <= 0}
              className="btn-primary w-full justify-center py-3 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Review &amp; Place Bet
            </button>

            <div className="relative py-1">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t" style={{ borderColor: 'var(--border)' }} />
              </div>
              <div className="relative flex justify-center text-xs">
                <span className="px-2" style={{ background: 'var(--bg-elev)', color: 'var(--text-3)' }}>
                  or
                </span>
              </div>
            </div>

            <button
              onClick={handlePlaceOnFanDuel}
              disabled={!selection || loadingFanDuel}
              className="w-full py-3 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed text-white"
              style={{ background: 'var(--win)' }}
            >
              {loadingFanDuel ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>Opening FanDuel...</span>
                </>
              ) : (
                <>
                  <span>Place Bet on FanDuel</span>
                  <ExternalLink className="w-4 h-4" />
                </>
              )}
            </button>

            <p className="text-xs text-center pt-1" style={{ color: 'var(--text-4)' }}>
              Please bet responsibly. If you need help, call 1-800-GAMBLER.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}