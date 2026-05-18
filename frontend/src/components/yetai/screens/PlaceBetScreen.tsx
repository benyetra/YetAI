'use client';

import React, { useMemo, useState } from 'react';
import { AccountMini, BetSlipPanel, GameOddsRow } from '../betting';
import type { DesignGame, SlipItem } from '../types';

export interface PlaceBetScreenProps {
  games: DesignGame[];
  slip: SlipItem[];
  setSlip: React.Dispatch<React.SetStateAction<SlipItem[]>>;
  onAddToSlip: (item: SlipItem) => void;
  onPlaceSlip?: () => void;
  placing?: boolean;
  bankroll?: number;
  loading?: boolean;
}

export default function PlaceBetScreen({
  games,
  slip,
  setSlip,
  onAddToSlip,
  onPlaceSlip,
  placing,
  bankroll,
  loading,
}: PlaceBetScreenProps) {
  const [sport, setSport] = useState('All');

  const sports = useMemo(() => {
    const set = new Set(games.map((g) => g.league));
    return ['All', ...Array.from(set)];
  }, [games]);

  const filtered = sport === 'All' ? games : games.filter((g) => g.league === sport);

  const addUnique = (item: SlipItem) => {
    setSlip((prev) => {
      if (prev.some((s) => s.id === item.id)) {
        return prev.filter((s) => s.id !== item.id);
      }
      return [...prev, item];
    });
    onAddToSlip(item);
  };

  return (
    <div className="content with-rail" data-screen-label="Place Bet" style={{ padding: 0 }}>
      <div className="col-main">
        <div style={{ marginBottom: 18 }}>
          <h1 className="type-page-title" style={{ fontSize: 24 }}>Place Bet</h1>
          <p style={{ color: 'var(--text-3)', fontSize: 13, marginTop: 4 }}>Real-time odds across major sportsbooks</p>
        </div>

        <div className="chip-row" style={{ marginBottom: 16 }}>
          {sports.map((s) => (
            <button key={s} type="button" className={`chip ${sport === s ? 'active' : ''}`} onClick={() => setSport(s)}>
              {s}
            </button>
          ))}
        </div>

        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="col-head">
            <div>Matchup</div>
            <div>Spread</div>
            <div>Total</div>
            <div>Moneyline</div>
          </div>
          {loading ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>Loading odds…</div>
          ) : filtered.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>No games for this filter.</div>
          ) : (
            filtered.map((g) => <GameOddsRow key={g.id} game={g} slip={slip} onAdd={addUnique} />)
          )}
        </div>
      </div>
      <div className="col-rail">
        <BetSlipPanel slip={slip} setSlip={setSlip} onPlace={onPlaceSlip} placing={placing} />
        <AccountMini bankroll={bankroll} />
      </div>
    </div>
  );
}
