'use client';

import {
  formatNumber,
  formatString,
} from '@/components/PredictionsTable';
import {
  formatSignedEdge,
} from '@/lib/propProjectionDisplay';
import {
  asNumber,
  type DiscoveryGroupConfig,
} from '@/lib/propDiscovery';
import { Sparkles } from 'lucide-react';

export type DiscoverySection = DiscoveryGroupConfig & {
  rows: Array<Record<string, unknown>>;
};

function displayName(row: Record<string, unknown>, nameKey: string): string {
  const primary = row[nameKey];
  if (primary != null && String(primary).trim() !== '') return String(primary);
  return formatString(
    row.player_name ?? row.pitcher_name ?? row.batter_name ?? row.goalie_name
  );
}

function teamLabel(row: Record<string, unknown>): string {
  return formatString(row.team_name ?? row.team);
}

function opponentLabel(row: Record<string, unknown>): string {
  return formatString(row.opponent_team_name ?? row.opponent ?? row.opponent_name);
}

function pickLabel(row: Record<string, unknown>, pickKey?: string): string {
  if (pickKey) return formatString(row[pickKey]);
  return formatString(
    row.recommendation ?? row.yetai_pick ?? row.fanduel_over_under ?? row.betting_recommendation
  );
}

function DiscoveryRow({
  row,
  group,
}: {
  row: Record<string, unknown>;
  group: DiscoveryGroupConfig;
}) {
  const edgeKey = group.edgeKey ?? 'edge';
  const projectedKey = group.projectedKey;
  const lineKey = group.lineKey;
  const edge = group.mode === 'positive_edge' ? asNumber(row[edgeKey]) : null;
  const value =
    group.mode === 'projected_value' && group.valueKey
      ? asNumber(row[group.valueKey])
      : null;

  return (
    <li className="predictions-discovery-row">
      <div className="predictions-discovery-player">
        <span className="predictions-discovery-name">{displayName(row, group.nameKey)}</span>
        <span className="predictions-discovery-matchup dim">
          {teamLabel(row)}
          {opponentLabel(row) !== '—' ? ` vs ${opponentLabel(row)}` : ''}
        </span>
      </div>
      <div className="predictions-discovery-stats mono">
        {projectedKey ? (
          <span title="Projected">
            {formatNumber(row[projectedKey], 1)}
            {lineKey && asNumber(row[lineKey]) != null
              ? ` / ${formatNumber(row[lineKey], 1)}`
              : ''}
          </span>
        ) : null}
        {group.mode === 'positive_edge' ? (
          <span className="predictions-discovery-edge">{formatSignedEdge(edge)}</span>
        ) : (
          <span className="predictions-discovery-edge">
            {value != null ? `${formatNumber(value, 0)} H` : '—'}
          </span>
        )}
        <span className="predictions-discovery-pick">{pickLabel(row, group.pickKey)}</span>
      </div>
    </li>
  );
}

export default function BestEdgesDiscovery({
  sections,
  loading,
}: {
  sections: DiscoverySection[];
  loading?: boolean;
}) {
  if (loading) {
    return (
      <section className="card predictions-discovery" aria-busy="true">
        <header className="predictions-discovery-head">
          <Sparkles size={16} aria-hidden />
          <h2>Best edges</h2>
        </header>
        <p className="dim" style={{ margin: 0, fontSize: 13 }}>
          Loading…
        </p>
      </section>
    );
  }

  if (sections.length === 0) return null;

  return (
    <section className="card predictions-discovery" aria-label="Best edges for parlay discovery">
      <header className="predictions-discovery-head">
        <Sparkles size={16} aria-hidden />
        <div>
          <h2>Best edges</h2>
          <p className="dim predictions-discovery-sub">
            Top +edge (and hit) legs for quick parlay building
          </p>
        </div>
      </header>
      <div className="predictions-discovery-grid">
        {sections.map((section) => (
          <div key={section.responseKey} className="predictions-discovery-group">
            <h3>{section.title}</h3>
            <ol className="predictions-discovery-list">
              {section.rows.map((row, i) => (
                <DiscoveryRow
                  key={`${section.responseKey}-${String(row.id ?? i)}`}
                  row={row}
                  group={section}
                />
              ))}
            </ol>
          </div>
        ))}
      </div>
    </section>
  );
}
