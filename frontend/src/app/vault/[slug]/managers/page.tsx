import Link from 'next/link';
import { notFound } from 'next/navigation';
import { fetchVaultSnapshot, vaultPath } from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function ManagersPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const rows = [...snap.managers].sort((a, b) =>
    a.display_name.localeCompare(b.display_name),
  );

  return (
    <>
      <section className="vault-section">
        <h1 className="vault-display">Managers</h1>
      </section>
      <section className="vault-section">
        <table className="vault-table">
          <thead>
            <tr>
              <th>Manager</th>
              <th>Seasons</th>
              <th>Record</th>
              <th>Titles</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const career = snap.manager_careers[String(m.id)];
              const record = career
                ? `${career.wins}-${career.losses}${career.ties ? `-${career.ties}` : ''}`
                : '—';
              return (
                <tr key={m.id}>
                  <th scope="row">
                    <Link href={vaultPath(slug, `/managers/${m.slug}`)}>
                      {m.display_name}
                    </Link>
                  </th>
                  <td className="vault-muted">
                    {m.first_season}–{m.last_season}
                  </td>
                  <td className="vault-num">{record}</td>
                  <td className="vault-num">{career?.titles ?? 0}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </>
  );
}
