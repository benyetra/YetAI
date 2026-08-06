import Link from 'next/link';
import { notFound } from 'next/navigation';
import { fetchVaultSnapshot, vaultPath } from '../../../../../lib/vault';

type Props = { params: Promise<{ slug: string; managerSlug: string }> };

export default async function ManagerDetailPage({ params }: Props) {
  const { slug, managerSlug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();
  const manager = snap.managers.find((m) => m.slug === managerSlug);
  if (!manager) notFound();

  const career = snap.manager_careers[String(manager.id)];
  const seasons = snap.seasons
    .map((s) => ({
      season: s.season,
      team: s.teams.find((t) => t.manager_id === manager.id),
      champion: s.champion?.id === manager.id,
    }))
    .filter((x) => x.team);

  return (
    <>
      <section className="vault-section">
        <p className="vault-muted">
          <Link href={vaultPath(slug, '/managers')}>Managers</Link>
        </p>
        <h1 className="vault-display">{manager.display_name}</h1>
        <p className="vault-muted">
          {manager.first_season}–{manager.last_season}
          {career
            ? ` · ${career.wins}-${career.losses} · ${career.titles} title${career.titles === 1 ? '' : 's'}`
            : null}
        </p>
      </section>
      <section className="vault-section">
        <h2>Season-by-season</h2>
        <table className="vault-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>Team</th>
              <th>Record</th>
              <th>PF</th>
              <th>Rank</th>
            </tr>
          </thead>
          <tbody>
            {[...seasons].reverse().map(({ season, team, champion }) => (
              <tr key={season}>
                <td className="vault-num">
                  <Link href={vaultPath(slug, `/seasons/${season}`)}>{season}</Link>
                  {champion ? ' ★' : ''}
                </td>
                <td>{team?.team_name ?? '—'}</td>
                <td className="vault-num">
                  {team?.wins}-{team?.losses}
                </td>
                <td className="vault-num">{team?.points_for?.toFixed(1) ?? '—'}</td>
                <td className="vault-num">{team?.final_rank ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
