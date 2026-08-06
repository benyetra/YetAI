import { notFound } from 'next/navigation';
import { fetchVaultSnapshot } from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function TransactionsPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const rows = [...snap.seasons]
    .reverse()
    .map((s) => ({
      season: s.season,
      count: s.transaction_count,
      moves: s.teams
        .map((t) => ({ name: t.team_name, moves: t.moves ?? 0 }))
        .sort((a, b) => b.moves - a.moves)
        .slice(0, 3),
    }));

  return (
    <>
      <section className="vault-section">
        <h1 className="vault-display">Transactions</h1>
        <p className="vault-muted">
          Activity by season. Full trade ledger detail expands in a later pass.
        </p>
      </section>
      <section className="vault-section">
        <table className="vault-table">
          <thead>
            <tr>
              <th>Season</th>
              <th>Transactions</th>
              <th>Most active</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.season}>
                <th scope="row">{r.season}</th>
                <td className="vault-num">{r.count}</td>
                <td className="vault-muted">
                  {r.moves.map((m) => `${m.name} (${m.moves})`).join(' · ') || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
