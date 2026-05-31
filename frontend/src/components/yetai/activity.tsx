'use client';

import React from 'react';
import Link from 'next/link';
import { Check, ChevronRight, Clock, X } from 'lucide-react';
import { fmtMoney, fmtMoneyShort, fmtOdds } from '@/lib/yetai-format';
import type { ActivityBet } from './types';

function pnlDayLabels(count: number): string[] {
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(today);
    d.setDate(d.getDate() - (count - 1 - i));
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  });
}

export function PerformanceChart({
  dailyPnl,
  lifetimeProfit,
}: {
  dailyPnl: number[];
  lifetimeProfit?: number;
}) {
  const history = dailyPnl.length > 0 ? dailyPnl : Array(14).fill(0);
  const labels = pnlDayLabels(history.length);
  const max = Math.max(...history.map(Math.abs), 1);
  const periodTotal = history.reduce((s, v) => s + v, 0);
  const axisStart = labels[0] ?? 'Start';
  const axisMid = labels[Math.floor(labels.length / 2)] ?? 'Mid';
  const axisEnd = labels[labels.length - 1] ?? 'Today';

  return (
    <div className="card">
      <div className="section-head" style={{ marginBottom: 6 }}>
        <div>
          <div className="section-title">Performance</div>
          <div className="section-sub">Last {history.length} days · Daily P&L</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div
            className="mono"
            style={{
              fontSize: 22,
              fontWeight: 500,
              color: periodTotal >= 0 ? 'var(--win)' : 'var(--loss)',
            }}
          >
            {fmtMoney(periodTotal, { signed: true })}
          </div>
          <div className="section-sub">{history.length}-day P&L</div>
          {lifetimeProfit != null && (
            <div className="section-sub" style={{ marginTop: 4 }}>
              Lifetime {fmtMoney(lifetimeProfit, { signed: true })}
            </div>
          )}
        </div>
      </div>
      <div className="pnl-chart-bars">
        {history.map((v, i) => {
          const pct = Math.max(2, (Math.abs(v) / max) * 50);
          const barClass = v > 0 ? 'win above' : v < 0 ? 'loss below' : 'zero';
          return (
            <div key={i} className="chart-bar-col">
              <div
                className={`chart-bar ${barClass}`}
                style={{ height: `${pct}%` }}
                title={`${labels[i]}: ${fmtMoney(v, { signed: true })}`}
              />
            </div>
          );
        })}
      </div>
      <div className="chart-axis">
        <span>{axisStart}</span>
        <span>{axisMid}</span>
        <span>{axisEnd}</span>
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
