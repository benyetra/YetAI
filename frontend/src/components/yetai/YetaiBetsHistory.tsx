'use client';

import React from 'react';
import { Check, Clock, Minus, X } from 'lucide-react';
import { apiBetToDesignPick } from '@/lib/yetai-mappers';
import { fmtOdds } from '@/lib/yetai-format';
import type { DesignPick } from './types';

export interface YetaiHistoryStats {
  period_days: number;
  total: number;
  won: number;
  lost: number;
  pushed: number;
  expired?: number;
  pending_manual_review?: number;
  win_rate: number;
  units: number;
}

export interface YetaiHistoryBet {
  id: string;
  sport?: string;
  game?: string;
  home_team?: string;
  away_team?: string;
  bet_type?: string;
  pick: string;
  odds: string | number;
  confidence: number;
  reasoning?: string;
  game_time?: string;
  status?: string;
  is_premium?: boolean;
  settled_at?: string | null;
  created_at?: string | null;
  result?: string | null;
}

function statusIcon(status: string) {
  if (status === 'won') return <Check size={14} />;
  if (status === 'lost') return <X size={14} />;
  if (status === 'pushed') return <Minus size={14} />;
  if (status === 'expired' || status === 'pending_manual_review') return <Clock size={13} />;
  return <Clock size={13} />;
}

function statusStyle(status: string): { background: string; color: string } {
  if (status === 'won') return { background: 'var(--win-soft)', color: 'var(--win)' };
  if (status === 'lost') return { background: 'var(--loss-soft)', color: 'var(--loss)' };
  if (status === 'expired' || status === 'pending_manual_review') {
    return { background: 'rgba(255,255,255,0.06)', color: 'var(--text-3)' };
  }
  return { background: 'rgba(255,255,255,0.06)', color: 'var(--text-2)' };
}

function statusLabel(status: string): string {
  if (status === 'pending_manual_review') return 'review';
  return status;
}

function formatSettledDate(iso?: string | null): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return '';
  }
}

export default function YetaiBetsHistory({
  bets,
  stats,
  loading,
}: {
  bets: YetaiHistoryBet[];
  stats: YetaiHistoryStats | null;
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="min-h-[24vh] flex items-center justify-center">
        <div
          className="animate-spin rounded-full h-10 w-10 border-2 border-transparent"
          style={{ borderBottomColor: 'var(--accent)' }}
        />
      </div>
    );
  }

  const picks: DesignPick[] = bets.map((b) => apiBetToDesignPick(b));

  return (
    <div>
      {stats && stats.total > 0 ? (
        <div className="stat-grid" style={{ marginBottom: 18 }}>
          <div className="card stat-tile">
            <div className="section-sub">Win rate ({stats.period_days}d)</div>
            <div className="mono" style={{ fontSize: 22, fontWeight: 500 }}>
              {stats.win_rate}%
            </div>
            <div className="section-sub" style={{ marginTop: 4 }}>
              {stats.won}W · {stats.lost}L
              {stats.pushed > 0 ? ` · ${stats.pushed}P` : ''}
              {(stats.expired ?? 0) > 0 ? ` · ${stats.expired} void` : ''}
            </div>
          </div>
          <div className="card stat-tile">
            <div className="section-sub">Record</div>
            <div className="mono" style={{ fontSize: 22, fontWeight: 500 }}>
              {stats.total}
            </div>
            <div className="section-sub" style={{ marginTop: 4 }}>
              settled picks
            </div>
          </div>
          <div className="card stat-tile">
            <div className="section-sub">Units (1u flat)</div>
            <div
              className="mono"
              style={{
                fontSize: 22,
                fontWeight: 500,
                color: stats.units >= 0 ? 'var(--win)' : 'var(--loss)',
              }}
            >
              {stats.units > 0 ? '+' : ''}
              {stats.units}
            </div>
            <div className="section-sub" style={{ marginTop: 4 }}>
              last {stats.period_days} days
            </div>
          </div>
        </div>
      ) : (
        <div className="card" style={{ padding: 24, marginBottom: 18, color: 'var(--text-3)' }}>
          No settled YetAI picks in this window yet. Results appear here after games finish and
          picks are graded.
        </div>
      )}

      {picks.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="section-head" style={{ padding: '14px 16px', marginBottom: 0 }}>
            <div>
              <div className="section-title">Pick history</div>
              <div className="section-sub">Graded YetAI promoted bets</div>
            </div>
          </div>
          <div>
            {bets.map((bet, i) => {
              const status = (bet.status || 'pending').toLowerCase();
              const pick = picks[i];
              const style = statusStyle(status);
              return (
                <div
                  key={bet.id}
                  className="act-row"
                  style={{ borderTop: i === 0 ? '1px solid var(--border)' : undefined }}
                >
                  <div className="act-icon" style={style}>
                    {statusIcon(status)}
                  </div>
                  <div className="act-text" style={{ minWidth: 0 }}>
                    <div className="act-title">
                      {pick.pick}{' '}
                      <span className="dim mono" style={{ marginLeft: 4 }}>
                        {fmtOdds(pick.odds)}
                      </span>
                    </div>
                    <div className="act-sub">
                      {pick.matchup}
                      {pick.league ? ` · ${pick.league}` : ''}
                      {formatSettledDate(bet.settled_at || bet.created_at)
                        ? ` · ${formatSettledDate(bet.settled_at || bet.created_at)}`
                        : ''}
                    </div>
                    {bet.result ? (
                      <div
                        style={{
                          fontSize: 12,
                          color: 'var(--text-3)',
                          marginTop: 4,
                          lineHeight: 1.35,
                        }}
                      >
                        {bet.result}
                      </div>
                    ) : null}
                  </div>
                  <span
                    className={`badge badge-${
                      status === 'won'
                        ? 'win'
                        : status === 'lost'
                          ? 'loss'
                          : 'pending'
                    }`}
                  >
                    {statusLabel(status)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
