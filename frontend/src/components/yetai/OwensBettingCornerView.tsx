'use client';

import { PredictionsError } from '@/components/PredictionsTable';
import { useOwensBettingCorner, type OwensBet } from '@/lib/useOwensBettingCorner';

function BetTable({ title, rows, showResult }: { title: string; rows: OwensBet[]; showResult?: boolean }) {
  if (!rows.length) {
    return (
      <section className="card" style={{ padding: 20 }}>
        <h2 className="type-section-title" style={{ marginBottom: 8 }}>{title}</h2>
        <p className="dim" style={{ fontSize: 13 }}>Nothing to show right now.</p>
      </section>
    );
  }

  return (
    <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)' }}>
        <h2 className="type-section-title" style={{ margin: 0 }}>{title}</h2>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table className="data-table" style={{ width: '100%' }}>
          <thead>
            <tr>
              <th>Bet</th>
              <th>Odds</th>
              <th>Date</th>
              {showResult ? <th>Result</th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((bet) => (
              <tr key={bet.id}>
                <td>{bet.name}</td>
                <td className="mono">{bet.odds}</td>
                <td className="mono dim">{bet.date ?? '—'}</td>
                {showResult ? (
                  <td>
                    <span className={bet.result === 'Win' ? 'badge badge-win' : bet.result === 'Loss' ? 'badge' : 'badge dim'}>
                      {bet.result}
                    </span>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function OwensBettingCornerView() {
  const { pending, historical, summary, loading, error } = useOwensBettingCorner();

  if (loading) {
    return (
      <section className="card" style={{ padding: 32, textAlign: 'center' }}>
        <p className="dim">Loading Owen's picks…</p>
      </section>
    );
  }

  if (error) return <PredictionsError message={error} />;

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      {summary ? (
        <section className="card" style={{ padding: 'var(--pad-card)' }}>
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12, textAlign: 'center' }}>
              <SummaryStat label="Total bets" value={String(summary.total_historical)} />
              <SummaryStat label="Wins" value={String(summary.wins)} />
              <SummaryStat label="Losses" value={String(summary.losses)} />
              <SummaryStat label="Success rate" value={`${summary.success_rate}%`} />
              <SummaryStat label="Units won" value={summary.implied_units_display} highlight />
            </div>
          </div>
        </section>
      ) : null}
      <BetTable title="Pending bets (this week)" rows={pending} />
      <BetTable title="Historical results" rows={historical} showResult />
    </div>
  );
}

function SummaryStat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div>
      <div className="dim" style={{ fontSize: 10 }}>{label}</div>
      <div>
        <div className="mono" style={{ fontSize: highlight ? 22 : 18, marginTop: 4, color: highlight ? 'var(--gold)' : undefined }}>
          {value}
        </div>
      </div>
    </div>
  );
}
