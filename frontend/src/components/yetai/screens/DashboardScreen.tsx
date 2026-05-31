'use client';

import React from 'react';
import Link from 'next/link';
import { Clock, DollarSign, Flame, Plus, Sparkles, Target } from 'lucide-react';
import { PerformanceChart, RecentActivity } from '../activity';
import { PickCard } from '../picks';
import { StatTile } from '../primitives';
import { fmtMoney, fmtMoneyShort } from '@/lib/yetai-format';
import type { ActivityBet, DesignPick } from '../types';

export interface DashboardScreenProps {
  userName?: string;
  bankroll?: number;
  profitChange?: number;
  winRate?: number;
  winRateDelta?: number;
  openBets?: number;
  openPotential?: number;
  streak?: number;
  featuredPicks: DesignPick[];
  recentBets: ActivityBet[];
  dailyPnl?: number[];
  onAddToSlip?: (pick: DesignPick) => void;
}

function greetingLine(name?: string) {
  const hour = new Date().getHours();
  const part = hour < 12 ? 'Morning' : hour < 17 ? 'Afternoon' : 'Evening';
  return `${part}, ${name || 'there'}.`;
}

export default function DashboardScreen({
  userName,
  bankroll = 0,
  profitChange = 0,
  winRate = 0,
  winRateDelta = 0,
  openBets = 0,
  openPotential = 0,
  streak = 0,
  featuredPicks,
  recentBets,
  dailyPnl = [],
  onAddToSlip,
}: DashboardScreenProps) {
  const now = new Date();
  const dateLabel = now.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });
  const timeLabel = now.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', timeZoneName: 'short' });

  return (
    <div data-screen-label="Dashboard">
      <div style={{ display: 'flex', alignItems: 'end', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ color: 'var(--text-3)', fontSize: 12.5, letterSpacing: '.04em', textTransform: 'uppercase', marginBottom: 6 }}>
            {dateLabel} · {timeLabel}
          </div>
          <h1 className="type-page-title">
            {greetingLine(userName)}{' '}
            <span style={{ color: 'var(--text-3)' }}>Your edge starts here.</span>
          </h1>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Link href="/bets" className="btn">
            <Clock size={14} /> History
          </Link>
          <Link href="/bet" className="btn btn-primary">
            <Plus size={14} /> Place Bet
          </Link>
        </div>
      </div>

      <div className="stat-grid">
        <StatTile
          label={
            <>
              <DollarSign size={12} /> Bankroll
            </>
          }
          value={fmtMoney(bankroll)}
          delta={
            profitChange
              ? `${profitChange >= 0 ? '+' : ''}${fmtMoneyShort(profitChange)} vs prev wk`
              : undefined
          }
          deltaKind={profitChange >= 0 ? 'up' : 'down'}
        />
        <StatTile
          label={
            <>
              <Target size={12} /> Win Rate · All time
            </>
          }
          value={`${winRate.toFixed(0)}%`}
          delta={
            winRateDelta
              ? `${winRateDelta >= 0 ? '+' : ''}${winRateDelta}pp vs prev wk`
              : undefined
          }
          deltaKind={winRateDelta >= 0 ? 'up' : 'down'}
        />
        <StatTile
          label="Open Bets"
          value={openBets}
          delta={openPotential ? `${fmtMoneyShort(openPotential)} potential` : undefined}
          deltaKind="neutral"
        />
        <StatTile
          label={
            <>
              <Flame size={12} /> Hot Streak
            </>
          }
          value={`${streak}W`}
          delta={streak > 0 ? 'Current run' : undefined}
          deltaKind="up"
        />
      </div>

      <div className="section-head">
        <div>
          <div className="section-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Sparkles size={15} style={{ color: 'var(--accent)' }} />
            AI Picks for Tonight
          </div>
          <div className="section-sub">
            {featuredPicks.length} high-confidence plays
          </div>
        </div>
        <Link href="/predictions" className="section-action">
          See all picks →
        </Link>
      </div>

      {featuredPicks.length > 0 ? (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
            gap: 'var(--gap-grid)',
            marginBottom: 28,
          }}
        >
          {featuredPicks.slice(0, 3).map((p) => (
            <PickCard key={p.id} pick={p} onAdd={onAddToSlip ? () => onAddToSlip(p) : undefined} />
          ))}
        </div>
      ) : (
        <div className="card" style={{ padding: 24, marginBottom: 28, textAlign: 'center', color: 'var(--text-3)' }}>
          No AI picks published yet. Check back soon or visit YetAI Bets.
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)', gap: 'var(--gap-grid)' }}>
        <PerformanceChart dailyPnl={dailyPnl} lifetimeProfit={bankroll} />
        <RecentActivity bets={recentBets} />
      </div>
    </div>
  );
}
