import Link from 'next/link';
import { notFound } from 'next/navigation';
import { fetchVaultSnapshot, vaultPath } from '../../../../../lib/vault';

type Props = { params: Promise<{ slug: string; year: string }> };

export default async function SeasonDetailPage({ params }: Props) {
  const { slug, year } = await params;
  const seasonYear = Number(year);
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();
  const season = snap.seasons.find((s) => s.season === seasonYear);
  if (!season) notFound();

  const teamName = (id: number | null) =>
    season.teams.find((t) => t.id === id)?.team_name ?? '—';

  return (
    <>
      <section className="vault-section">
        <p className="vault-muted">
          <Link href={vaultPath(slug, '/seasons')}>Seasons</Link>
        </p>
        <h1 className="vault-display">{season.season} Season</h1>
        <p className="vault-muted">
          Champion: {season.champion?.display_name ?? '—'}
          {' · '}
          <Link href={vaultPath(slug, `/drafts/${season.season}`)}>Draft board</Link>
        </p>
      </section>

      <section className="vault-section">
        <h2>Standings</h2>
        <table className="vault-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Team</th>
              <th>W-L</th>
              <th>PF</th>
              <th>All-play</th>
              <th>Luck</th>
            </tr>
          </thead>
          <tbody>
            {season.teams.map((t) => (
              <tr key={t.id}>
                <td className="vault-num">{t.final_rank ?? '—'}</td>
                <td>{t.team_name}</td>
                <td className="vault-num">
                  {t.wins}-{t.losses}
                </td>
                <td className="vault-num">{t.points_for?.toFixed(1)}</td>
                <td className="vault-num">
                  {t.all_play_wins != null
                    ? `${t.all_play_wins}-${t.all_play_losses}`
                    : '—'}
                </td>
                <td className="vault-num">
                  {t.luck_differential != null ? t.luck_differential.toFixed(2) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="vault-section">
        <h2>Scoreboard</h2>
        <table className="vault-table">
          <thead>
            <tr>
              <th>Wk</th>
              <th>Matchup</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {season.matchups.map((m, i) => (
              <tr key={`${m.week}-${i}`}>
                <td className="vault-num">
                  {m.week}
                  {m.is_playoff ? ' P' : ''}
                </td>
                <td>
                  {teamName(m.team_a_id)} vs {teamName(m.team_b_id)}
                </td>
                <td className="vault-num">
                  {m.team_a_score?.toFixed(1)} – {m.team_b_score?.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
