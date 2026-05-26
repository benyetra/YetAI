'use client';

import { formatNumber, formatString } from '@/components/PredictionsTable';
import { teamAbbr } from '@/lib/yetai-format';
import { TeamGlyph } from './primitives';

type GameRow = Record<string, unknown>;

type Side = 'HOME' | 'AWAY';

type PickKind = 'ml' | 'spread' | 'total';

type ProjectionPick = {
  kind: PickKind;
  side: Side;
  team: string;
  label: string;
  detail?: string;
  edge?: string;
};

const MLB_SPREAD_EDGE_THRESHOLD = 0.5;

function pct(v: unknown): string {
  const n = typeof v === 'number' ? v : parseFloat(String(v));
  if (!Number.isFinite(n)) return '—';
  return `${(n * 100).toFixed(1)}%`;
}

function num(v: unknown): number | null {
  const n = typeof v === 'number' ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

function ratingClass(rating: unknown): string {
  const r = formatString(rating);
  if (r === 'Strong') return 'badge badge-win';
  if (r === 'Lean') return 'badge';
  return 'badge dim';
}

function teamForSide(proj: GameRow, side: Side): string {
  return side === 'HOME' ? formatString(proj.home_team) : formatString(proj.away_team);
}

function formatSpreadLine(side: Side, marketSpreadHome: number): string {
  const line = side === 'HOME' ? marketSpreadHome : -marketSpreadHome;
  const sign = line > 0 ? '+' : '';
  return `${sign}${line.toFixed(1)}`;
}

function formatEdgePct(edge: number | null): string | undefined {
  if (edge == null) return undefined;
  const sign = edge > 0 ? '+' : '';
  return `${sign}${(edge * 100).toFixed(1)}% edge`;
}

function spreadRecommendation(proj: GameRow): Side | null {
  const runLine = num(proj.run_line);
  const marketSpread = num(proj.market_spread);
  if (runLine == null || marketSpread == null) return null;

  const impliedMarketMargin = -marketSpread;
  const edge = runLine - impliedMarketMargin;
  if (edge >= MLB_SPREAD_EDGE_THRESHOLD) return 'HOME';
  if (edge <= -MLB_SPREAD_EDGE_THRESHOLD) return 'AWAY';
  return null;
}

function buildPicks(proj: GameRow): ProjectionPick[] {
  const picks: ProjectionPick[] = [];

  const mlRaw = formatString(proj.ml_recommendation);
  if (mlRaw === 'HOME' || mlRaw === 'AWAY') {
    const edgeMl = num(proj.edge_vs_market_ml);
    picks.push({
      kind: 'ml',
      side: mlRaw,
      team: teamForSide(proj, mlRaw),
      label: 'Moneyline',
      detail: proj.market_home_ml != null && mlRaw === 'HOME'
        ? fmtAmerican(proj.market_home_ml)
        : proj.market_away_ml != null && mlRaw === 'AWAY'
          ? fmtAmerican(proj.market_away_ml)
          : undefined,
      edge: formatEdgePct(edgeMl),
    });
  }

  const spreadSide = spreadRecommendation(proj);
  const marketSpread = num(proj.market_spread);
  if (spreadSide && marketSpread != null) {
    const runLine = num(proj.run_line);
    const edgeRuns =
      runLine != null ? runLine - -marketSpread : null;
    picks.push({
      kind: 'spread',
      side: spreadSide,
      team: teamForSide(proj, spreadSide),
      label: 'Spread',
      detail: formatSpreadLine(spreadSide, marketSpread),
      edge:
        edgeRuns != null
          ? `${edgeRuns > 0 ? '+' : ''}${edgeRuns.toFixed(1)} run edge`
          : undefined,
    });
  }

  const totalRaw = formatString(proj.total_recommendation);
  if (totalRaw === 'OVER' || totalRaw === 'UNDER') {
    const edgeTotal = num(proj.edge_vs_market_total);
    picks.push({
      kind: 'total',
      side: 'HOME',
      team: totalRaw,
      label: 'Total',
      detail: proj.market_total != null ? `Line ${formatNumber(proj.market_total, 1)}` : undefined,
      edge:
        edgeTotal != null
          ? `${edgeTotal > 0 ? '+' : ''}${edgeTotal.toFixed(1)} run edge`
          : undefined,
    });
  }

  return picks;
}

function fmtAmerican(odds: unknown): string | undefined {
  const n = num(odds);
  if (n == null) return undefined;
  return n > 0 ? `+${Math.round(n)}` : `${Math.round(n)}`;
}

function pickKindClass(kind: PickKind): string {
  if (kind === 'ml') return 'badge badge-ai';
  if (kind === 'spread') return 'badge';
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
  const picks = buildPicks(proj);
  const mlPick = picks.find((p) => p.kind === 'ml');
  const recommendedSides = new Set(picks.filter((p) => p.kind !== 'total').map((p) => p.side));
  const hasEdge = formatString(proj.value_rating) !== 'No Edge' && picks.length > 0;

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
        <div style={{ flex: 1, minWidth: 0 }}>
          <TeamMatchupRow
            away={away}
            home={home}
            awayPitcher={formatString(proj.away_pitcher_name) || 'TBD'}
            homePitcher={formatString(proj.home_pitcher_name) || 'TBD'}
            recommendedSides={recommendedSides}
            mlFavoredSide={
              mlPick?.side ??
              (homeWp > awayWp ? 'HOME' : awayWp > homeWp ? 'AWAY' : null)
            }
          />
        </div>
        <span className={ratingClass(proj.value_rating)}>{formatString(proj.value_rating) || 'No edge'}</span>
      </div>

      <ProjectionPicksSection picks={picks} hasEdge={hasEdge} valueRating={formatString(proj.value_rating)} />

      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }} className="dim">
          <span style={{ color: recommendedSides.has('AWAY') ? 'var(--text)' : undefined, fontWeight: recommendedSides.has('AWAY') ? 600 : undefined }}>
            {pct(awayWp)}
          </span>
          <span>Win prob</span>
          <span style={{ color: recommendedSides.has('HOME') ? 'var(--text)' : undefined, fontWeight: recommendedSides.has('HOME') ? 600 : undefined }}>
            {pct(homeWp)}
          </span>
        </div>
        <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', marginTop: 4, background: 'var(--surface-3)' }}>
          <div
            style={{
              width: `${awayWp * 100}%`,
              background: recommendedSides.has('AWAY') ? 'var(--win)' : 'var(--loss)',
              boxShadow: recommendedSides.has('AWAY') ? 'inset 0 0 0 1px color-mix(in oklab, white 25%, transparent)' : undefined,
            }}
          />
          <div
            style={{
              width: `${homeWp * 100}%`,
              background: recommendedSides.has('HOME') ? 'var(--win)' : 'var(--accent)',
              boxShadow: recommendedSides.has('HOME') ? 'inset 0 0 0 1px color-mix(in oklab, white 25%, transparent)' : undefined,
            }}
          />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, textAlign: 'center' }}>
        <MiniStat label="Proj total" value={formatNumber(proj.projected_total, 1)} sub={proj.market_total ? `Mkt ${formatNumber(proj.market_total, 1)}` : undefined} />
        <MiniStat label="Proj score" value={`${formatNumber(proj.away_projected_runs, 1)}-${formatNumber(proj.home_projected_runs, 1)}`} sub={proj.run_line != null ? `Margin ${formatNumber(proj.run_line, 1)}` : undefined} />
        <MiniStat label="Confidence" value={proj.model_confidence ? pct(proj.model_confidence) : '—'} />
      </div>
    </article>
  );
}

function TeamMatchupRow({
  away,
  home,
  awayPitcher,
  homePitcher,
  recommendedSides,
  mlFavoredSide,
}: {
  away: string;
  home: string;
  awayPitcher: string;
  homePitcher: string;
  recommendedSides: Set<Side>;
  mlFavoredSide: Side | null;
}) {
  return (
    <>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <TeamLine name={away} side="AWAY" isPick={recommendedSides.has('AWAY')} isFavored={mlFavoredSide === 'AWAY'} />
        <div className="dim" style={{ fontSize: 11, paddingLeft: 34 }}>@</div>
        <TeamLine name={home} side="HOME" isPick={recommendedSides.has('HOME')} isFavored={mlFavoredSide === 'HOME'} />
      </div>
      <p className="dim" style={{ fontSize: 11, marginTop: 8 }}>
        {awayPitcher} vs {homePitcher}
      </p>
    </>
  );
}

function TeamLine({
  name,
  side,
  isPick,
  isFavored,
}: {
  name: string;
  side: Side;
  isPick: boolean;
  isFavored: boolean;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '4px 8px',
        marginLeft: -8,
        borderRadius: 'var(--radius-sm)',
        background: isPick ? 'var(--win-soft)' : undefined,
        border: isPick ? '1px solid color-mix(in oklab, var(--win) 35%, transparent)' : '1px solid transparent',
      }}
    >
      <TeamGlyph abbr={teamAbbr(name)} />
      <span className="type-section-title" style={{ margin: 0, fontSize: 15, flex: 1 }}>
        {name}
      </span>
      {isPick ? (
        <span className="badge badge-win" style={{ fontSize: 9, letterSpacing: '0.06em' }}>
          PICK
        </span>
      ) : isFavored ? (
        <span className="dim" style={{ fontSize: 10 }}>favored</span>
      ) : null}
      <span className="dim" style={{ fontSize: 10, textTransform: 'uppercase' }}>{side === 'HOME' ? 'Home' : 'Away'}</span>
    </div>
  );
}

function ProjectionPicksSection({
  picks,
  hasEdge,
  valueRating,
}: {
  picks: ProjectionPick[];
  hasEdge: boolean;
  valueRating: string;
}) {
  if (!picks.length) {
    return (
      <div
        className="dim"
        style={{
          marginBottom: 12,
          padding: '10px 12px',
          background: 'var(--surface-2)',
          borderRadius: 'var(--radius-sm)',
          fontSize: 12,
          textAlign: 'center',
        }}
      >
        No ML or spread play — model edge below threshold ({valueRating || 'No Edge'})
      </div>
    );
  }

  return (
    <div style={{ marginBottom: 12 }}>
      <div className="dim" style={{ fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
        Projection picks
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {picks.map((pick) => (
          <PickRow key={`${pick.kind}-${pick.team}-${pick.label}`} pick={pick} emphasized={hasEdge && pick.kind !== 'total'} />
        ))}
      </div>
    </div>
  );
}

function PickRow({ pick, emphasized }: { pick: ProjectionPick; emphasized: boolean }) {
  const isTotal = pick.kind === 'total';

  return (
    <div
      className="pick-call"
      style={{
        margin: 0,
        background: emphasized ? 'var(--accent-soft)' : 'var(--surface-2)',
        border: emphasized
          ? '1px solid color-mix(in oklab, var(--accent) 40%, var(--border))'
          : '1px solid var(--border)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
        {!isTotal ? <TeamGlyph abbr={teamAbbr(pick.team)} /> : null}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span className={pickKindClass(pick.kind)} style={{ fontSize: 10 }}>
              {pick.label}
            </span>
            <strong style={{ fontSize: 14, color: 'var(--text)' }}>
              {pick.team}
            </strong>
            {pick.detail ? (
              <span className="mono" style={{ fontSize: 13, color: 'var(--text-2)' }}>
                {pick.detail}
              </span>
            ) : null}
          </div>
          {pick.edge ? (
            <div className="dim" style={{ fontSize: 11, marginTop: 4 }}>
              {pick.edge}
            </div>
          ) : null}
        </div>
      </div>
    </div>
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
