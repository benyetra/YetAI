'use client';

import React from 'react';
import Link from 'next/link';
import { Check, ChevronRight, Clock, X } from 'lucide-react';
import { fmtMoney, fmtMoneyShort, fmtOdds } from '@/lib/yetai-format';
import type { ActivityBet } from './types';

export function PerformanceChart({ dailyPnl }: { dailyPnl: number[] }) {
  const history = dailyPnl.length > 0 ? dailyPnl : [0, 0, 0, 0, 0, 0, 0];
  const max = Math.max(...history.map(Math.abs), 1);
  const total = history.reduce((s, v) => s + v, 0);

  return (
    <div className="card">
      <div className="section-head" style={{ marginBottom: 6 }}>
        <div>
          <div className="section-title">Performance</div>
          <div className="section-sub">Last {history.length} days · Daily P&L</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="mono" style={{ fontSize: 22, fontWeight: 500, color: total >= 0 ? 'var(--win)' : 'var(--loss)' }}>
            {fmtMoney(total, { signed: true })}
          </div>
          <div className="section-sub">net profit</div>
        </div>
      </div>
      <div className="chart-bars">
        {history.map((v, i) => (
          <div
            key={i}
            className={`chart-bar ${v > 0 ? 'win' : v < 0 ? 'loss' : 'zero'}`}
            style={{
              height: `${Math.max(4, (Math.abs(v) / max) * 100)}%`,
              alignSelf: v < 0 ? 'flex-start' : 'flex-end',
            }}
            title={`Day ${i + 1}: ${fmtMoney(v, { signed: true })}`}
          />
        ))}
      </div>
      <div className="chart-axis">
        <span>Start</span>
        <span>Mid</span>
        <span>Today</span>
      </div>
    </div>
  );
}

export function RecentActivity({ bets, historyHref = '/bets' }: { bets: ActivityBet[]; historyHref?: string }) {
  return (
    <div className="card">
      <div className="section-head" style={{ marginBottom: 6 }}>
        <div>
          <div className="section-title">Recent Bets</div>
          <div className="section-sub">Your last {Math.min(bets.length, 5)} wagers</div>
        </div>
        <Link href={historyHref} className="section-action">
          All <ChevronRight size={12} />
        </Link>
      </div>
      <div>
        {bets.length === 0 ? (
          <p style={{ fontSize: 13, color: 'var(--text-3)', padding: '12px 0' }}>No recent bets yet.</p>
        ) : (
          bets.slice(0, 5).map((b) => (
            <div key={b.id} className="act-row">
              <div
                className="act-icon"
                style={{
                  background: b.status === 'won' ? 'var(--win-soft)' : b.status === 'lost' ? 'var(--loss-soft)' : 'rgba(255,255,255,0.05)',
                  color: b.status === 'won' ? 'var(--win)' : b.status === 'lost' ? 'var(--loss)' : 'var(--text-2)',
                }}
              >
                {b.status === 'won' ? <Check size={14} /> : b.status === 'lost' ? <X size={14} /> : <Clock size={13} />}
              </div>
              <div className="act-text">
                <div className="act-title">
                  {b.pick} <span className="dim mono" style={{ marginLeft: 4 }}>{fmtOdds(b.odds)}</span>
                </div>
                <div className="act-sub">
                  {b.matchup}
                  {b.date ? ` · ${new Date(b.date).toLocaleDateString()}` : ''} · {b.source}
                </div>
              </div>
              <span className={`badge badge-${b.status === 'won' ? 'win' : b.status === 'lost' ? 'loss' : 'pending'}`}>{b.status}</span>
              <span
                className="act-amt mono"
                style={{ color: b.status === 'won' ? 'var(--win)' : b.status === 'lost' ? 'var(--loss)' : 'var(--text-2)' }}
              >
                {b.status === 'pending'
                  ? fmtMoneyShort(b.stake ?? 0)
                  : b.status === 'won'
                    ? `+${fmtMoneyShort((b.payout ?? 0) - (b.stake ?? 0))}`
                    : `-${fmtMoneyShort(b.stake ?? 0)}`}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
