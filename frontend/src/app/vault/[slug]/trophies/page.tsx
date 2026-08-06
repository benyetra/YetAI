import Link from 'next/link';
import { notFound } from 'next/navigation';
import { fetchVaultSnapshot, managerById, vaultPath } from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function TrophiesPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const titleCounts = new Map<number, number>();
  for (const s of snap.seasons) {
    if (s.champion?.id != null) {
      titleCounts.set(s.champion.id, (titleCounts.get(s.champion.id) ?? 0) + 1);
    }
  }
  const leaderboard = [...titleCounts.entries()]
    .map(([id, n]) => ({ manager: managerById(snap, id), n }))
    .filter((x) => x.manager)
    .sort((a, b) => b.n - a.n);

  return (
    <>
      <section className="vault-section">
        <h1 className="vault-display">Trophy Room</h1>
        <p className="vault-muted">
          Champions, runners-up, and the {snap.last_place_label}.
        </p>
      </section>

      <section className="vault-section">
        <h2>By season</h2>
        <table className="vault-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>Champion</th>
              <th>Runner-up</th>
              <th>{snap.last_place_label}</th>
            </tr>
          </thead>
          <tbody>
            {[...snap.seasons].reverse().map((s) => (
              <tr key={s.season}>
                <td className="vault-num">{s.season}</td>
                <td>
                  {s.champion ? (
                    <Link href={vaultPath(slug, `/managers/${s.champion.slug}`)}>
                      {s.champion.display_name}
                    </Link>
                  ) : (
                    '—'
                  )}
                </td>
                <td>
                  {s.runner_up ? (
                    <Link href={vaultPath(slug, `/managers/${s.runner_up.slug}`)}>
                      {s.runner_up.display_name}
                    </Link>
                  ) : (
                    '—'
                  )}
                </td>
                <td>
                  {s.last_place ? (
                    <Link href={vaultPath(slug, `/managers/${s.last_place.slug}`)}>
                      {s.last_place.display_name}
                    </Link>
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="vault-section">
        <h2>Titles</h2>
        {leaderboard.length === 0 ? (
          <p className="vault-muted">No champions recorded yet.</p>
        ) : (
          <table className="vault-table">
            <tbody>
              {leaderboard.map(({ manager, n }) => (
                <tr key={manager!.id}>
                  <th scope="row">
                    <Link href={vaultPath(slug, `/managers/${manager!.slug}`)}>
                      {manager!.display_name}
                    </Link>
                  </th>
                  <td className="vault-num">{n}</td>
                  <td className="vault-muted">{n === 1 ? 'title' : 'titles'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
