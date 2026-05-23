'use client';

import { useMemo, useState } from 'react';
import { Plus, X } from 'lucide-react';
import {
  calculateParlay,
  calculateSingleBet,
  oddsToDecimal,
  type OddsFormat,
  type ParlayLeg,
} from '@/lib/bet-calculator';
import { fmtMoney } from '@/lib/yetai-format';

type Tab = 'single' | 'parlay';

const ODDS_FORMAT_LABELS: Record<OddsFormat, string> = {
  american: 'American',
  decimal: 'Decimal',
  fractional: 'Fractional',
};

function formatPct(n: number, decimals = 2): string {
  return `${(n * 100).toFixed(decimals)}%`;
}

function ResultRow({
  label,
  value,
  accent,
  isLast,
}: {
  label: string;
  value: string;
  accent?: string;
  isLast?: boolean;
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingBottom: isLast ? 0 : 12,
        marginBottom: isLast ? 0 : 12,
        borderBottom: isLast ? undefined : '1px solid var(--border)',
      }}
    >
      <span className="field-label" style={{ marginBottom: 0 }}>
        {label}
      </span>
      <span className="mono" style={{ fontSize: 17, fontWeight: 500, color: accent || 'var(--text)' }}>
        {value}
      </span>
    </div>
  );
}

export default function BetCalculatorPanel() {
  const [tab, setTab] = useState<Tab>('single');
  const [oddsFormat, setOddsFormat] = useState<OddsFormat>('american');
  const [stake, setStake] = useState('100');
  const [odds, setOdds] = useState('-110');
  const [parlayLegs, setParlayLegs] = useState<ParlayLeg[]>([{ odds: '-110' }, { odds: '-110' }, { odds: '+150' }]);

  const stakeAmount = parseFloat(stake);

  const singleResult = useMemo(() => {
    if (!odds.trim()) return null;
    return calculateSingleBet(stakeAmount, odds, oddsFormat);
  }, [stakeAmount, odds, oddsFormat]);

  const singleDecimal = useMemo(() => {
    if (!odds.trim()) return null;
    return oddsToDecimal(odds, oddsFormat);
  }, [odds, oddsFormat]);

  const parlayResult = useMemo(() => {
    return calculateParlay(stakeAmount, parlayLegs, oddsFormat);
  }, [stakeAmount, parlayLegs, oddsFormat]);

  const updateLeg = (index: number, value: string) => {
    setParlayLegs((legs) => legs.map((leg, i) => (i === index ? { odds: value } : leg)));
  };

  const removeLeg = (index: number) => {
    setParlayLegs((legs) => (legs.length <= 2 ? legs : legs.filter((_, i) => i !== index)));
  };

  return (
    <div data-screen-label="Bet Calculator">
      <div className="tabs" style={{ marginBottom: 18 }}>
        <button type="button" className={tab === 'single' ? 'active' : ''} onClick={() => setTab('single')}>
          Single bet
        </button>
        <button type="button" className={tab === 'parlay' ? 'active' : ''} onClick={() => setTab('parlay')}>
          Parlay
        </button>
      </div>

      <div className="bet-calc-grid">
        <div className="card">
          <div className="section-title" style={{ marginBottom: 14 }}>
            Inputs
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div>
              <label className="field-label" htmlFor="bet-calc-odds-format">
                Odds format
              </label>
              <select
                id="bet-calc-odds-format"
                className="select"
                value={oddsFormat}
                onChange={(e) => setOddsFormat(e.target.value as OddsFormat)}
                style={{ width: '100%' }}
              >
                {(Object.keys(ODDS_FORMAT_LABELS) as OddsFormat[]).map((key) => (
                  <option key={key} value={key}>
                    {ODDS_FORMAT_LABELS[key]}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="field-label" htmlFor="bet-calc-stake">
                Bet amount
              </label>
              <div style={{ position: 'relative' }}>
                <span
                  className="mono"
                  style={{
                    position: 'absolute',
                    left: 10,
                    top: '50%',
                    transform: 'translateY(-50%)',
                    color: 'var(--text-3)',
                  }}
                >
                  $
                </span>
                <input
                  id="bet-calc-stake"
                  className="input mono"
                  type="number"
                  min={0}
                  step="0.01"
                  style={{ paddingLeft: 22, width: '100%' }}
                  value={stake}
                  onChange={(e) => setStake(e.target.value)}
                />
              </div>
            </div>
            {tab === 'single' ? (
              <div>
                <label className="field-label" htmlFor="bet-calc-odds">
                  Odds
                </label>
                <input
                  id="bet-calc-odds"
                  className="input mono"
                  style={{ width: '100%' }}
                  value={odds}
                  onChange={(e) => setOdds(e.target.value)}
                  placeholder={oddsFormat === 'fractional' ? '5/2' : '-110'}
                />
              </div>
            ) : (
              <div>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: 6,
                  }}
                >
                  <span className="field-label" style={{ marginBottom: 0 }}>
                    Legs ({parlayLegs.length})
                  </span>
                  <button type="button" className="btn btn-sm" onClick={() => setParlayLegs((l) => [...l, { odds: '' }])}>
                    <Plus size={11} />
                    Add leg
                  </button>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {parlayLegs.map((leg, i) => (
                    <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <span className="dim mono" style={{ fontSize: 11, width: 28 }}>
                        #{i + 1}
                      </span>
                      <input
                        className="input mono"
                        style={{ flex: 1 }}
                        value={leg.odds}
                        onChange={(e) => updateLeg(i, e.target.value)}
                        placeholder={oddsFormat === 'fractional' ? '5/2' : '-110'}
                        aria-label={`Leg ${i + 1} odds`}
                      />
                      {parlayLegs.length > 2 ? (
                        <button
                          type="button"
                          className="btn-ghost"
                          onClick={() => removeLeg(i)}
                          style={{ padding: 4, color: 'var(--text-3)' }}
                          aria-label={`Remove leg ${i + 1}`}
                        >
                          <X size={12} />
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="section-title" style={{ marginBottom: 14 }}>
            Result
          </div>
          {tab === 'single' ? (
            <SingleResults result={singleResult} stakeAmount={stakeAmount} decimal={singleDecimal} />
          ) : (
            <ParlayResults result={parlayResult} />
          )}
        </div>
      </div>
    </div>
  );
}

function SingleResults({
  result,
  stakeAmount,
  decimal,
}: {
  result: ReturnType<typeof calculateSingleBet>;
  stakeAmount: number;
  decimal: number | null;
}) {
  if (!result || !Number.isFinite(stakeAmount) || stakeAmount <= 0) {
    return <p className="dim" style={{ fontSize: 13 }}>Enter a valid stake and odds to see results.</p>;
  }

  const profit = result.potentialPayout - stakeAmount;

  return (
    <>
      <ResultRow label="Potential payout" value={fmtMoney(result.potentialPayout)} />
      <ResultRow label="Potential profit" value={fmtMoney(profit, { signed: true })} accent="var(--win)" />
      <ResultRow label="Implied probability" value={formatPct(result.impliedProbability, 2)} />
      <ResultRow
        label="Decimal odds"
        value={decimal != null ? decimal.toFixed(3) : '—'}
        isLast
      />
    </>
  );
}

function ParlayResults({ result }: { result: ReturnType<typeof calculateParlay> }) {
  if (!result) {
    return <p className="dim" style={{ fontSize: 13 }}>Add at least two legs with valid odds to see parlay math.</p>;
  }

  return (
    <>
      <ResultRow
        label="Parlay odds (American)"
        value={result.combinedAmerican || '—'}
        accent="var(--text)"
      />
      <ResultRow label="Parlay odds (decimal)" value={result.combinedDecimal.toFixed(3)} />
      <ResultRow label="Potential payout" value={fmtMoney(result.potentialPayout)} />
      <ResultRow
        label="Potential profit"
        value={fmtMoney(result.profit, { signed: true })}
        accent="var(--win)"
        isLast
      />
    </>
  );
}
