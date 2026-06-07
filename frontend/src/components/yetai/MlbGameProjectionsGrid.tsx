'use client';

import type { ReactNode } from 'react';
import { formatNumber, formatString } from '@/components/PredictionsTable';
import { formatGameProjectionTime } from '@/lib/gameProjectionSchedule';
import { teamAbbr } from '@/lib/yetai-format';
import type { GameProjectionsVariant } from '@/lib/gameProjectionsTypes';
import {
  displaySpreadMargin,
  displayTeamScores,
  projectedTotal as projectedTotalFromRow,
  spreadMarketEdge,
} from '@/lib/spreadTotalsProjectionDisplay';
import { teamColorStyle, teamPrimaryColor } from '@/lib/team-colors';
import { TeamGlyph } from './primitives';

type GameRow = Record<string, unknown>;

type Side = 'HOME' | 'AWAY';

type PickKind = 'ml' | 'spread' | 'total';

type PrimaryPick = {
  kind: PickKind;
  side?: Side;
  team: string;
  betLabel: string;
  detail?: string;
};

export type { GameProjectionsVariant } from '@/lib/gameProjectionsTypes';

export type GameProjectionSlipPick = {
  team: string;
  betType: string;
  matchup: string;
  odds?: number;
};

const VARIANT = {
  mlb: {
    spreadEdgeThreshold: 0.5,
    showMatchupSubtitle: true,
    emptySubtitle: 'TBD',
    primaryPickKind: 'ml' as PickKind,
    pickBetSuffix: 'ML',
    logoLeague: 'MLB',
    sportKey: 'baseball_mlb',
    scoreUnit: 'runs',
    edgeUnit: 'pt',
    marginUnit: 'run',
  },
  nba: {
    spreadEdgeThreshold: 2.0,
    showMatchupSubtitle: true,
    emptySubtitle: '',
    primaryPickKind: 'spread' as PickKind,
    pickBetSuffix: 'Spread / ML',
    logoLeague: 'NBA',
    sportKey: 'basketball_nba',
    scoreUnit: 'pts',
    edgeUnit: 'pt',
    marginUnit: 'pt',
  },
  wnba: {
    spreadEdgeThreshold: 2.0,
    showMatchupSubtitle: true,
    emptySubtitle: '',
    primaryPickKind: 'spread' as PickKind,
    pickBetSuffix: 'Spread / ML',
    logoLeague: 'WNBA',
    sportKey: 'basketball_wnba',
    scoreUnit: 'pts',
    edgeUnit: 'pt',
    marginUnit: 'pt',
  },
  nfl: {
    spreadEdgeThreshold: 3.0,
    showMatchupSubtitle: false,
    emptySubtitle: '',
    primaryPickKind: 'spread' as PickKind,
    pickBetSuffix: 'Spread / ML',
    logoLeague: 'NFL',
    sportKey: 'americanfootball_nfl',
    scoreUnit: 'pts',
    edgeUnit: 'pt',
    marginUnit: 'pt',
  },
  nhl: {
    spreadEdgeThreshold: 0.5,
    showMatchupSubtitle: false,
    emptySubtitle: '',
    primaryPickKind: 'total' as PickKind,
    pickBetSuffix: 'Total',
    logoLeague: 'NHL',
    sportKey: 'icehockey_nhl',
    scoreUnit: 'goals',
    edgeUnit: 'goal',
    marginUnit: 'goal',
  },
} as const;

function num(v: unknown): number | null {
  const n = typeof v === 'number' ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

function pctPoints(prob: number): string {
  return `${(prob * 100).toFixed(1)}`;
}

function formatModelConfidence(v: unknown): string {
  const n = num(v);
  if (n == null) return '—';
  const pctVal = n <= 1 ? n * 100 : n;
  return `${Math.round(pctVal)}%`;
}

function hasFinalScore(proj: GameRow): boolean {
  return proj.actual_home_score != null && proj.actual_away_score != null;
}

function spreadRecommendation(proj: GameRow, threshold: number): Side | null {
  const stored = formatString(proj.spread_recommendation);
  if (stored === 'HOME' || stored === 'AWAY') return stored;

  const runLine = num(proj.run_line);
  const marketSpread = num(proj.market_spread);
  if (runLine == null || marketSpread == null) return null;

  const impliedMarketMargin = -marketSpread;
  const edge = runLine - impliedMarketMargin;
  if (edge >= threshold) return 'HOME';
  if (edge <= -threshold) return 'AWAY';
  return null;
}

function teamForSide(proj: GameRow, side: Side): string {
  return side === 'HOME' ? formatString(proj.home_team) : formatString(proj.away_team);
}

function primaryPick(proj: GameRow, variant: GameProjectionsVariant): PrimaryPick | null {
  const cfg = VARIANT[variant];

  if (cfg.primaryPickKind === 'ml') {
    const mlRaw = formatString(proj.ml_recommendation);
    if (mlRaw !== 'HOME' && mlRaw !== 'AWAY') return null;
    const side = mlRaw;
    const odds =
      side === 'HOME' ? num(proj.market_home_ml) : num(proj.market_away_ml);
    return {
      kind: 'ml',
      side,
      team: teamForSide(proj, side),
      betLabel: cfg.pickBetSuffix,
      detail: odds != null ? fmtAmerican(odds) : undefined,
    };
  }

  if (cfg.primaryPickKind === 'total') {
    const totalRaw = formatString(proj.total_recommendation);
    if (totalRaw !== 'OVER' && totalRaw !== 'UNDER') return null;
    const line = num(proj.market_total);
    return {
      kind: 'total',
      team: totalRaw === 'OVER' ? 'Over' : 'Under',
      betLabel: line != null ? line.toFixed(1) : cfg.pickBetSuffix,
      detail: undefined,
    };
  }

  const spreadSide = spreadRecommendation(proj, cfg.spreadEdgeThreshold);
  if (!spreadSide) return null;
  const marketSpread = num(proj.market_spread);
  return {
    kind: 'spread',
    side: spreadSide,
    team: teamForSide(proj, spreadSide),
    betLabel: cfg.pickBetSuffix,
    detail:
      marketSpread != null ? formatSpreadLine(spreadSide, marketSpread) : undefined,
  };
}

function fmtAmerican(odds: number): string {
  return odds > 0 ? `+${Math.round(odds)}` : `${Math.round(odds)}`;
}

function formatSpreadLine(side: Side, marketSpreadHome: number): string {
  const line = side === 'HOME' ? marketSpreadHome : -marketSpreadHome;
  const sign = line > 0 ? '+' : '';
  return `${sign}${line.toFixed(1)}`;
}

function pickGrade(proj: GameRow, kind: PickKind): boolean | null {
  if (kind === 'ml') return typeof proj.ml_correct === 'boolean' ? proj.ml_correct : null;
  if (kind === 'total') return typeof proj.total_correct === 'boolean' ? proj.total_correct : null;
  return typeof proj.spread_correct === 'boolean' ? proj.spread_correct : null;
}

function verdictClass(valueRating: string, hasPick: boolean): string {
  if (valueRating === 'Strong') return 'proj-verdict v-strong';
  if (hasPick || valueRating === 'Lean') return 'proj-verdict v-lean';
  return 'proj-verdict v-none';
}

function verdictLabel(valueRating: string, hasPick: boolean): string {
  if (valueRating === 'Strong') return 'Strong value';
  if (hasPick || valueRating === 'Lean') return 'Model lean';
  return 'No edge';
}

export default function GameProjectionsGrid({
  rows,
  loading,
  isPastDate = false,
  variant = 'mlb',
  onAddToSlip,
}: {
  rows: GameRow[];
  loading?: boolean;
  isPastDate?: boolean;
  variant?: GameProjectionsVariant;
  onAddToSlip?: (pick: GameProjectionSlipPick) => void;
}) {
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
        <StatChip
          label="Strong value"
          value={String(strong)}
          sub={strong === 0 ? 'no high-edge plays' : `${strong} ${strong === 1 ? 'pick' : 'picks'} with edge`}
          muted={strong === 0}
        />
      </div>
      {rows.map((proj) => (
        <GameCard
          key={String(proj.game_id ?? proj.id)}
          proj={proj}
          showResults={isPastDate || hasFinalScore(proj)}
          variant={variant}
          onAddToSlip={onAddToSlip}
        />
      ))}
    </div>
  );
}

function StatChip({
  label,
  value,
  sub,
  muted,
}: {
  label: string;
  value: string;
  sub?: string;
  muted?: boolean;
}) {
  return (
    <div className="card" style={{ padding: 12, textAlign: 'center' }}>
      <div className="dim" style={{ fontSize: 10 }}>{label}</div>
      <div
        className="mono"
        style={{
          fontSize: 22,
          marginTop: 4,
          color: muted ? 'var(--text-3)' : undefined,
        }}
      >
        {value}
      </div>
      {sub ? <div className="dim" style={{ fontSize: 9, marginTop: 4 }}>{sub}</div> : null}
    </div>
  );
}

function GameCard({
  proj,
  showResults,
  variant,
  onAddToSlip,
}: {
  proj: GameRow;
  showResults: boolean;
  variant: GameProjectionsVariant;
  onAddToSlip?: (pick: GameProjectionSlipPick) => void;
}) {
  const cfg = VARIANT[variant];
  const away = formatString(proj.away_team);
  const home = formatString(proj.home_team);
  const awayAbbr = teamAbbr(away);
  const homeAbbr = teamAbbr(home);
  const awayWp = num(proj.away_win_prob) ?? 0;
  const homeWp = num(proj.home_win_prob) ?? 0;
  const homeFav = homeWp >= awayWp;
  const favName = homeFav ? home : away;
  const favAbbr = homeFav ? homeAbbr : awayAbbr;
  const valueRating = formatString(proj.value_rating);
  const isStrong = valueRating === 'Strong';
  const pick = primaryPick(proj, variant);
  const hasPick = pick != null;
  const scores = displayTeamScores(proj, variant);
  const awayRuns = scores.away;
  const homeRuns = scores.home;
  const marginInfo = displaySpreadMargin(proj, variant, homeAbbr, awayAbbr);
  const total = projectedTotalFromRow(proj);
  const spreadEdge = spreadMarketEdge(proj);
  const gameTimeLabel = formatGameProjectionTime(proj);

  return (
    <article className={`proj-card${isStrong ? ' is-strong' : ''}`}>
      <div className="proj-head">
        <div className="proj-head-title">
          <div>
            {away} <span className="proj-at">@</span> {home}
          </div>
          {gameTimeLabel ? (
            <div className="proj-head-time mono">{gameTimeLabel}</div>
          ) : null}
        </div>
        <span className={verdictClass(valueRating, hasPick)}>{verdictLabel(valueRating, hasPick)}</span>
      </div>

      {showResults && hasFinalScore(proj) ? <FinalScoreBanner proj={proj} /> : null}

      <div className="proj-matchup">
        <ProjTeamLine
          abbr={awayAbbr}
          name={away}
          role="Away"
          subtitle={formatString(proj.away_pitcher_name) || cfg.emptySubtitle}
          showSubtitle={cfg.showMatchupSubtitle}
          score={awayRuns}
          scoreUnit={cfg.scoreUnit}
          prob={awayWp}
          isFav={!homeFav}
          isPick={pick?.kind !== 'total' && pick?.side === 'AWAY'}
          logoLeague={cfg.logoLeague}
          sportKey={cfg.sportKey}
        />
        <ProjTeamLine
          abbr={homeAbbr}
          name={home}
          role="Home"
          subtitle={formatString(proj.home_pitcher_name) || cfg.emptySubtitle}
          showSubtitle={cfg.showMatchupSubtitle}
          score={homeRuns}
          scoreUnit={cfg.scoreUnit}
          prob={homeWp}
          isFav={homeFav}
          isPick={pick?.kind !== 'total' && pick?.side === 'HOME'}
          logoLeague={cfg.logoLeague}
          sportKey={cfg.sportKey}
        />
      </div>

      <div
        className="proj-bar"
        role="img"
        aria-label={`${awayAbbr} ${pctPoints(awayWp)}% vs ${homeAbbr} ${pctPoints(homeWp)}%`}
      >
        <div
          className="proj-bar-seg"
          style={{
            width: `${awayWp * 100}%`,
            background: teamPrimaryColor(away, {
              league: cfg.logoLeague,
              sportKey: cfg.sportKey,
              abbr: awayAbbr,
            }),
          }}
        />
        <div
          className="proj-bar-seg"
          style={{
            width: `${homeWp * 100}%`,
            background: teamPrimaryColor(home, {
              league: cfg.logoLeague,
              sportKey: cfg.sportKey,
              abbr: homeAbbr,
            }),
          }}
        />
      </div>

      <ModelPickModule
        pick={pick}
        pickProbPct={(pick?.side === 'HOME' ? homeWp : pick?.side === 'AWAY' ? awayWp : homeFav ? homeWp : awayWp) * 100}
        favTeam={{ name: favName, abbr: favAbbr }}
        logoLeague={cfg.logoLeague}
        sportKey={cfg.sportKey}
        projectedTotal={total}
        marketTotal={num(proj.market_total)}
        totalEdge={num(proj.edge_vs_market_total)}
        spreadMarginAbs={marginInfo.marginAbs}
        spreadEdge={spreadEdge}
        marketSpread={num(proj.market_spread)}
        edgeUnit={cfg.edgeUnit}
        marginUnit={cfg.marginUnit}
        scoreUnit={cfg.scoreUnit}
        showResults={showResults}
        grade={pick && showResults ? pickGrade(proj, pick.kind) : null}
        pickTeamColors={
          pick && pick.kind !== 'total'
            ? teamColorStyle(pick.team, {
                league: cfg.logoLeague,
                sportKey: cfg.sportKey,
              })
            : undefined
        }
        onAdd={
          pick && onAddToSlip
            ? () =>
                onAddToSlip({
                  team: pick.kind === 'total' ? `${pick.team} ${pick.betLabel}` : pick.team,
                  betType: pick.betLabel,
                  matchup: `${away} @ ${home}`,
                  odds:
                    pick.kind === 'ml' && pick.side
                      ? (pick.side === 'HOME'
                          ? num(proj.market_home_ml)
                          : num(proj.market_away_ml)) ?? undefined
                      : undefined,
                })
            : undefined
        }
      />

      <div className="proj-foot">
        <KVStat
          label="Proj total"
          value={total != null ? total.toFixed(1) : '—'}
          sub={
            showResults && proj.actual_total_runs != null
              ? `Actual ${formatNumber(proj.actual_total_runs, 0)}`
              : proj.market_total != null
                ? `Mkt ${formatNumber(proj.market_total, 1)}`
                : undefined
          }
        />
        <KVStat
          label={marginInfo.spreadHomeMargin != null ? 'Spread margin' : 'Proj margin'}
          value={
            marginInfo.marginAbs != null ? (
              <span className="proj-margin-value">
                <ProjTeamInline
                  name={favName}
                  abbr={favAbbr}
                  league={cfg.logoLeague}
                  sportKey={cfg.sportKey}
                  size={16}
                />
                <span className="mono">by {marginInfo.marginAbs.toFixed(1)}</span>
              </span>
            ) : (
              '—'
            )
          }
          valueClassName=""
          sub={
            showResults && hasFinalScore(proj)
              ? `Final ${formatNumber(proj.actual_away_score, 0)}–${formatNumber(proj.actual_home_score, 0)}`
              : marginInfo.spreadHomeMargin != null &&
                  marginInfo.totalsMargin != null &&
                  marginInfo.marginAbs != null &&
                  Math.abs(marginInfo.totalsMargin - marginInfo.marginAbs) >= 0.5
                ? `Pace split ${marginInfo.totalsMargin.toFixed(1)} ${cfg.marginUnit}`
                : scores.alignedWithSpread
                  ? 'From spread + total models'
                  : undefined
          }
        />
        <KVStat label="Model confidence" value={formatModelConfidence(proj.model_confidence)} />
      </div>
    </article>
  );
}

type TeamInlineProps = {
  name: string;
  abbr: string;
  league: string;
  sportKey: string;
  size?: number;
  className?: string;
};

function ProjTeamInline({
  name,
  abbr,
  league,
  sportKey,
  size = 18,
  className,
}: TeamInlineProps) {
  return (
    <span className={`proj-team-inline${className ? ` ${className}` : ''}`}>
      <TeamGlyph abbr={abbr} name={name} league={league} sportKey={sportKey} size={size} />
      <span className="proj-team-inline-name">{name}</span>
    </span>
  );
}

function ProjTeamLine({
  abbr,
  name,
  role,
  subtitle,
  showSubtitle,
  score,
  scoreUnit,
  prob,
  isFav,
  isPick,
  logoLeague,
  sportKey,
}: {
  abbr: string;
  name: string;
  role: string;
  subtitle: string;
  showSubtitle: boolean;
  score: number | null;
  scoreUnit: string;
  prob: number;
  isFav: boolean;
  isPick: boolean;
  logoLeague: string;
  sportKey: string;
}) {
  const meta =
    showSubtitle && subtitle ? (
      <>
        <span className="proj-role">{role}</span>
        <span className="proj-dot">·</span>
        <span className="mono">{subtitle}</span>
      </>
    ) : (
      <span className="proj-role">{role}</span>
    );

  return (
    <div
      className={`proj-team${isFav ? ' is-fav' : ''}${isPick ? ' is-pick' : ''}`}
      style={teamColorStyle(name, { league: logoLeague, sportKey, abbr })}
    >
      <TeamGlyph abbr={abbr} name={name} league={logoLeague} sportKey={sportKey} size={30} />
      <div className="proj-team-id">
        <div className="proj-team-name">
          {name}
          {isPick ? <span className="proj-tag-pick">PICK</span> : null}
        </div>
        <div className="proj-team-meta">{meta}</div>
      </div>
      <div className="proj-team-score">
        <span className="proj-team-runs mono">{score != null ? score.toFixed(1) : '—'}</span>
        <span className="proj-team-runs-lab">proj {scoreUnit}</span>
      </div>
      <div className="proj-team-prob">
        <span className={`proj-prob-val mono${isFav ? ' fav' : ''}`}>
          {pctPoints(prob)}
          <i>%</i>
        </span>
        <span className="proj-prob-lab">win prob</span>
      </div>
    </div>
  );
}

function ModelPickModule({
  pick,
  pickProbPct,
  favTeam,
  logoLeague,
  sportKey,
  projectedTotal,
  marketTotal,
  totalEdge,
  spreadMarginAbs,
  spreadEdge,
  marketSpread,
  edgeUnit,
  marginUnit,
  scoreUnit,
  showResults,
  grade,
  pickTeamColors,
  onAdd,
}: {
  pick: PrimaryPick | null;
  pickProbPct: number;
  favTeam: { name: string; abbr: string };
  logoLeague: string;
  sportKey: string;
  projectedTotal: number | null;
  marketTotal: number | null;
  totalEdge: number | null;
  spreadMarginAbs: number | null;
  spreadEdge: number | null;
  marketSpread: number | null;
  edgeUnit: string;
  marginUnit: string;
  scoreUnit: string;
  showResults: boolean;
  grade: boolean | null;
  pickTeamColors?: Record<string, string>;
  onAdd?: () => void;
}) {
  if (!pick) {
    return (
      <div className="proj-pick is-none">
        <div className="proj-pick-main">
          <span className="proj-pick-kicker">No play</span>
          <span className="proj-pick-bet dim">
            Model leans{' '}
            <ProjTeamInline
              name={favTeam.name}
              abbr={favTeam.abbr}
              league={logoLeague}
              sportKey={sportKey}
              size={16}
              className="proj-team-inline-emphasis"
            />
            , below betting threshold
          </span>
        </div>
      </div>
    );
  }

  const pickAbbr = teamAbbr(pick.team);
  const pickTeamInline = (
    <ProjTeamInline
      name={pick.team}
      abbr={pickAbbr}
      league={logoLeague}
      sportKey={sportKey}
      size={16}
      className="proj-team-inline-emphasis"
    />
  );
  const marketLine =
    pick.kind === 'spread' && pick.side && marketSpread != null
      ? formatSpreadLine(pick.side, marketSpread)
      : pick.detail;
  const whyCopy =
    pick.kind === 'total' ? (
      <>
        Model projects{' '}
        <b className="mono">{projectedTotal != null ? projectedTotal.toFixed(1) : '—'}</b> total {scoreUnit}
        {marketTotal != null && totalEdge != null ? (
          <>
            {' '}
            — a <b className="mono">{Math.abs(totalEdge).toFixed(1)}-{edgeUnit}</b> edge over the{' '}
            <b className="mono">{marketTotal.toFixed(1)}</b> market line.
          </>
        ) : (
          '.'
        )}
      </>
    ) : pick.kind === 'spread' ? (
      <>
        Spread model projects {pickTeamInline} by{' '}
        <b className="mono">
          {spreadMarginAbs != null ? spreadMarginAbs.toFixed(1) : '—'} {marginUnit}
        </b>{' '}
        (<b className="mono">{pickProbPct.toFixed(1)}%</b> win prob).
        {marketLine && spreadEdge != null ? (
          <>
            {' '}
            Market line <b className="mono">{marketLine}</b> —{' '}
            <b className="mono">{Math.abs(spreadEdge).toFixed(1)}-{edgeUnit}</b> edge vs our margin.
          </>
        ) : (
          '.'
        )}
      </>
    ) : (
      <>
        Model gives {pickTeamInline} a <b className="mono">{pickProbPct.toFixed(1)}%</b> win probability.
      </>
    );

  return (
    <div className="proj-pick" style={pickTeamColors}>
      <div className="proj-pick-main">
        <span className="proj-pick-kicker">Model pick</span>
        <span className="proj-pick-bet">
          {pick.kind === 'total' ? (
            <>
              {pick.team} <b>{pick.betLabel}</b>
            </>
          ) : (
            <>
              {pickTeamInline} <b>{pick.betLabel}</b>
            </>
          )}
          {marketLine ? (
            <span className="mono dim" style={{ marginLeft: 8, fontSize: 13 }}>
              Line {marketLine}
            </span>
          ) : null}
        </span>
        {showResults && grade != null ? (
          <span className={grade ? 'badge badge-win' : 'badge'} style={{ fontSize: 10 }}>
            {grade ? 'Hit' : 'Miss'}
          </span>
        ) : null}
      </div>
      <div className="proj-pick-why">{whyCopy}</div>
      <button
        type="button"
        className="proj-pick-add"
        onClick={onAdd}
        disabled={!onAdd}
        style={!onAdd ? { opacity: 0.55, cursor: 'not-allowed' } : undefined}
      >
        + Add to slip
      </button>
    </div>
  );
}

function KVStat({
  label,
  value,
  sub,
  valueClassName = 'mono',
}: {
  label: string;
  value: ReactNode;
  sub?: string;
  valueClassName?: string;
}) {
  return (
    <div>
      <div className="field-label" style={{ marginBottom: 3 }}>
        {label}
      </div>
      <div
        className={valueClassName}
        style={{ fontSize: 14, fontWeight: 500, color: 'var(--text)' }}
      >
        {value}
      </div>
      {sub ? (
        <div className="dim" style={{ fontSize: 9, marginTop: 2 }}>
          {sub}
        </div>
      ) : null}
    </div>
  );
}

function FinalScoreBanner({ proj }: { proj: GameRow }) {
  const away = formatNumber(proj.actual_away_score, 0);
  const home = formatNumber(proj.actual_home_score, 0);
  return (
    <div
      className="mono"
      style={{
        margin: '0 14px 8px',
        padding: '8px 12px',
        borderRadius: 'var(--radius-sm)',
        background: 'var(--surface-2)',
        fontSize: 13,
        textAlign: 'center',
      }}
    >
      Final: {away}–{home}
    </div>
  );
}

/** @deprecated Use GameProjectionsGrid — kept for MLB imports */
export function MlbGameProjectionsGrid(
  props: Parameters<typeof GameProjectionsGrid>[0],
) {
  return <GameProjectionsGrid {...props} variant="mlb" />;
}
