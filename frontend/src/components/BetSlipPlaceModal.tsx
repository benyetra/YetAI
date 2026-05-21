'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle, Layers, X } from 'lucide-react';
import { useAuth } from './Auth';
import { apiClient } from '@/lib/api';
import { formatOdds, calculatePotentialWin } from '@/lib/formatting';
import { fmtMoney, fmtOdds } from '@/lib/yetai-format';
import {
  parlayAmericanOdds,
  slipItemsToLegs,
  type SlipBetLeg,
} from '@/lib/slip-to-bet';
import type { BetSlipPlaceContext } from '@/components/yetai/types';

export type { BetSlipPlaceContext };

interface BetSlipPlaceModalProps {
  isOpen: boolean;
  onClose: () => void;
  context: BetSlipPlaceContext | null;
  onPlaced?: () => void;
}

export default function BetSlipPlaceModal({
  isOpen,
  onClose,
  context,
  onPlaced,
}: BetSlipPlaceModalProps) {
  const { token } = useAuth();
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [betPlaced, setBetPlaced] = useState(false);
  const [error, setError] = useState('');

  const slip = context?.slip ?? [];
  const mode = context?.mode ?? 'single';
  const stake = context?.stake ?? 0;

  const { legs, missing } = useMemo(() => slipItemsToLegs(slip), [slip]);

  const parlayOdds = useMemo(
    () => (mode === 'parlay' && slip.length >= 2 ? parlayAmericanOdds(slip) : 0),
    [mode, slip]
  );

  const totalStake = mode === 'single' ? stake * slip.length : stake;

  const potentialWin = useMemo(() => {
    if (stake <= 0 || slip.length === 0) return 0;
    if (mode === 'parlay' && slip.length >= 2) {
      return calculatePotentialWin(stake, parlayOdds);
    }
    return slip.reduce((sum, b) => sum + calculatePotentialWin(stake, b.odds), 0);
  }, [mode, stake, slip, parlayOdds]);

  const totalReturn = totalStake + potentialWin;

  useEffect(() => {
    if (isOpen) {
      setShowConfirmation(false);
      setBetPlaced(false);
      setError('');
      setIsProcessing(false);
    }
  }, [isOpen, context]);

  const validationError = useMemo(() => {
    if (slip.length === 0) return 'Your bet slip is empty.';
    if (missing.length > 0) return 'Some selections are missing game data. Remove and re-add them from the odds board.';
    if (stake <= 0) return 'Enter a stake greater than $0.';
    if (mode === 'parlay' && slip.length < 2) return 'Parlays need at least two legs.';
    return '';
  }, [slip.length, missing.length, stake, mode]);

  const placeSingles = async (betLegs: SlipBetLeg[]) => {
    for (const leg of betLegs) {
      const response = await apiClient.post(
        '/api/bets/place',
        {
          game_id: leg.game_id,
          bet_type: leg.bet_type,
          selection: leg.selection,
          odds: leg.odds,
          amount: stake,
          home_team: leg.home_team,
          away_team: leg.away_team,
          sport: leg.sport,
          commence_time: leg.commence_time,
        },
        token
      );
      if (response.status !== 'success') {
        throw new Error(response.detail || 'Failed to place bet');
      }
    }
  };

  const placeParlay = async (betLegs: SlipBetLeg[]) => {
    const response = await apiClient.post(
      '/api/bets/parlay',
      { legs: betLegs, amount: stake },
      token
    );
    if (response.status !== 'success') {
      throw new Error(response.detail || 'Failed to place parlay');
    }
  };

  const handleConfirm = async () => {
    if (validationError || legs.length === 0) {
      setError(validationError || 'Unable to place bet.');
      return;
    }

    setIsProcessing(true);
    setError('');

    try {
      if (mode === 'parlay') {
        await placeParlay(legs);
      } else {
        await placeSingles(legs);
      }
      setBetPlaced(true);
      setShowConfirmation(false);
      onPlaced?.();
      setTimeout(() => onClose(), 1800);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to place bet. Please try again.';
      setError(message);
      setShowConfirmation(false);
    } finally {
      setIsProcessing(false);
    }
  };

  if (!isOpen || !context) return null;

  const title =
    mode === 'parlay'
      ? `Place ${slip.length}-Leg Parlay`
      : slip.length === 1
        ? 'Place Your Bet'
        : `Place ${slip.length} Bets`;

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
      <div
        className="rounded-xl max-w-lg w-full max-h-[90vh] overflow-y-auto shadow-2xl border border-[var(--border-strong)]"
        style={{ background: 'var(--surface)' }}
      >
        <div
          className="sticky top-0 z-10 flex items-center justify-between p-5 border-b border-[var(--border)]"
          style={{ background: 'var(--surface)' }}
        >
          <div>
            <h2 className="text-xl font-semibold tracking-tight flex items-center gap-2" style={{ color: 'var(--text)' }}>
              <Layers className="w-5 h-5" style={{ color: 'var(--accent)' }} />
              {title}
            </h2>
            <p className="text-sm mt-0.5" style={{ color: 'var(--text-2)' }}>
              {mode === 'parlay' ? 'Combined parlay from your slip' : 'Review selections before submitting'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-lg transition-colors hover:bg-[var(--surface-2)]"
            aria-label="Close"
          >
            <X className="w-5 h-5" style={{ color: 'var(--text-3)' }} />
          </button>
        </div>

        {betPlaced ? (
          <div className="p-6">
            <div className="flex items-center gap-3">
              <CheckCircle className="w-8 h-8 shrink-0" style={{ color: 'var(--win)' }} />
              <div>
                <p className="font-semibold" style={{ color: 'var(--text)' }}>
                  {mode === 'parlay' ? 'Parlay placed!' : 'Bet placed!'}
                </p>
                <p className="text-sm mt-0.5" style={{ color: 'var(--text-2)' }}>
                  {fmtMoney(totalStake)} staked · potential return {fmtMoney(totalReturn)}
                </p>
              </div>
            </div>
          </div>
        ) : (
          <>
            <div className="px-5 py-4 border-b border-[var(--border)]">
              <span className="type-label block mb-2">Your selections</span>
              <div className="space-y-2">
                {slip.map((item) => (
                  <div
                    key={item.id}
                    className="rounded-lg border p-3"
                    style={{ background: 'var(--surface-2)', borderColor: 'var(--border)' }}
                  >
                    <div className="flex justify-between gap-3 items-start">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                          {item.label}
                        </p>
                        <p className="text-xs mt-0.5 truncate" style={{ color: 'var(--text-3)' }}>
                          {item.matchup}
                        </p>
                      </div>
                      <span className="mono text-sm shrink-0" style={{ color: 'var(--accent)' }}>
                        {fmtOdds(item.odds)}
                      </span>
                    </div>
                    {mode === 'single' && stake > 0 && (
                      <p className="text-xs mt-2 mono" style={{ color: 'var(--text-3)' }}>
                        Stake {fmtMoney(stake)} · win {fmtMoney(calculatePotentialWin(stake, item.odds), { signed: true })}
                      </p>
                    )}
                  </div>
                ))}
              </div>
              {mode === 'parlay' && slip.length >= 2 && (
                <p className="text-xs mt-3 mono" style={{ color: 'var(--text-2)' }}>
                  Combined odds: {formatOdds(parlayOdds)}
                </p>
              )}
            </div>

            <div className="px-5 py-4 border-b border-[var(--border)]">
              <span className="type-label block mb-2">Wager summary</span>
              <div
                className="rounded-lg border p-3 space-y-2"
                style={{ background: 'var(--surface-2)', borderColor: 'var(--border)' }}
              >
                <div className="flex justify-between text-sm">
                  <span style={{ color: 'var(--text-2)' }}>Bet type</span>
                  <span className="font-medium capitalize" style={{ color: 'var(--text)' }}>
                    {mode === 'parlay' ? `Parlay (${slip.length} legs)` : slip.length === 1 ? 'Single' : `${slip.length} singles`}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span style={{ color: 'var(--text-2)' }}>
                    {mode === 'single' && slip.length > 1 ? 'Stake per bet' : 'Stake'}
                  </span>
                  <span className="mono font-medium" style={{ color: 'var(--text)' }}>
                    {fmtMoney(stake)}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span style={{ color: 'var(--text-2)' }}>Total stake</span>
                  <span className="mono font-medium" style={{ color: 'var(--text)' }}>
                    {fmtMoney(totalStake)}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span style={{ color: 'var(--text-2)' }}>Potential win</span>
                  <span className="mono font-medium" style={{ color: 'var(--win)' }}>
                    {fmtMoney(potentialWin, { signed: true })}
                  </span>
                </div>
                <div
                  className="flex justify-between items-baseline pt-2 border-t"
                  style={{ borderColor: 'var(--border)' }}
                >
                  <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                    Total return
                  </span>
                  <span className="type-numeric-lg" style={{ color: 'var(--text)' }}>
                    {fmtMoney(totalReturn)}
                  </span>
                </div>
              </div>
            </div>

            {(error || validationError) && !showConfirmation && (
              <div className="px-5 py-3 flex items-start gap-2" style={{ background: 'var(--loss-soft)' }}>
                <AlertCircle className="w-5 h-5 shrink-0" style={{ color: 'var(--loss)' }} />
                <p className="text-sm" style={{ color: 'var(--loss)' }}>
                  {error || validationError}
                </p>
              </div>
            )}

            {showConfirmation ? (
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
                  Confirm {mode === 'parlay' ? 'parlay' : 'bet'}
                </h3>
                <p className="text-sm mb-4" style={{ color: 'var(--text-2)' }}>
                  You are placing {fmtMoney(totalStake)} for a potential return of {fmtMoney(totalReturn)}.
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={handleConfirm}
                    disabled={isProcessing}
                    className="flex-1 py-3 rounded-lg font-semibold text-white disabled:opacity-50"
                    style={{ background: 'var(--win)' }}
                  >
                    {isProcessing ? 'Processing…' : 'Confirm'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowConfirmation(false)}
                    disabled={isProcessing}
                    className="btn-secondary flex-1 py-3 rounded-lg font-medium disabled:opacity-50"
                  >
                    Back
                  </button>
                </div>
              </div>
            ) : (
              <div className="px-5 py-4 space-y-2" style={{ background: 'var(--bg-elev)' }}>
                <button
                  type="button"
                  onClick={() => {
                    if (validationError) {
                      setError(validationError);
                      return;
                    }
                    setError('');
                    setShowConfirmation(true);
                  }}
                  disabled={!!validationError}
                  className="btn-primary w-full justify-center py-3 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Review &amp; {mode === 'parlay' ? 'Place Parlay' : 'Place Bet'}
                </button>
                <button type="button" onClick={onClose} className="btn-secondary w-full py-3 rounded-lg">
                  Edit slip
                </button>
                <p className="text-xs text-center pt-1" style={{ color: 'var(--text-4)' }}>
                  Please bet responsibly. If you need help, call 1-800-GAMBLER.
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
