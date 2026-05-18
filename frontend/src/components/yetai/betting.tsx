'use client';

import React, { useMemo, useState } from 'react';
import { Layers, X } from 'lucide-react';
import { LeagueChip, TeamGlyph } from './primitives';
import { calcPayout, fmtMoney, fmtOdds } from '@/lib/yetai-format';
import { spreadLabel } from '@/lib/yetai-odds';
import type { DesignGame, SlipItem } from './types';

function SlipRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5 }}>
      <span style={{ color: 'var(--text-3)' }}>{label}</span>
      <span className="mono" style={{ color: highlight ? 'var(--win)' : 'var(--text)', fontWeight: highlight ? 500 : 400 }}>
        {value}
      </span>
    </div>
  );
}

export function GameOddsRow({
  game,
  slip,
  onAdd,
}: {
  game: DesignGame;
  slip: SlipItem[];
  onAdd: (item: SlipItem) => void;
}) {
  const isInSlip = (key: string) => slip.some((s) => s.gameId === game.id && s.key === key);
  const matchup = `${game.away.name} @ ${game.home.name}`;

  const makeBet = (key: string, label: string, odds: number): SlipItem => ({
    id: `${game.id}-${key}`,
    gameId: game.id,
    key,
    label,
    odds,
    matchup,
    sportKey: game.sport_key,
    rawGame: game.raw,
  });

  const spreadAway = game.spread.away;
  const spreadHome = game.spread.home;

  return (
    <div className="game-row">
      <div className="game-teams">
        <div className="game-team">
          <TeamGlyph abbr={game.away.abbr} size={20} />
          <span className="t-name">{game.away.name}</span>
          {game.away.rec ? <span className="dim mono" style={{ fontSize: 11 }}>{game.away.rec}</span> : null}
        </div>
        <div className="game-team">
          <TeamGlyph abbr={game.home.abbr} size={20} />
          <span className="t-name">{game.home.name}</span>
          {game.home.rec ? <span className="dim mono" style={{ fontSize: 11 }}>{game.home.rec}</span> : null}
        </div>
        <div className="game-time">
          <LeagueChip league={game.league} /> · {game.time}
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <button
          type="button"
          className={`odds-btn ${isInSlip('spread-away') ? 'selected' : ''}`}
          onClick={() => onAdd(makeBet('spread-away', spreadLabel(game.away.abbr, spreadAway), game.spread.awayOdds))}
        >
          <span className="o-line">{typeof spreadAway === 'string' ? spreadAway : (Number(spreadAway) > 0 ? '+' : '') + spreadAway}</span>
          <span className="o-val">{fmtOdds(game.spread.awayOdds)}</span>
        </button>
        <button
          type="button"
          className={`odds-btn ${isInSlip('spread-home') ? 'selected' : ''}`}
          onClick={() => onAdd(makeBet('spread-home', spreadLabel(game.home.abbr, spreadHome), game.spread.homeOdds))}
        >
          <span className="o-line">{typeof spreadHome === 'string' ? spreadHome : (Number(spreadHome) > 0 ? '+' : '') + spreadHome}</span>
          <span className="o-val">{fmtOdds(game.spread.homeOdds)}</span>
        </button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <button
          type="button"
          className={`odds-btn ${isInSlip('total-over') ? 'selected' : ''}`}
          onClick={() => onAdd(makeBet('total-over', `Over ${game.total.line}`, game.total.over))}
        >
          <span className="o-line">O {game.total.line}</span>
          <span className="o-val">{fmtOdds(game.total.over)}</span>
        </button>
        <button
          type="button"
          className={`odds-btn ${isInSlip('total-under') ? 'selected' : ''}`}
          onClick={() => onAdd(makeBet('total-under', `Under ${game.total.line}`, game.total.under))}
        >
          <span className="o-line">U {game.total.line}</span>
          <span className="o-val">{fmtOdds(game.total.under)}</span>
        </button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <button
          type="button"
          className={`odds-btn ${isInSlip('ml-away') ? 'selected' : ''}`}
          onClick={() => onAdd(makeBet('ml-away', `${game.away.abbr} ML`, game.ml.away))}
        >
          <span className="o-line">{game.away.abbr}</span>
          <span className="o-val">{fmtOdds(game.ml.away)}</span>
        </button>
        <button
          type="button"
          className={`odds-btn ${isInSlip('ml-home') ? 'selected' : ''}`}
          onClick={() => onAdd(makeBet('ml-home', `${game.home.abbr} ML`, game.ml.home))}
        >
          <span className="o-line">{game.home.abbr}</span>
          <span className="o-val">{fmtOdds(game.ml.home)}</span>
        </button>
      </div>
    </div>
  );
}

export function BetSlipPanel({
  slip,
  setSlip,
  onPlace,
  placing,
}: {
  slip: SlipItem[];
  setSlip: React.Dispatch<React.SetStateAction<SlipItem[]>>;
  onPlace?: () => void;
  placing?: boolean;
}) {
  const [mode, setMode] = useState<'single' | 'parlay'>('single');
  const [stake, setStake] = useState(50);

  const parlayMultiplier = useMemo(
    () =>
      slip.reduce((acc, b) => {
        const o = b.odds;
        return acc * (o > 0 ? 1 + o / 100 : 1 + 100 / Math.abs(o));
      }, 1),
    [slip]
  );

  const toWin =
    mode === 'parlay'
      ? stake * (parlayMultiplier - 1)
      : slip.reduce((s, b) => s + (calcPayout(b.odds, stake) - stake), 0);

  const totalStake = mode === 'single' ? stake * slip.length : stake;

  return (
    <div className="card" style={{ padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div className="section-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Layers size={14} /> Bet Slip
          {slip.length > 0 && <span className="badge badge-ai">{slip.length}</span>}
        </div>
        {slip.length > 0 && (
          <button type="button" className="btn-ghost" style={{ fontSize: 11.5, color: 'var(--text-3)' }} onClick={() => setSlip([])}>
            Clear
          </button>
        )}
      </div>

      {slip.length > 0 && (
        <div style={{ display: 'flex', gap: 4, marginBottom: 12, padding: 3, background: 'var(--bg-elev)', borderRadius: 8 }}>
          <button
            type="button"
            onClick={() => setMode('single')}
            className="btn-sm"
            style={{
              flex: 1,
              padding: '6px 10px',
              borderRadius: 6,
              background: mode === 'single' ? 'var(--surface-2)' : 'transparent',
              color: mode === 'single' ? 'var(--text)' : 'var(--text-3)',
            }}
          >
            Single
          </button>
          <button
            type="button"
            onClick={() => setMode('parlay')}
            className="btn-sm"
            style={{
              flex: 1,
              padding: '6px 10px',
              borderRadius: 6,
              background: mode === 'parlay' ? 'var(--surface-2)' : 'transparent',
              color: mode === 'parlay' ? 'var(--text)' : 'var(--text-3)',
            }}
          >
            Parlay
            {slip.length >= 2 && (
              <span className="mono" style={{ fontSize: 10.5, marginLeft: 4, color: 'var(--accent)' }}>
                +{((parlayMultiplier - 1) * 100).toFixed(0)}
              </span>
            )}
          </button>
        </div>
      )}

      {slip.length === 0 ? (
        <div className="slip-empty">
          <div
            style={{
              width: 44,
              height: 44,
              margin: '0 auto 10px',
              borderRadius: 12,
              background: 'var(--bg-elev)',
              border: '1px solid var(--border)',
              display: 'grid',
              placeItems: 'center',
              color: 'var(--text-4)',
            }}
          >
            <Layers size={18} />
          </div>
          <div>No bets selected</div>
          <div className="dim" style={{ marginTop: 4, fontSize: 11.5 }}>
            Tap any odds to add a leg
          </div>
        </div>
      ) : (
        <>
          <div className="slip" style={{ marginBottom: 14 }}>
            {slip.map((b, i) => (
              <div key={b.id} className="slip-item">
                <div className="slip-item-head">
                  <div>
                    <div className="slip-item-team">{b.label}</div>
                    <div className="slip-item-meta">{b.matchup}</div>
                  </div>
                  <button type="button" onClick={() => setSlip(slip.filter((_, j) => j !== i))} style={{ color: 'var(--text-3)', padding: 4 }}>
                    <X size={14} />
                  </button>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className="slip-item-odds">{fmtOdds(b.odds)}</span>
                  {mode === 'single' && (
                    <span className="dim mono" style={{ fontSize: 11.5 }}>
                      → {fmtMoney(calcPayout(b.odds, stake) - stake, { signed: true })}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 11.5, color: 'var(--text-3)' }}>Stake</span>
                <div style={{ display: 'flex', gap: 4 }}>
                  {[25, 50, 100].map((v) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setStake(v)}
                      className="btn-sm"
                      style={{
                        padding: '3px 8px',
                        borderRadius: 5,
                        background: stake === v ? 'var(--surface-2)' : 'var(--bg-elev)',
                        border: '1px solid var(--border)',
                        fontSize: 11,
                        color: 'var(--text-2)',
                      }}
                    >
                      ${v}
                    </button>
                  ))}
                </div>
              </div>
              <div style={{ position: 'relative' }}>
                <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>
                  $
                </span>
                <input
                  className="input mono"
                  style={{ paddingLeft: 22 }}
                  value={stake}
                  onChange={(e) => setStake(Number(e.target.value) || 0)}
                />
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '10px 0', borderTop: '1px solid var(--border)' }}>
              <SlipRow label="Total stake" value={fmtMoney(totalStake)} />
              <SlipRow label="To win" value={fmtMoney(toWin)} highlight />
            </div>

            <button type="button" className="btn btn-primary btn-block" style={{ padding: '12px' }} onClick={onPlace} disabled={placing}>
              {placing ? 'Placing…' : `Place ${mode === 'parlay' ? 'parlay' : `${slip.length} bet${slip.length > 1 ? 's' : ''}`}`}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export function AccountMini({
  bankroll,
  openExposure,
  todayPnl,
}: {
  bankroll?: number;
  openExposure?: number;
  todayPnl?: number;
}) {
  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="section-title" style={{ fontSize: 13, marginBottom: 10 }}>
        Account
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12.5 }}>
        <SlipRow label="Bankroll" value={bankroll != null ? fmtMoney(bankroll) : '—'} />
        <SlipRow label="Open exposure" value={openExposure != null ? fmtMoney(openExposure) : '—'} />
        <SlipRow label="Today's P&L" value={todayPnl != null ? fmtMoney(todayPnl, { signed: true }) : '—'} highlight />
      </div>
    </div>
  );
}
