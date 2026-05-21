'use client';

import React from 'react';
import { Crown, Eye, Plus, Sparkles } from 'lucide-react';
import { ConfidenceBar, LeagueChip, TeamGlyph } from './primitives';
import { fmtOdds, teamAbbr } from '@/lib/yetai-format';
import type { DesignPick } from './types';

function splitMatchup(matchup: string): [string, string] {
  if (matchup.includes('@')) {
    const [a, b] = matchup.split('@').map((s) => s.trim());
    return [a, b];
  }
  const parts = matchup.split(/\s+vs\.?\s+/i);
  return [parts[0]?.trim() || 'Away', parts[1]?.trim() || 'Home'];
}

export function PickCard({ pick, onAdd }: { pick: DesignPick; onAdd?: () => void }) {
  const [away, home] = splitMatchup(pick.matchup);

  return (
    <div className="pick">
      <div className="pick-head">
        <div className="pick-league">
          <LeagueChip league={pick.league} />
          <span>{pick.game_time || pick.sport}</span>
        </div>
        <span className="badge badge-ai">
          <Sparkles size={9} /> {pick.units ?? 1}u
        </span>
      </div>
      <div className="pick-body">
        <div className="pick-teams">
          <div className="pick-team">
            <span className="t-name">
              <TeamGlyph abbr={teamAbbr(away)} /> {away}
            </span>
          </div>
          <div className="pick-team">
            <span className="t-name">
              <TeamGlyph abbr={teamAbbr(home)} /> {home}
            </span>
          </div>
        </div>
        <div className="pick-call">
          <div className="pick-call-text">
            <strong>{pick.pick}</strong>
            {pick.bet_type ? ` · ${pick.bet_type}` : ''}
          </div>
          <div className="odds mono">{fmtOdds(pick.odds)}</div>
        </div>
        <ConfidenceBar value={pick.confidence} />
        <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
          {onAdd && (
            <button type="button" className="btn btn-primary btn-sm" style={{ flex: 1, justifyContent: 'center' }} onClick={onAdd}>
              <Plus size={13} /> Add to slip
            </button>
          )}
          <button type="button" className="btn btn-sm" style={{ minWidth: 36, justifyContent: 'center' }} title="Why this pick?">
            <Eye size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}

export function HeroAIPick({
  pick,
  onAdd,
}: {
  pick: DesignPick;
  onAdd?: () => void;
}) {
  const [away, home] = splitMatchup(pick.matchup);
  const confPct = Math.round(pick.confidence > 1 ? pick.confidence : pick.confidence * 100);

  return (
    <div className="hero-ai">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, position: 'relative', zIndex: 1 }}>
        <span className="badge badge-gold">
          <Crown size={10} /> Top pick
        </span>
        <span className="badge badge-ai">
          <Sparkles size={10} /> {confPct}% confidence
        </span>
        <span className="badge" style={{ background: 'rgba(255,255,255,0.06)', color: 'var(--text-2)' }}>
          {pick.league}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.4fr) minmax(0,1fr)', gap: 28, position: 'relative', zIndex: 1 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 20, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <TeamGlyph abbr={teamAbbr(away)} size={36} />
              <div style={{ fontSize: 15, fontWeight: 500 }}>{away}</div>
            </div>
            <span style={{ color: 'var(--text-4)', fontFamily: 'var(--mono)', fontSize: 13 }}>@</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <TeamGlyph abbr={teamAbbr(home)} size={36} />
              <div style={{ fontSize: 15, fontWeight: 500 }}>{home}</div>
            </div>
          </div>
          {pick.reasoning && (
            <div style={{ fontSize: 13, color: 'var(--text-3)', lineHeight: 1.6, maxWidth: 560 }}>
              <span style={{ color: 'var(--text)', fontWeight: 500, display: 'block', marginBottom: 6 }}>Why we like it</span>
              {pick.reasoning}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 12, padding: 18 }}>
            <div style={{ fontSize: 11, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.06em' }}>The pick</div>
            <div style={{ fontSize: 22, fontWeight: 500, marginTop: 6 }}>{pick.pick}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 14, fontSize: 12 }}>
              <div>
                <div className="dim" style={{ fontSize: 10.5, textTransform: 'uppercase' }}>Odds</div>
                <div className="mono" style={{ fontSize: 15, fontWeight: 500, marginTop: 2 }}>{fmtOdds(pick.odds)}</div>
              </div>
              <div>
                <div className="dim" style={{ fontSize: 10.5, textTransform: 'uppercase' }}>Stake</div>
                <div className="mono" style={{ fontSize: 15, fontWeight: 500, marginTop: 2 }}>{pick.units ?? 1}u</div>
              </div>
              {pick.edge && (
                <div>
                  <div className="dim" style={{ fontSize: 10.5, textTransform: 'uppercase' }}>Edge</div>
                  <div className="mono" style={{ fontSize: 15, fontWeight: 500, marginTop: 2, color: 'var(--win)' }}>{pick.edge}</div>
                </div>
              )}
            </div>
          </div>
          {onAdd && (
            <button type="button" className="btn btn-primary btn-block" onClick={onAdd}>
              <Plus size={14} /> Add to bet slip
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function DetailedPick({ pick, onAdd }: { pick: DesignPick; onAdd?: () => void }) {
  const confPct = Math.round(pick.confidence > 1 ? pick.confidence : pick.confidence * 100);
  return (
    <div className="card" style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <LeagueChip league={pick.league} />
          <span style={{ fontSize: 13, color: 'var(--text-2)' }}>{pick.matchup}</span>
        </div>
        <span className="badge badge-ai">{confPct}%</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div style={{ fontSize: 18, fontWeight: 500 }}>{pick.pick}</div>
        <div className="mono" style={{ fontSize: 15, color: 'var(--text-2)' }}>{fmtOdds(pick.odds)}</div>
      </div>
      {pick.reasoning && <div style={{ fontSize: 12.5, color: 'var(--text-3)', lineHeight: 1.55 }}>{pick.reasoning}</div>}
      <ConfidenceBar value={pick.confidence} />
      <div style={{ display: 'flex', gap: 14, fontSize: 11.5, color: 'var(--text-3)', paddingTop: 4, flexWrap: 'wrap' }}>
        <div>
          <span className="dim">Stake</span> <span className="mono" style={{ color: 'var(--text)' }}> {pick.units ?? 1}u</span>
        </div>
        {pick.edge && (
          <div>
            <span className="dim">Edge</span> <span className="mono" style={{ color: 'var(--win)' }}> {pick.edge}</span>
          </div>
        )}
        {onAdd && (
          <div style={{ marginLeft: 'auto' }}>
            <button type="button" className="btn btn-sm" onClick={onAdd}>
              <Plus size={12} /> Add
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
