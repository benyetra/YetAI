'use client';

import React, { useState } from 'react';
import { ArrowDown, ArrowUp } from 'lucide-react';
import { teamColor } from '@/lib/yetai-format';
import { teamLogoUrl } from '@/lib/team-logos';

const LEAGUE_COLORS: Record<string, string> = {
  NBA: '#C8102E',
  WNBA: '#F26C24',
  MLB: '#002D72',
  NFL: '#013369',
  NHL: '#000000',
  UCL: '#0D1B43',
  UFC: '#D20A0A',
  MLS: '#001E5E',
  NCAAF: '#013369',
  NCAAB: '#C8102E',
};

export function TeamGlyph({
  abbr,
  name,
  league,
  sportKey,
  size = 22,
}: {
  abbr: string;
  /** Full team name — used to resolve MLB/NFL logo SVGs */
  name?: string;
  league?: string;
  sportKey?: string;
  size?: number;
}) {
  const [logoFailed, setLogoFailed] = useState(false);
  const label = (name || abbr).trim();
  const logoSrc =
    !logoFailed && label
      ? teamLogoUrl(label, { league, sportKey, abbr })
      : null;

  if (logoSrc) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- local static SVGs
      <img
        src={logoSrc}
        alt=""
        role="presentation"
        className="team-logo"
        width={size}
        height={size}
        onError={() => setLogoFailed(true)}
        style={{ width: size, height: size }}
      />
    );
  }

  return (
    <span
      className="team-glyph"
      style={{
        background: teamColor(abbr),
        width: size,
        height: size,
        fontSize: Math.max(9, size * 0.42),
      }}
      aria-hidden
    >
      {abbr.slice(0, 3)}
    </span>
  );
}

export function LeagueChip({ league }: { league: string }) {
  const key = league.length <= 4 ? league : league.slice(0, 3).toUpperCase();
  return (
    <span
      style={{
        fontSize: 9.5,
        fontWeight: 600,
        letterSpacing: '.05em',
        padding: '2px 6px',
        borderRadius: 4,
        background: LEAGUE_COLORS[key] || LEAGUE_COLORS[league] || '#333',
        color: '#fff',
      }}
    >
      {league}
    </span>
  );
}

export function ConfidenceBar({
  value,
  label = 'AI Confidence',
}: {
  value: number;
  label?: string;
}) {
  const pct = value > 1 ? value : value * 100;
  return (
    <div className="confidence">
      <div className="conf-row">
        <span>{label}</span>
        <b>{Math.round(pct)}%</b>
      </div>
      <div className="conf-bar">
        <div className="conf-fill" style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
    </div>
  );
}

export function StatTile({
  label,
  value,
  delta,
  deltaKind = 'up',
  icon,
  sub,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  delta?: React.ReactNode;
  deltaKind?: 'up' | 'down' | 'neutral';
  icon?: React.ReactNode;
  sub?: React.ReactNode;
}) {
  const deltaClass =
    deltaKind === 'up' ? 'delta-up' : deltaKind === 'down' ? 'delta-down' : 'delta-neutral';
  return (
    <div className="stat">
      <div className="stat-label">
        {icon}
        {label}
      </div>
      <div className="stat-value mono">{value}</div>
      {(delta != null || sub != null) && (
        <div className="stat-foot">
          {delta != null && (
            <span className={`stat-delta ${deltaClass}`}>
              {deltaKind === 'up' && <ArrowUp size={11} />}
              {deltaKind === 'down' && <ArrowDown size={11} />}
              {delta}
            </span>
          )}
          {sub != null ? <span>{sub}</span> : null}
        </div>
      )}
    </div>
  );
}

export function SummaryRow({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5 }}>
      <span className="dim">{label}</span>
      <span
        className="mono"
        style={{
          color: highlight ? 'var(--win)' : 'var(--text)',
          fontWeight: highlight ? 500 : 400,
        }}
      >
        {value}
      </span>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  body?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      {icon ? <div className="empty-glyph">{icon}</div> : null}
      <div className="empty-title">{title}</div>
      {body ? <div className="empty-body">{body}</div> : null}
      {action ? <div style={{ marginTop: 14 }}>{action}</div> : null}
    </div>
  );
}

export function Sparkline({
  data,
  width = 80,
  height = 28,
  className,
}: {
  data: number[];
  width?: number;
  height?: number;
  className?: string;
}) {
  if (!data.length) return null;
  const max = Math.max(...data.map(Math.abs), 1);
  const mid = height / 2;
  const points = data
    .map((v, i) => {
      const x = (i / Math.max(data.length - 1, 1)) * width;
      const y = mid - (v / max) * (mid - 2);
      return `${x},${y}`;
    })
    .join(' ');
  return (
    <svg width={width} height={height} className={className} style={{ overflow: 'visible' }}>
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

