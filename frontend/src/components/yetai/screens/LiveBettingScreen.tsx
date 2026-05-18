'use client';

import React from 'react';
import { fmtMoney, fmtMoneyShort } from '@/lib/yetai-format';
import { LiveGameCard } from '../live';
import { StatTile } from '../primitives';
import type { DesignGame, SlipItem } from '../types';

export interface LiveBettingScreenProps {
  games: DesignGame[];
  activeBets?: number;
  staked?: number;
  potentialPayout?: number;
  cashOutAvailable?: number;
  todayPnl?: number;
  onAddToSlip?: (item: SlipItem) => void;
  loading?: boolean;
}

export default function LiveBettingScreen({
  games,
  activeBets = 0,
  staked = 0,
  potentialPayout = 0,
  cashOutAvailable = 0,
  todayPnl = 0,
  onAddToSlip,
  loading,
}: LiveBettingScreenProps) {
  return (
    <div data-screen-label="Live Betting">
      <div style={{ display: 'flex', alignItems: 'end', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span className="badge badge-live">Live</span>
            <span className="mono" style={{ fontSize: 12.5, color: 'var(--text-3)' }}>
              {games.length} games in progress
            </span>
          </div>
          <h1 className="type-page-title">In-game betting</h1>
          <p style={{ color: 'var(--text-3)', fontSize: 13, marginTop: 4 }}>Real-time odds and instant cash-out</p>
        </div>
      </div>

      <div className="stat-grid" style={{ marginBottom: 24 }}>
        <StatTile label="Active live bets" value={activeBets} delta={staked ? `${fmtMoneyShort(staked)} staked` : undefined} deltaKind="neutral" />
        <StatTile label="Potential payout" value={fmtMoney(potentialPayout)} delta="if all hit" deltaKind="up" />
        <StatTile label="Cash-out available" value={fmtMoney(cashOutAvailable)} deltaKind="neutral" />
        <StatTile label="Today's live P&L" value={fmtMoney(todayPnl, { signed: true })} deltaKind={todayPnl >= 0 ? 'up' : 'neutral'} />
      </div>

      <div className="section-head">
        <div className="section-title">Live games</div>
      </div>

      {loading ? (
        <div className="card" style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>
          Loading live markets…
        </div>
      ) : games.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>
          No live games right now. Check back when games are in progress.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 'var(--gap-grid)' }}>
          {games.map((g) => (
            <LiveGameCard key={g.id} game={g} onAdd={onAddToSlip || (() => {})} />
          ))}
        </div>
      )}
    </div>
  );
}
