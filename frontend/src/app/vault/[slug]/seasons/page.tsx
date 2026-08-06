import Link from 'next/link';
import { notFound } from 'next/navigation';
import { fetchVaultSnapshot, isDraftPending, vaultPath } from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function SeasonsIndexPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  return (
    <>
      <section className="vault-section">
        <h1 className="vault-display">Seasons</h1>
      </section>
      <section className="vault-section">
        <table className="vault-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>Champion</th>
              <th>Teams</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {[...snap.seasons].reverse().map((s) => {
              const draft = s.drafts[0];
              const pending = isDraftPending(draft);
              const draftLabel =
                !draft || draft.picks.length === 0
                  ? 'Draft'
                  : pending
                    ? 'Order'
                    : 'Draft';
              return (
                <tr key={s.season}>
                  <th scope="row">
                    <Link href={vaultPath(slug, `/seasons/${s.season}`)}>{s.season}</Link>
                  </th>
                  <td>{s.champion?.display_name ?? '—'}</td>
                  <td className="vault-num">{s.team_count ?? s.teams.length}</td>
                  <td>
                    <Link href={vaultPath(slug, `/drafts/${s.season}`)}>{draftLabel}</Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </>
  );
}
