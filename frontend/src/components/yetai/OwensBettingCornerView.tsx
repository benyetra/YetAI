'use client';

import { Clock } from 'lucide-react';
import { PredictionsError } from '@/components/PredictionsTable';
import AppLoading from '@/components/yetai/AppLoading';
import { EmptyState, StatTile } from '@/components/yetai/primitives';
import { useOwensBettingCorner, type OwensBet, type OwensSummary } from '@/lib/useOwensBettingCorner';

const HISTORICAL_PREVIEW = 12;

function resultBadgeClass(result: string): string {
  if (result === 'Win') return 'badge badge-win';
  if (result === 'Loss') return 'badge badge-loss';
  if (result === 'Push') return 'badge badge-flat';
  return 'badge badge-pending';
}

function formatUnitsDisplay(summary: OwensSummary): string {
  const raw = summary.implied_units_display.trim();
  if (/u$/i.test(raw)) return raw;
  return `${raw}u`;
}

function OwensBetsTable({
  rows,
  showResult,
}: {
  rows: OwensBet[];
  showResult?: boolean;
}) {
  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <table className="tbl">
        <thead>
          <tr>
            <th>Bet</th>
            <th className="num">Odds</th>
            <th>Date</th>
            {showResult ? <th className="num">Result</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((bet) => (
            <tr key={bet.id}>
              <td>{bet.name}</td>
              <td className="num dim">{bet.odds}</td>
              <td className="dim">{bet.date ?? '—'}</td>
              {showResult ? (
                <td className="num">
                  <span className={resultBadgeClass(bet.result)}>{bet.result}</span>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SummaryStats({ summary }: { summary: OwensSummary }) {
  return (
    <div className="stat-grid cols-5">
      <StatTile label="Total bets" value={summary.total_historical} deltaKind="neutral" />
      <StatTile label="Wins" value={summary.wins} deltaKind="neutral" />
      <StatTile label="Losses" value={summary.losses} deltaKind="neutral" />
      <StatTile label="Hit rate" value={`${summary.success_rate.toFixed(1)}%`} deltaKind="neutral" />
      <StatTile
        label="Units won"
        value={formatUnitsDisplay(summary)}
        delta="all-time"
        deltaKind="up"
      />
    </div>
  );
}

export default function OwensBettingCornerView() {
  const { pending, historical, summary, loading, error } = useOwensBettingCorner();
  const recent = historical.slice(0, HISTORICAL_PREVIEW);

  if (loading) {
    return <AppLoading />;
  }

  if (error) return <PredictionsError message={error} />;

  return (
    <div data-screen-label="Owen's Corner">
      {summary ? <SummaryStats summary={summary} /> : null}

      <div className="section-head">
        <div className="section-title">Pending bets (this week)</div>
      </div>
      {pending.length === 0 ? (
        <div className="card" style={{ marginBottom: 24 }}>
          <EmptyState
            icon={<Clock size={16} />}
            title="Nothing pending"
            body="Owen has no live picks out this week. Check back Saturday morning for the slate."
          />
        </div>
      ) : (
        <div style={{ marginBottom: 24 }}>
          <OwensBetsTable rows={pending} />
        </div>
      )}

      <div className="section-head">
        <div>
          <div className="section-title">Historical results</div>
          {recent.length > 0 ? (
            <div className="section-sub">
              Last {recent.length} picks · most recent first
            </div>
          ) : null}
        </div>
      </div>
      {recent.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={<Clock size={16} />}
            title="No history yet"
            body="Settled picks will show here once Owen's bets are graded."
          />
        </div>
      ) : (
        <OwensBetsTable rows={recent} showResult />
      )}
    </div>
  );
}
