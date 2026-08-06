import Link from 'next/link';
import { notFound } from 'next/navigation';
import { VaultLabelWithHelp } from '../../../../components/vault/VaultHelp';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { MovesMark } from '../../../../components/vault/illustrations';
import { COLUMN_HELP, PAGE_HELP, fetchVaultSnapshot, vaultPath } from '../../../../lib/vault';

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

  const rows = [...snap.seasons]
    .reverse()
    .map((s) => ({
      season: s.season,
      count: s.transaction_count,
      summary: s.transaction_summary ?? {},
      recent: s.transactions_recent ?? [],
      moves: s.teams
        .map((t) => ({ name: t.team_name, moves: t.moves ?? 0 }))
        .sort((a, b) => b.moves - a.moves)
        .slice(0, 3),
    }));

  const latestWithActivity = rows.find((r) => r.recent.length > 0);

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
        <table className="vault-table">
          <thead>
            <tr>
              <th>Season</th>
              <th>
                <VaultLabelWithHelp
                  help={COLUMN_HELP.moves_total}
                  helpLabel="About total moves"
                >
                  Total
                </VaultLabelWithHelp>
              </th>
              <th>
                <VaultLabelWithHelp
                  help={COLUMN_HELP.moves_breakdown}
                  helpLabel="About moves breakdown"
                >
                  Breakdown
                </VaultLabelWithHelp>
              </th>
              <th>
                <VaultLabelWithHelp
                  help="Teams with the highest move counts in that season."
                  helpLabel="About most active"
                >
                  Most active
                </VaultLabelWithHelp>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const breakdown = Object.entries(r.summary)
                .sort((a, b) => b[1] - a[1])
                .map(([k, n]) => `${TYPE_LABELS[k] ?? k} ${n}`)
                .join(' · ');
              return (
                <tr key={r.season}>
                  <th scope="row">
                    <Link href={vaultPath(slug, `/seasons/${r.season}`)}>{r.season}</Link>
                  </th>
                  <td className="vault-num">{r.count}</td>
                  <td className="vault-muted">{breakdown || '—'}</td>
                  <td className="vault-muted">
                    {r.moves.map((m) => `${m.name} (${m.moves})`).join(' · ') || '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      {latestWithActivity ? (
        <section className="vault-section">
          <div className="vault-section-heading">
            <h2>{latestWithActivity.season} recent</h2>
            <p className="vault-muted">Latest logged transactions from the most recent active season.</p>
          </div>
          <table className="vault-table">
            <thead>
              <tr>
                <th>Week</th>
                <th>Type</th>
                <th>Teams</th>
              </tr>
            </thead>
            <tbody>
              {latestWithActivity.recent.slice(0, 25).map((tx, i) => (
                <tr key={`${tx.week}-${tx.type}-${i}`}>
                  <td className="vault-num">{tx.week ?? '—'}</td>
                  <td>{TYPE_LABELS[tx.type ?? ''] ?? tx.type ?? '—'}</td>
                  <td className="vault-muted">
                    {tx.team_names.length ? tx.team_names.join(' · ') : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </>
  );
}
