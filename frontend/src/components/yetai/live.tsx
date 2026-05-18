'use client';

import React from 'react';
import { ChevronRight } from 'lucide-react';
import { LeagueChip, TeamGlyph } from './primitives';
import { fmtOdds } from '@/lib/yetai-format';
import type { DesignGame, SlipItem } from './types';

export function LiveGameCard({
  game,
  onAdd,
}: {
  game: DesignGame;
  onAdd: (item: SlipItem) => void;
}) {
  const matchup = `${game.away.name} @ ${game.home.name}`;
  const awayScore = game.away.score ?? 0;
  const homeScore = game.home.score ?? 0;

  const add = (key: string, label: string, odds: number) =>
    onAdd({
      id: `${game.id}-${key}`,
      gameId: game.id,
      key,
      label,
      odds,
      matchup,
      sportKey: game.sport_key,
      rawGame: game.raw,
    });

  return (
    <div className="live-card">
      <div className="live-head">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <LeagueChip league={game.league} />
          <span className="badge badge-live">Live</span>
          <span className="mono" style={{ color: 'var(--text-2)' }}>{game.tag}</span>
        </div>
        <button type="button" className="btn-ghost" style={{ fontSize: 11.5 }}>
          Details <ChevronRight size={11} />
        </button>
      </div>
      <div className="live-score">
        <div className="live-team">
          <TeamGlyph abbr={game.away.abbr} size={28} />
          <div>
            <div style={{ fontSize: 13.5 }}>{game.away.name}</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-3)' }}>Away</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="live-score-num">{awayScore}</span>
          <span className="live-divider">·</span>
          <span className="live-score-num">{homeScore}</span>
        </div>
        <div className="live-team away">
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 13.5 }}>{game.home.name}</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-3)' }}>Home</div>
          </div>
          <TeamGlyph abbr={game.home.abbr} size={28} />
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, marginTop: 4 }}>
        <button type="button" className="odds-btn" onClick={() => add('ml-away', `${game.away.abbr} ML`, game.ml.away)}>
          <span className="o-line">{game.away.abbr} ML</span>
          <span className="o-val">{fmtOdds(game.ml.away)}</span>
        </button>
        <button
          type="button"
          className="odds-btn"
          onClick={() =>
            add(
              'spread-home',
              `${game.home.abbr} ${game.spread.home}`,
              game.spread.homeOdds
            )
          }
        >
          <span className="o-line">Spread</span>
          <span className="o-val">
            {typeof game.spread.home === 'number' && game.spread.home > 0 ? '+' : ''}
            {game.spread.home}
          </span>
        </button>
        <button type="button" className="odds-btn" onClick={() => add('total-over', `Over ${game.total.line}`, game.total.over)}>
          <span className="o-line">O/U</span>
          <span className="o-val">{game.total.line}</span>
        </button>
      </div>
    </div>
  );
}
