import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Medal } from '../../../../components/vault/illustrations';
import { fetchVaultSnapshot, vaultPath } from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function ManagersPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const rows = [...snap.managers].sort((a, b) => {
    const careerA = snap.manager_careers[String(a.id)];
    const careerB = snap.manager_careers[String(b.id)];
    return (
      (careerB?.titles ?? 0) - (careerA?.titles ?? 0) ||
      (careerB?.wins ?? 0) - (careerA?.wins ?? 0) ||
      a.display_name.localeCompare(b.display_name)
    );
  });
  const topTitleCount = Math.max(
    0,
    ...rows.map((m) => snap.manager_careers[String(m.id)]?.titles ?? 0),
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
            {rows.map((m, index) => {
              const career = snap.manager_careers[String(m.id)];
              const titles = career?.titles ?? 0;
              const record = career
                ? `${career.wins}-${career.losses}${career.ties ? `-${career.ties}` : ''}`
                : '—';
              return (
                <tr
                  key={m.id}
                  className={index === 0 && topTitleCount > 0 ? 'vault-rank-1' : undefined}
                >
                  <th scope="row">
                    <Link href={vaultPath(slug, `/managers/${m.slug}`)}>
                      {m.display_name}
                    </Link>
                  </th>
                  <td className="vault-muted">
                    {m.first_season}–{m.last_season}
                  </td>
                  <td className="vault-num">{record}</td>
                  <td className="vault-num">
                    {titles > 0 ? (
                      <span className="vault-title-count">
                        <Medal className="vault-illust vault-title-count-medal" rank={1} />
                        {titles}
                      </span>
                    ) : (
                      titles
                    )}
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
