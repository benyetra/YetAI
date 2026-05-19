'use client';

import { useMemo, useState, type ReactNode } from 'react';
import {
  calculateParlay,
  calculateSingleBet,
  type OddsFormat,
  type ParlayLeg,
} from '@/lib/bet-calculator';

type Tab = 'single' | 'parlay';

function formatMoney(n: number): string {
  return `$${n.toFixed(2)}`;
}

function formatPct(n: number): string {
  return `${(n * 100).toFixed(2)}%`;
}

export default function BetCalculatorPanel() {
  const [tab, setTab] = useState<Tab>('single');
  const [oddsFormat, setOddsFormat] = useState<OddsFormat>('american');
  const [betAmount, setBetAmount] = useState('100');
  const [odds, setOdds] = useState('-110');
  const [parlayAmount, setParlayAmount] = useState('25');
  const [parlayLegs, setParlayLegs] = useState<ParlayLeg[]>([{ odds: '-110' }, { odds: '+120' }]);

  const singleResult = useMemo(() => {
    const amount = parseFloat(betAmount);
    if (!odds.trim()) return null;
    return calculateSingleBet(amount, odds, oddsFormat);
  }, [betAmount, odds, oddsFormat]);

  const parlayResult = useMemo(() => {
    const amount = parseFloat(parlayAmount);
    return calculateParlay(amount, parlayLegs, oddsFormat);
  }, [parlayAmount, parlayLegs, oddsFormat]);

  return (
    <div>
      <div className="card" style={{ padding: 'var(--pad-card)' }}>
        <TabBar tab={tab} onTab={setTab} />
        <div style={{ marginTop: 20 }}>
          <label className="dim" style={{ fontSize: 11, display: 'block', marginBottom: 6 }}>
            Odds format
          </label>
          <select
            className="input"
            value={oddsFormat}
            onChange={(e) => setOddsFormat(e.target.value as OddsFormat)}
            style={{ maxWidth: 200 }}
          >
            <option value="american">American</option>
            <option value="decimal">Decimal</option>
            <option value="fractional">Fractional</option>
          </select>
        </div>
        {tab === 'single' ? (
          <SingleBetForm
            betAmount={betAmount}
            odds={odds}
            onBetAmount={setBetAmount}
            onOdds={setOdds}
            result={singleResult}
          />
        ) : (
          <ParlayForm
            parlayAmount={parlayAmount}
            parlayLegs={parlayLegs}
            oddsFormat={oddsFormat}
            onParlayAmount={setParlayAmount}
            onAddLeg={() => setParlayLegs((l) => [...l, { odds: '' }])}
            onRemoveLeg={(i) =>
              setParlayLegs((l) => (l.length <= 2 ? l : l.filter((_, idx) => idx !== i)))
            }
            onUpdateLeg={(i, v) => setParlayLegs((l) => l.map((leg, idx) => (idx === i ? { odds: v } : leg)))}
            result={parlayResult}
          />
        )}
      </div>
    </div>
  );
}

function TabBar({ tab, onTab }: { tab: Tab; onTab: (t: Tab) => void }) {
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      {(['single', 'parlay'] as const).map((t) => (
        <button
          key={t}
          type="button"
          className={`btn ${tab === t ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => onTab(t)}
        >
          {t === 'single' ? 'Single bet' : 'Parlay'}
        </button>
      ))}
    </div>
  );
}

function SingleBetForm({
  betAmount,
  odds,
  onBetAmount,
  onOdds,
  result,
}: {
  betAmount: string;
  odds: string;
  onBetAmount: (v: string) => void;
  onOdds: (v: string) => void;
  result: ReturnType<typeof calculateSingleBet>;
}) {
  return (
    <div style={{ display: 'grid', gap: 16, marginTop: 20 }}>
      <Field label="Bet amount" prefix="$">
        <input
          className="input mono"
          type="number"
          min={0}
          step="0.01"
          value={betAmount}
          onChange={(e) => onBetAmount(e.target.value)}
        />
      </Field>
      <Field label="Odds">
        <input className="input mono" value={odds} onChange={(e) => onOdds(e.target.value)} />
      </Field>
      <ResultGrid>
        <ResultBox label="Potential payout" value={result ? formatMoney(result.potentialPayout) : '—'} />
        <ResultBox label="Implied probability" value={result ? formatPct(result.impliedProbability) : '—'} />
      </ResultGrid>
    </div>
  );
}

function ParlayForm({
  parlayAmount,
  parlayLegs,
  oddsFormat,
  onParlayAmount,
  onAddLeg,
  onRemoveLeg,
  onUpdateLeg,
  result,
}: {
  parlayAmount: string;
  parlayLegs: ParlayLeg[];
  oddsFormat: OddsFormat;
  onParlayAmount: (v: string) => void;
  onAddLeg: () => void;
  onRemoveLeg: (i: number) => void;
  onUpdateLeg: (i: number, v: string) => void;
  result: ReturnType<typeof calculateParlay>;
}) {
  return (
    <div>
      <div style={{ display: 'grid', gap: 16, marginTop: 20 }}>
        <Field label="Bet amount" prefix="$">
          <input
            className="input mono"
            type="number"
            min={0}
            step="0.01"
            value={parlayAmount}
            onChange={(e) => onParlayAmount(e.target.value)}
          />
        </Field>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span className="dim" style={{ fontSize: 11 }}>
              Legs
            </span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={onAddLeg}>
              + Add leg
            </button>
          </div>
          <div style={{ display: 'grid', gap: 8 }}>
            {parlayLegs.map((leg, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span className="dim mono" style={{ fontSize: 11, width: 48 }}>
                  Leg {i + 1}
                </span>
                <input
                  className="input mono"
                  style={{ flex: 1 }}
                  value={leg.odds}
                  onChange={(e) => onUpdateLeg(i, e.target.value)}
                  placeholder={oddsFormat === 'fractional' ? '5/2' : '-110'}
                />
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => onRemoveLeg(i)}
                  disabled={parlayLegs.length <= 2}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        </div>
        <ResultGrid>
          <ResultBox
            label="Combined odds"
            value={result ? result.combinedAmerican || result.combinedDecimal.toFixed(2) : '—'}
          />
          <ResultBox label="Implied probability" value={result ? formatPct(result.impliedProbability) : '—'} />
          <ResultBox label="Potential payout" value={result ? formatMoney(result.potentialPayout) : '—'} />
          <ResultBox label="Profit" value={result ? formatMoney(result.profit) : '—'} />
        </ResultGrid>
      </div>
    </div>
  );
}

function Field({ label, prefix, children }: { label: string; prefix?: string; children: ReactNode }) {
  return (
    <label style={{ display: 'block' }}>
      <span className="dim" style={{ fontSize: 11, display: 'block', marginBottom: 6 }}>
        {label}
      </span>
      {prefix ? (
        <div style={{ display: 'flex' }}>
          <span
            className="mono dim"
            style={{
              padding: '10px 12px',
              background: 'var(--surface-2)',
              border: '1px solid var(--border)',
              borderRight: 0,
              borderRadius: 'var(--radius-sm) 0 0 var(--radius-sm)',
            }}
          >
            {prefix}
          </span>
          <div style={{ flex: 1 }}>{children}</div>
        </div>
      ) : (
        children
      )}
    </label>
  );
}

function ResultGrid({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>{children}</div>
  );
}

function ResultBox({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        padding: 14,
        background: 'var(--surface-2)',
        borderRadius: 'var(--radius-sm)',
        border: '1px solid var(--border)',
      }}
    >
      <div className="dim" style={{ fontSize: 10, marginBottom: 4 }}>
        {label}
      </div>
      <div>
        <div className="mono" style={{ fontSize: 18, fontWeight: 500 }}>
          {value}
        </div>
      </div>
    </div>
  );
}
