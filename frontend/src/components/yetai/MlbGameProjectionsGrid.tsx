'use client';

import { formatNumber, formatString } from '@/components/PredictionsTable';

type GameRow = Record<string, unknown>;

function pct(v: unknown): string {
  const n = typeof v === 'number' ? v : parseFloat(String(v));
  if (!Number.isFinite(n)) return '—';
  return `${(n * 100).toFixed(1)}%`;
}

function ratingClass(rating: unknown): string {
  const r = formatString(rating);
  if (r === 'Strong') return 'badge badge-win';
  if (r === 'Lean') return 'badge';
  return 'badge dim';
}

export default function MlbGameProjectionsGrid({ rows, loading }: { rows: GameRow[]; loading?: boolean }) {
  if (loading) {
    return (
      <section className="card" style={{ padding: 24, textAlign: 'center' }}>
        <p className="dim">Loading game projections…</p>
      </section>
    );
  }

  if (!rows.length) {
    return (
      <section className="card" style={{ padding: 24, textAlign: 'center' }}>
        <p className="dim">No game projections for this date.</p>
      </section>
    );
  }

  const strong = rows.filter((r) => formatString(r.value_rating) === 'Strong').length;

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
        <StatChip label="Games" value={String(rows.length)} />
        <StatChip label="Strong value" value={String(strong)} />
      </div>
      {rows.map((proj) => (
        <GameCard key={String(proj.game_id ?? proj.id)} proj={proj} />
      ))}
    </div>
  );
}

function StatChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="card" style={{ padding: 12, textAlign: 'center' }}>
      <div className="dim" style={{ fontSize: 10 }}>{label}</div>
      <div className="mono" style={{ fontSize: 22, marginTop: 4 }}>{value}</div>
    </div>
  );
}

function GameCard({ proj }: { proj: GameRow }) {
  const away = formatString(proj.away_team);
  const home = formatString(proj.home_team);
  const awayWp = typeof proj.away_win_prob === 'number' ? proj.away_win_prob : 0;
  const homeWp = typeof proj.home_win_prob === 'number' ? proj.home_win_prob : 0;

  return (
    <article
      className="card"
      style={{
        padding: 'var(--pad-card)',
        borderColor:
          formatString(proj.value_rating) === 'Strong'
            ? 'color-mix(in oklab, var(--win) 40%, var(--border))'
            : undefined,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: 12 }}>
        <div>
          <h3 className="type-section-title" style={{ margin: 0 }}>{away} @ {home}</h3>
          <p className="dim" style={{ fontSize: 11, marginTop: 4 }}>
            {formatString(proj.away_pitcher_name) || 'TBD'} vs {formatString(proj.home_pitcher_name) || 'TBD'}
          </p>
        </div>
        <span className={ratingClass(proj.value_rating)}>{formatString(proj.value_rating) || 'No edge'}</span>
      </div>

      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }} className="dim">
          <span>{pct(awayWp)}</span>
          <span>Win prob</span>
          <span>{pct(homeWp)}</span>
        </div>
        <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', marginTop: 4, background: 'var(--surface-3)' }}>
          <div style={{ width: `${awayWp * 100}%`, background: 'var(--loss)' }} />
          <div style={{ width: `${homeWp * 100}%`, background: 'var(--accent)' }} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, textAlign: 'center' }}>
        <MiniStat label="Proj total" value={formatNumber(proj.projected_total, 1)} sub={proj.market_total ? `Mkt ${formatNumber(proj.market_total, 1)}` : undefined} />
        <MiniStat label="Proj score" value={`${formatNumber(proj.away_projected_runs, 1)}-${formatNumber(proj.home_projected_runs, 1)}`} />
        <MiniStat label="Confidence" value={proj.model_confidence ? pct(proj.model_confidence) : '—'} />
      </div>

      {(proj.ml_recommendation || proj.total_recommendation) && (
        <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
          {proj.ml_recommendation && formatString(proj.ml_recommendation) !== 'NO_PLAY' ? (
            <span className="badge">ML: {formatString(proj.ml_recommendation)}</span>
          ) : null}
          {proj.total_recommendation && formatString(proj.total_recommendation) !== 'NO_PLAY' ? (
            <span className="badge">{formatString(proj.total_recommendation)}</span>
          ) : null}
        </div>
      )}
    </article>
  );
}

function MiniStat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ padding: 10, background: 'var(--surface-2)', borderRadius: 'var(--radius-sm)' }}>
      <div className="dim" style={{ fontSize: 9 }}>{label}</div>
      <div className="mono" style={{ fontSize: 14, marginTop: 2 }}>{value}</div>
      {sub ? <div className="dim" style={{ fontSize: 9, marginTop: 2 }}>{sub}</div> : null}
    </div>
  );
}
