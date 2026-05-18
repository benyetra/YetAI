'use client';

import React, { useMemo, useState } from 'react';
import { Layers, Sparkles, Target, TrendingUp, Zap } from 'lucide-react';
import { DetailedPick, HeroAIPick } from '../picks';
import { StatTile } from '../primitives';
import type { DesignPick } from '../types';

export interface YetaiBetsScreenProps {
  picks: DesignPick[];
  hitRate?: number;
  roiLabel?: string;
  modelConfidence?: string;
  onAddToSlip?: (pick: DesignPick) => void;
  showMascot?: boolean;
}

export default function YetaiBetsScreen({
  picks,
  hitRate = 0,
  roiLabel,
  modelConfidence,
  onAddToSlip,
  showMascot = true,
}: YetaiBetsScreenProps) {
  const [filter, setFilter] = useState('All');
  const featured = picks[0];
  const rest = picks.slice(1);

  const leagues = useMemo(() => {
    const set = new Set(rest.map((p) => p.league));
    return ['All', ...Array.from(set)];
  }, [rest]);

  const filtered = filter === 'All' ? rest : rest.filter((p) => p.league === filter);

  return (
    <div data-screen-label="YetAI Bets">
      <div style={{ marginBottom: 24 }}>
        <h1 className="type-page-title">YetAI Bets</h1>
        <p style={{ color: 'var(--text-3)', fontSize: 13, marginTop: 4 }}>
          Premium AI-powered picks with full reasoning
        </p>
      </div>

      <div className="stat-grid" style={{ marginBottom: 18 }}>
        <StatTile
          label={
            <>
              <Target size={12} /> Today&apos;s hit rate
            </>
          }
          value={hitRate ? `${hitRate}%` : '—'}
          deltaKind="up"
        />
        <StatTile
          label={
            <>
              <TrendingUp size={12} /> 7-day ROI
            </>
          }
          value={roiLabel || '—'}
          deltaKind="up"
        />
        <StatTile
          label={
            <>
              <Zap size={12} /> Model confidence
            </>
          }
          value={modelConfidence || '—'}
          deltaKind="neutral"
        />
        <StatTile
          label={
            <>
              <Layers size={12} /> Picks today
            </>
          }
          value={picks.length}
          delta={`${Math.min(3, picks.length)} featured`}
          deltaKind="neutral"
        />
      </div>

      {featured ? (
        <HeroAIPick pick={featured} showMascot={showMascot} onAdd={onAddToSlip ? () => onAddToSlip(featured) : undefined} />
      ) : (
        <div className="card" style={{ padding: 32, textAlign: 'center', color: 'var(--text-3)' }}>
          <Sparkles size={24} style={{ margin: '0 auto 8px', opacity: 0.5 }} />
          No picks available right now.
        </div>
      )}

      {rest.length > 0 && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 24, marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
            <div className="section-title">More picks today</div>
            <div className="chip-row">
              {leagues.map((s) => (
                <button key={s} type="button" className={`chip ${filter === s ? 'active' : ''}`} onClick={() => setFilter(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 'var(--gap-grid)' }}>
            {filtered.map((p) => (
              <DetailedPick key={p.id} pick={p} onAdd={onAddToSlip ? () => onAddToSlip(p) : undefined} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
