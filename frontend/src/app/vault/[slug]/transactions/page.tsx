import { notFound } from 'next/navigation';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { MovesMark } from '../../../../components/vault/illustrations';
import { MovesRecentTable, MovesSeasonTable } from '../../../../components/vault/tables';
import { PAGE_HELP, fetchVaultSnapshot } from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

const TYPE_LABELS: Record<string, string> = {
  trade: 'Trades',
  free_agent: 'Free agents',
  waiver: 'Waivers',
  commissioner: 'Commissioner',
};

export default async function TransactionsPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const seasonRows = [...snap.seasons].reverse().map((s) => {
    const summary = s.transaction_summary ?? {};
    const moves = s.teams
      .map((t) => ({ name: t.team_name, moves: t.moves ?? 0 }))
      .sort((a, b) => b.moves - a.moves)
      .slice(0, 3);
    const breakdown = Object.entries(summary)
      .sort((a, b) => b[1] - a[1])
      .map(([k, n]) => `${TYPE_LABELS[k] ?? k} ${n}`)
      .join(' · ');
    return {
      season: s.season,
      count: s.transaction_count,
      breakdown,
      mostActive: moves.map((m) => `${m.name} (${m.moves})`).join(' · '),
      recent: s.transactions_recent ?? [],
    };
  });

  const latestWithActivity = seasonRows.find((r) => r.recent.length > 0);
  const recentRows =
    latestWithActivity?.recent.slice(0, 25).map((tx, i) => ({
      key: `${tx.week}-${tx.type}-${i}`,
      week: tx.week,
      typeLabel: TYPE_LABELS[tx.type ?? ''] ?? tx.type ?? '—',
      teams: tx.team_names.length ? tx.team_names.join(' · ') : '—',
    })) ?? [];

  return (
    <>
      <VaultPageHeader
        kicker="Roster churn"
        title="Moves"
        blurb="Waivers, free agents, and trades pulled from the league history."
        help={PAGE_HELP.moves}
        illustration={<MovesMark className="vault-illust" />}
      />
      <section className="vault-section">
        <MovesSeasonTable
          slug={slug}
          rows={seasonRows.map(({ season, count, breakdown, mostActive }) => ({
            season,
            count,
            breakdown,
            mostActive,
          }))}
        />
      </section>
      {latestWithActivity ? (
        <section className="vault-section">
          <div className="vault-section-heading">
            <h2>{latestWithActivity.season} recent</h2>
            <p className="vault-muted">
              Latest logged transactions from the most recent active season.
            </p>
          </div>
          <MovesRecentTable rows={recentRows} />
        </section>
      ) : null}
    </>
  );
}
