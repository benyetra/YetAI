'use client';

import type { MouseEvent } from 'react';
import { Check, Clock, Share2, Sparkles, X } from 'lucide-react';
import { fmtMoney, fmtMoneyShort, fmtOdds } from '@/lib/yetai-format';

export type MyBetsBetRowProps = {
  pick: string;
  odds: number | string;
  status: string;
  matchup?: string;
  sport?: string;
  betType?: string;
  date?: string;
  stake: number;
  potentialWin?: number;
  profit?: number | null;
  legCount?: number;
  showYetAiSource?: boolean;
  onClick?: () => void;
  onShare?: (e: MouseEvent) => void;
};

export default function MyBetsBetRow({
  pick,
  odds,
  status,
  matchup,
  sport,
  betType,
  date,
  stake,
  potentialWin,
  profit,
  legCount,
  showYetAiSource,
  onClick,
  onShare,
}: MyBetsBetRowProps) {
  const normalized = status.toLowerCase();
  const isWon = normalized === 'won';
  const isLost = normalized === 'lost';
  const isPushed = normalized === 'pushed';
  const dotColor = isWon ? 'var(--win)' : isLost ? 'var(--loss)' : isPushed ? 'var(--text-2)' : 'var(--warn)';
  const dotBg = isWon ? 'var(--win-soft)' : isLost ? 'var(--loss-soft)' : isPushed ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.04)';

  const statusLabel = normalized.charAt(0).toUpperCase() + normalized.slice(1);
  const oddsDisplay = typeof odds === 'number' ? fmtOdds(odds) : odds;

  const profitDisplay =
    profit != null
      ? fmtMoney(profit, { signed: true }).replace(/^\+-/, '-')
      : potentialWin != null
        ? `→ ${fmtMoneyShort(potentialWin)}`
        : null;

  return (
    <div
      className="bet-row"
      style={onClick ? { cursor: 'pointer' } : undefined}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
    >
      <div className="status-dot" style={{ background: dotBg, color: dotColor }}>
        {isWon ? <Check size={13} /> : isLost ? <X size={13} /> : <Clock size={12} />}
      </div>
      <div className="bet-main">
        <div className="bet-headline">
          <span style={{ minWidth: 0 }}>{pick}</span>
          <span className="dim mono" style={{ fontSize: 12, fontWeight: 400 }}>
            {oddsDisplay}
          </span>
          <span className={`badge badge-${isWon ? 'win' : isLost ? 'loss' : isPushed ? 'pending' : 'pending'}`}>{statusLabel}</span>
          {legCount != null && legCount > 1 ? (
            <span className="badge badge-ai">{legCount}-Leg</span>
          ) : null}
        </div>
        <div className="bet-meta">
          {matchup ? <span>{matchup}</span> : null}
          {matchup && sport ? <span>·</span> : null}
          {sport ? <span>{sport}</span> : null}
          {(matchup || sport) && betType ? <span>·</span> : null}
          {betType ? <span>{betType}</span> : null}
          {(matchup || sport || betType) && date ? <span>·</span> : null}
          {date ? <span>{date}</span> : null}
          {showYetAiSource ? (
            <>
              <span>·</span>
              <span style={{ color: 'var(--accent)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Sparkles size={10} />
                YetAI
              </span>
            </>
          ) : null}
        </div>
      </div>
      <div className="bet-amt">
        {onShare ? (
          <button
            type="button"
            className="btn-ghost"
            style={{ padding: 4, marginBottom: 4, marginLeft: 'auto', display: 'flex' }}
            onClick={(e) => {
              e.stopPropagation();
              onShare(e);
            }}
            aria-label="Share bet"
          >
            <Share2 size={14} style={{ color: 'var(--text-3)' }} />
          </button>
        ) : null}
        <div className="stake">{fmtMoney(stake)}</div>
        {profitDisplay ? (
          <div
            className="potential"
            style={{
              color:
                profit != null
                  ? (profit > 0 ? 'var(--win)' : profit < 0 ? 'var(--loss)' : 'var(--text-3)')
                  : 'var(--text-3)',
            }}
          >
            {profitDisplay}
          </div>
        ) : null}
      </div>
    </div>
  );
}
