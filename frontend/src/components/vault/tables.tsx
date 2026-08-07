'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { VaultLabelWithHelp } from './VaultHelp';
import { Medal } from './illustrations';
import {
  VaultSortableTable,
  type VaultSortableColumn,
} from './VaultSortableTable';
import {
  COLUMN_HELP,
  vaultNameFitClass,
  vaultPath,
} from '../../lib/vault';

function ManagerNameLink({
  slug,
  managerSlug,
  name,
}: {
  slug: string;
  managerSlug: string;
  name: string;
}) {
  return (
    <Link
      href={vaultPath(slug, `/managers/${managerSlug}`)}
      className={vaultNameFitClass(name)}
      title={name}
    >
      {name}
    </Link>
  );
}

/* ---------- Managers roster ---------- */

export type ManagersRosterRow = {
  id: number;
  slug: string;
  displayName: string;
  seasonsLabel: string;
  firstSeason: number;
  wins: number;
  recordLabel: string;
  titles: number;
  highlight: boolean;
  epithet?: string | null;
};

export function ManagersRosterTable({
  slug,
  rows,
}: {
  slug: string;
  rows: ManagersRosterRow[];
}) {
  const columns: VaultSortableColumn<ManagersRosterRow>[] = [
    {
      key: 'manager',
      label: 'Manager',
      rowHeader: true,
      sortValue: (r) => r.displayName,
      cell: (r) => (
        <span className="vault-manager-cell">
          <ManagerNameLink slug={slug} managerSlug={r.slug} name={r.displayName} />
          {r.epithet ? <span className="vault-epithet-inline">“{r.epithet}”</span> : null}
        </span>
      ),
    },
    {
      key: 'seasons',
      label: 'Seasons',
      help: COLUMN_HELP.seasons_span,
      helpLabel: 'About seasons column',
      sortValue: (r) => r.firstSeason,
      cell: (r) => r.seasonsLabel,
      cellClassName: 'vault-muted',
    },
    {
      key: 'record',
      label: 'Record',
      help: COLUMN_HELP.record,
      helpLabel: 'About record column',
      sortValue: (r) => r.wins,
      cell: (r) => r.recordLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'titles',
      label: 'Titles',
      help: COLUMN_HELP.titles,
      helpLabel: 'About titles column',
      sortValue: (r) => r.titles,
      cell: (r) =>
        r.titles > 0 ? (
          <span className="vault-title-count">
            <Medal className="vault-illust vault-title-count-medal" rank={1} />
            {r.titles}
          </span>
        ) : (
          r.titles
        ),
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
  ];

  return (
    <VaultSortableTable
      rows={rows}
      columns={columns}
      rowKey={(r) => r.id}
      initialSort={{ key: 'titles', dir: 'desc' }}
      rowClassName={(r) => (r.highlight ? 'vault-rank-1' : undefined)}
    />
  );
}

/* ---------- Seasons index ---------- */

export type SeasonsIndexRow = {
  season: number;
  championName: string;
  teams: number;
  draftLabel: string;
};

export function SeasonsIndexTable({
  slug,
  rows,
}: {
  slug: string;
  rows: SeasonsIndexRow[];
}) {
  const columns: VaultSortableColumn<SeasonsIndexRow>[] = [
    {
      key: 'year',
      label: 'Year',
      rowHeader: true,
      sortValue: (r) => r.season,
      cell: (r) => <Link href={vaultPath(slug, `/seasons/${r.season}`)}>{r.season}</Link>,
      headerClassName: 'vault-col-num',
    },
    {
      key: 'champion',
      label: 'Champion',
      sortValue: (r) => r.championName || '',
      cell: (r) =>
        r.championName ? (
          <span className={vaultNameFitClass(r.championName)} title={r.championName}>
            {r.championName}
          </span>
        ) : (
          '—'
        ),
    },
    {
      key: 'teams',
      label: 'Teams',
      help: 'Number of teams that competed in the season.',
      helpLabel: 'About teams column',
      sortValue: (r) => r.teams,
      cell: (r) => r.teams,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'draft',
      label: 'Draft',
      help: 'Jump to the draft board or published draft order for that year.',
      helpLabel: 'About draft links',
      sortValue: (r) => r.draftLabel,
      cell: (r) => <Link href={vaultPath(slug, `/drafts/${r.season}`)}>{r.draftLabel}</Link>,
    },
  ];

  return (
    <VaultSortableTable
      rows={rows}
      columns={columns}
      rowKey={(r) => r.season}
      initialSort={{ key: 'year', dir: 'desc' }}
    />
  );
}

/* ---------- Titles ---------- */

export type TitlesRow = {
  id: number;
  slug: string;
  displayName: string;
  titles: number;
  titleLabel: string;
  rankClass?: string;
};

export function TitlesTable({ slug, rows }: { slug: string; rows: TitlesRow[] }) {
  const columns: VaultSortableColumn<TitlesRow>[] = [
    {
      key: 'manager',
      label: 'Manager',
      rowHeader: true,
      sortValue: (r) => r.displayName,
      cell: (r) => (
        <ManagerNameLink slug={slug} managerSlug={r.slug} name={r.displayName} />
      ),
    },
    {
      key: 'titles',
      label: 'Titles',
      sortValue: (r) => r.titles,
      cell: (r) => r.titles,
      cellClassName: 'vault-num',
    },
    {
      key: 'label',
      label: '',
      sortable: false,
      sortValue: () => '',
      cell: (r) => r.titleLabel,
      cellClassName: 'vault-muted',
    },
  ];

  return (
    <VaultSortableTable
      rows={rows}
      columns={columns}
      rowKey={(r) => r.id}
      initialSort={{ key: 'titles', dir: 'desc' }}
      rowClassName={(r) => r.rankClass}
    />
  );
}

/* ---------- Records ---------- */

export type RecordsBookRow = {
  key: string;
  label: string;
  help?: string;
  value: number;
  valueLabel: string;
  holderName: string;
  holderSlug: string | null;
  matchup?: {
    managerA: { slug: string; displayName: string };
    managerB: { slug: string; displayName: string };
  };
  detail: string;
  highlight: boolean;
};

export function RecordsBookTable({
  slug,
  rows,
}: {
  slug: string;
  rows: RecordsBookRow[];
}) {
  const columns: VaultSortableColumn<RecordsBookRow>[] = [
    {
      key: 'record',
      label: 'Record',
      rowHeader: true,
      headerClassName: 'vault-col-record',
      cellClassName: 'vault-col-record',
      sortValue: (r) => r.label,
      cell: (r) => (
        <VaultLabelWithHelp help={r.help} helpLabel={`About ${r.label}`}>
          {r.label}
        </VaultLabelWithHelp>
      ),
    },
    {
      key: 'value',
      label: 'Value',
      sortValue: (r) => r.value,
      cell: (r) => r.valueLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'holder',
      label: 'Holder',
      sortValue: (r) => r.holderName || r.detail,
      cell: (r) => (
        <>
          {r.matchup ? (
            <span className="vault-record-matchup">
              <ManagerNameLink
                slug={slug}
                managerSlug={r.matchup.managerA.slug}
                name={r.matchup.managerA.displayName}
              />
              <span className="vault-record-vs"> vs </span>
              <ManagerNameLink
                slug={slug}
                managerSlug={r.matchup.managerB.slug}
                name={r.matchup.managerB.displayName}
              />
            </span>
          ) : r.holderSlug ? (
            <ManagerNameLink slug={slug} managerSlug={r.holderSlug} name={r.holderName} />
          ) : (
            <span>{r.holderName || '—'}</span>
          )}
          {r.detail ? ` · ${r.detail}` : null}
        </>
      ),
      cellClassName: 'vault-muted',
    },
  ];

  return (
    <VaultSortableTable
      className="vault-table vault-table-records"
      rows={rows}
      columns={columns}
      rowKey={(r) => r.key}
      rowClassName={(r) => (r.highlight ? 'vault-record-highlight' : undefined)}
      initialSort={null}
    />
  );
}

/* ---------- Moves / transactions ---------- */

export type MovesSeasonRow = {
  season: number;
  count: number;
  breakdown: string;
  mostActive: string;
};

export function MovesSeasonTable({
  slug,
  rows,
}: {
  slug: string;
  rows: MovesSeasonRow[];
}) {
  const columns: VaultSortableColumn<MovesSeasonRow>[] = [
    {
      key: 'season',
      label: 'Season',
      rowHeader: true,
      sortValue: (r) => r.season,
      cell: (r) => <Link href={vaultPath(slug, `/seasons/${r.season}`)}>{r.season}</Link>,
    },
    {
      key: 'total',
      label: 'Total',
      help: COLUMN_HELP.moves_total,
      helpLabel: 'About total moves',
      sortValue: (r) => r.count,
      cell: (r) => r.count,
      cellClassName: 'vault-num',
    },
    {
      key: 'breakdown',
      label: 'Breakdown',
      help: COLUMN_HELP.moves_breakdown,
      helpLabel: 'About moves breakdown',
      sortValue: (r) => r.breakdown,
      cell: (r) => r.breakdown || '—',
      cellClassName: 'vault-muted',
    },
    {
      key: 'active',
      label: 'Most active',
      help: 'Teams with the highest move counts in that season.',
      helpLabel: 'About most active',
      sortValue: (r) => r.mostActive,
      cell: (r) => r.mostActive || '—',
      cellClassName: 'vault-muted',
    },
  ];

  return (
    <VaultSortableTable
      rows={rows}
      columns={columns}
      rowKey={(r) => r.season}
      initialSort={{ key: 'season', dir: 'desc' }}
    />
  );
}

export type MovesRecentRow = {
  key: string;
  week: number | null;
  typeLabel: string;
  teams: string;
};

export function MovesRecentTable({ rows }: { rows: MovesRecentRow[] }) {
  const columns: VaultSortableColumn<MovesRecentRow>[] = [
    {
      key: 'week',
      label: 'Week',
      sortValue: (r) => r.week ?? -1,
      cell: (r) => r.week ?? '—',
      cellClassName: 'vault-num',
    },
    {
      key: 'type',
      label: 'Type',
      sortValue: (r) => r.typeLabel,
      cell: (r) => r.typeLabel,
    },
    {
      key: 'teams',
      label: 'Teams',
      sortValue: (r) => r.teams,
      cell: (r) => r.teams || '—',
      cellClassName: 'vault-muted',
    },
  ];

  return (
    <VaultSortableTable
      rows={rows}
      columns={columns}
      rowKey={(r) => r.key}
      initialSort={{ key: 'week', dir: 'desc' }}
    />
  );
}

/* ---------- Draft ---------- */

export type DraftPickRow = {
  key: string;
  overall: number;
  round: number;
  teamName: string;
  managerName: string;
  managerSlug: string | null;
  playerLabel: string;
  firstOverall: boolean;
};

export function DraftBoardTable({
  slug,
  rows,
}: {
  slug: string;
  rows: DraftPickRow[];
}) {
  const columns: VaultSortableColumn<DraftPickRow>[] = [
    {
      key: 'overall',
      label: 'Overall',
      help: COLUMN_HELP.draft_overall,
      helpLabel: 'About overall pick',
      sortValue: (r) => r.overall,
      cell: (r) => r.overall,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'round',
      label: 'Rd',
      sortValue: (r) => r.round,
      cell: (r) => r.round,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'team',
      label: 'Team',
      sortValue: (r) => r.teamName,
      cell: (r) => r.teamName || '—',
    },
    {
      key: 'manager',
      label: 'Manager',
      sortValue: (r) => r.managerName,
      cell: (r) =>
        r.managerSlug ? (
          <ManagerNameLink slug={slug} managerSlug={r.managerSlug} name={r.managerName} />
        ) : (
          '—'
        ),
    },
    {
      key: 'player',
      label: 'Player',
      sortValue: (r) => r.playerLabel,
      cell: (r) => r.playerLabel,
    },
  ];

  return (
    <VaultSortableTable
      rows={rows}
      columns={columns}
      rowKey={(r) => r.key}
      initialSort={{ key: 'overall', dir: 'asc' }}
      rowClassName={(r) => (r.firstOverall ? 'vault-draft-first-overall' : undefined)}
    />
  );
}

/* ---------- Season standings / scoreboard ---------- */

export type StandingsRow = {
  id: number;
  rank: number | null;
  teamName: string;
  managerName: string;
  managerSlug: string | null;
  wins: number;
  losses: number;
  recordLabel: string;
  pf: number | null;
  pfLabel: string;
  allPlayWins: number | null;
  allPlayLabel: string;
  luck: number | null;
  luckLabel: string;
};

export function SeasonStandingsTable({
  slug,
  rows,
}: {
  slug: string;
  rows: StandingsRow[];
}) {
  const columns: VaultSortableColumn<StandingsRow>[] = [
    {
      key: 'rank',
      label: '#',
      sortValue: (r) => r.rank ?? 999,
      cell: (r) => r.rank ?? '—',
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'team',
      label: 'Team',
      sortValue: (r) => r.teamName,
      cell: (r) => r.teamName,
    },
    {
      key: 'manager',
      label: 'Manager',
      sortValue: (r) => r.managerName,
      cell: (r) =>
        r.managerSlug ? (
          <ManagerNameLink slug={slug} managerSlug={r.managerSlug} name={r.managerName} />
        ) : (
          '—'
        ),
    },
    {
      key: 'record',
      label: 'W-L',
      sortValue: (r) => r.wins * 1000 - r.losses,
      cell: (r) => r.recordLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'pf',
      label: 'PF',
      help: COLUMN_HELP.pf,
      helpLabel: 'About points for',
      sortValue: (r) => r.pf ?? -1,
      cell: (r) => r.pfLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'allplay',
      label: 'All-play',
      help: COLUMN_HELP.all_play,
      helpLabel: 'About all-play',
      sortValue: (r) => r.allPlayWins ?? -1,
      cell: (r) => r.allPlayLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'luck',
      label: 'Luck',
      help: COLUMN_HELP.luck,
      helpLabel: 'About luck',
      sortValue: (r) => r.luck ?? -999,
      cell: (r) => r.luckLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
  ];

  return (
    <VaultSortableTable
      className="vault-table vault-table-standings"
      rows={rows}
      columns={columns}
      rowKey={(r) => r.id}
      initialSort={{ key: 'rank', dir: 'asc' }}
      rowClassName={(r) => (r.rank === 1 ? 'vault-rank-1' : undefined)}
    />
  );
}

export type ScoreboardRow = {
  key: string;
  matchup: string;
  scoreSort: number;
  scoreLabel: string;
};

export function WeekScoreboardTable({ rows }: { rows: ScoreboardRow[] }) {
  const columns: VaultSortableColumn<ScoreboardRow>[] = [
    {
      key: 'matchup',
      label: 'Matchup',
      sortValue: (r) => r.matchup,
      cell: (r) => r.matchup,
    },
    {
      key: 'score',
      label: 'Score',
      sortValue: (r) => r.scoreSort,
      cell: (r) => r.scoreLabel,
      cellClassName: 'vault-num',
    },
  ];

  return (
    <VaultSortableTable
      rows={rows}
      columns={columns}
      rowKey={(r) => r.key}
      initialSort={null}
    />
  );
}

/* ---------- Manager detail ---------- */

export type ManagerSeasonRow = {
  season: number;
  teamName: string;
  wins: number;
  losses: number;
  recordLabel: string;
  pf: number | null;
  pfLabel: string;
  allPlayWins: number | null;
  allPlayLabel: string;
  luck: number | null;
  luckLabel: string;
  rank: number | null;
  champion: boolean;
};

export function ManagerSeasonsTable({
  slug,
  rows,
}: {
  slug: string;
  rows: ManagerSeasonRow[];
}) {
  const columns: VaultSortableColumn<ManagerSeasonRow>[] = [
    {
      key: 'year',
      label: 'Year',
      sortValue: (r) => r.season,
      cell: (r) => (
        <>
          <Link href={vaultPath(slug, `/seasons/${r.season}`)}>{r.season}</Link>
          {r.champion ? (
            <span className="vault-champion-season-badge">
              <span className="vault-css-star" aria-hidden="true" />
              Champion
            </span>
          ) : null}
        </>
      ),
    },
    {
      key: 'team',
      label: 'Team',
      sortValue: (r) => r.teamName,
      cell: (r) => r.teamName || '—',
    },
    {
      key: 'record',
      label: 'Record',
      sortValue: (r) => r.wins * 1000 - r.losses,
      cell: (r) => r.recordLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'pf',
      label: 'PF',
      help: COLUMN_HELP.pf,
      helpLabel: 'About points for',
      sortValue: (r) => r.pf ?? -1,
      cell: (r) => r.pfLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'allplay',
      label: 'All-play',
      help: COLUMN_HELP.all_play,
      helpLabel: 'About all-play',
      sortValue: (r) => r.allPlayWins ?? -1,
      cell: (r) => r.allPlayLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'luck',
      label: 'Luck',
      help: COLUMN_HELP.luck,
      helpLabel: 'About luck',
      sortValue: (r) => r.luck ?? -999,
      cell: (r) => r.luckLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'rank',
      label: 'Rank',
      sortValue: (r) => r.rank ?? 999,
      cell: (r) => r.rank ?? '—',
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
  ];

  return (
    <VaultSortableTable
      className="vault-table vault-table-seasons"
      rows={rows}
      columns={columns}
      rowKey={(r) => r.season}
      initialSort={{ key: 'year', dir: 'desc' }}
      rowClassName={(r) => (r.champion ? 'vault-manager-season-champion' : undefined)}
    />
  );
}

export type ManagerRecordRow = {
  key: string;
  label: string;
  help?: string;
  value: number;
  valueLabel: string;
  seasonSort: number;
  seasonLabel: string;
};

export function ManagerRecordsTable({ rows }: { rows: ManagerRecordRow[] }) {
  const columns: VaultSortableColumn<ManagerRecordRow>[] = [
    {
      key: 'record',
      label: 'Record',
      sortValue: (r) => r.label,
      cell: (r) => (
        <VaultLabelWithHelp help={r.help} helpLabel={`About ${r.label}`}>
          {r.label}
        </VaultLabelWithHelp>
      ),
    },
    {
      key: 'value',
      label: 'Value',
      sortValue: (r) => r.value,
      cell: (r) => r.valueLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
    {
      key: 'season',
      label: 'Season',
      sortValue: (r) => r.seasonSort,
      cell: (r) => r.seasonLabel,
      headerClassName: 'vault-col-num',
      cellClassName: 'vault-num',
    },
  ];

  return (
    <VaultSortableTable
      className="vault-table vault-table-records"
      rows={rows}
      columns={columns}
      rowKey={(r) => r.key}
      initialSort={{ key: 'value', dir: 'desc' }}
    />
  );
}

/* ---------- H2H matrix ---------- */

export type H2HManager = {
  id: number;
  slug: string;
  displayName: string;
};

export type H2HCell = {
  text: string;
  isSelf: boolean;
  isWinning: boolean;
};

export function H2HMatrixTable({
  slug,
  managers,
  matrix,
}: {
  slug: string;
  managers: H2HManager[];
  matrix: Record<string, Record<string, H2HCell>>;
}) {
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  /** Stable roster numbers from the page key (alphabetical), independent of matrix sort. */
  const rosterNumber = useMemo(() => {
    const map = new Map<number, number>();
    managers.forEach((m, index) => map.set(m.id, index + 1));
    return map;
  }, [managers]);

  const ordered = useMemo(() => {
    const list = [...managers];
    list.sort((a, b) =>
      sortDir === 'asc'
        ? a.displayName.localeCompare(b.displayName)
        : b.displayName.localeCompare(a.displayName),
    );
    return list;
  }, [managers, sortDir]);

  return (
    <div className="vault-matrix">
      <table>
        <thead>
          <tr>
            <th scope="col" className="vault-matrix-corner vault-th-sortable is-sorted">
              <button
                type="button"
                className="vault-sort-btn"
                onClick={() => setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))}
                aria-sort={sortDir === 'asc' ? 'ascending' : 'descending'}
              >
                <span className="vault-sort-btn-label">Manager</span>
                <span className="vault-sort-glyph" aria-hidden="true">
                  {sortDir === 'asc' ? '▲' : '▼'}
                </span>
              </button>
            </th>
            {ordered.map((m) => {
              const num = rosterNumber.get(m.id) ?? 0;
              return (
                <th key={m.id} scope="col">
                  <Link
                    href={vaultPath(slug, `/managers/${m.slug}`)}
                    className="vault-h2h-col-head"
                    aria-label={`Column ${num}: ${m.displayName}`}
                    title={m.displayName}
                  >
                    <span className="vault-h2h-col-num">{num}</span>
                  </Link>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {ordered.map((row) => {
            const rowNum = rosterNumber.get(row.id) ?? 0;
            return (
              <tr key={row.id}>
                <th scope="row">
                  <span className="vault-h2h-row-label">
                    <span className="vault-h2h-row-num" aria-hidden="true">
                      {rowNum}
                    </span>
                    <ManagerNameLink
                      slug={slug}
                      managerSlug={row.slug}
                      name={row.displayName}
                    />
                  </span>
                </th>
                {ordered.map((col) => {
                  const result =
                    matrix[String(row.id)]?.[String(col.id)] ?? {
                      text: '0-0',
                      isSelf: row.id === col.id,
                      isWinning: false,
                    };
                  const colNum = rosterNumber.get(col.id) ?? 0;
                  const aria =
                    row.id === col.id
                      ? `${row.displayName} versus self`
                      : `${row.displayName} versus ${col.displayName}: ${result.text}`;
                  return (
                    <td
                      key={col.id}
                      aria-label={aria}
                      title={
                        row.id === col.id
                          ? undefined
                          : `vs ${col.displayName} (#${colNum})`
                      }
                      className={[
                        'vault-num',
                        result.isSelf ? 'vault-matrix-self' : '',
                        result.isWinning ? 'vault-matrix-win' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                    >
                      {result.text}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
