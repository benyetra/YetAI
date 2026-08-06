import Link from 'next/link';
import { notFound } from 'next/navigation';
import { VaultLabelWithHelp } from '../../../../../components/vault/VaultHelp';
import { VaultPageHeader } from '../../../../../components/vault/VaultPageHeader';
import { StadiumMark } from '../../../../../components/vault/illustrations';
import {
  COLUMN_HELP,
  fetchVaultSnapshot,
  managerById,
  vaultNameFitClass,
  vaultPath,
} from '../../../../../lib/vault';

type Props = { params: Promise<{ slug: string; year: string }> };

export default async function SeasonDetailPage({ params }: Props) {
  const { slug, year } = await params;
  const seasonYear = Number(year);
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();
  const season = snap.seasons.find((s) => s.season === seasonYear);
  if (!season) notFound();

  const teamById = new Map(season.teams.map((t) => [t.id, t]));
  const inProgress = !season.champion && season.matchups.length === 0;

  const teamName = (id: number | null) => {
    if (id == null) return '—';
    return teamById.get(id)?.team_name ?? '—';
  };

  const weeks = new Map<number, typeof season.matchups>();
  for (const m of season.matchups) {
    const list = weeks.get(m.week) ?? [];
    list.push(m);
    weeks.set(m.week, list);
  }
  const weekNums = [...weeks.keys()].sort((a, b) => a - b);

  const blurb = (
    <>
      {inProgress ? (
        <>Season in progress</>
      ) : (
        <>
          Champion:{' '}
          {season.champion ? (
            <Link
              href={vaultPath(slug, `/managers/${season.champion.slug}`)}
              className={vaultNameFitClass(season.champion.display_name)}
              title={season.champion.display_name}
            >
              {season.champion.display_name}
            </Link>
          ) : (
            '—'
          )}
        </>
      )}
      {' · '}
      <Link href={vaultPath(slug, `/drafts/${season.season}`)}>Draft board</Link>
    </>
  );

  return (
    <>
      <VaultPageHeader
        kicker={<Link href={vaultPath(slug, '/seasons')}>Seasons</Link>}
        title={`${season.season} Season`}
        blurb={blurb}
        help="Standings, weekly scores, and a link to this year’s draft board."
        illustration={<StadiumMark className="vault-illust" />}
      />

      <section className="vault-section">
        <div className="vault-section-heading">
          <h2>Standings</h2>
          <p className="vault-muted">Final ranks when available, with schedule-neutral all-play and luck.</p>
        </div>
        {season.teams.length === 0 ? (
          <p className="vault-muted">No teams for this season yet.</p>
        ) : (
          <table className="vault-table vault-table-standings">
            <thead>
              <tr>
                <th className="vault-col-num">#</th>
                <th>Team</th>
                <th>Manager</th>
                <th className="vault-col-num">W-L</th>
                <th className="vault-col-num">
                  <VaultLabelWithHelp help={COLUMN_HELP.pf} helpLabel="About points for">
                    PF
                  </VaultLabelWithHelp>
                </th>
                <th className="vault-col-num">
                  <VaultLabelWithHelp help={COLUMN_HELP.all_play} helpLabel="About all-play">
                    All-play
                  </VaultLabelWithHelp>
                </th>
                <th className="vault-col-num">
                  <VaultLabelWithHelp help={COLUMN_HELP.luck} helpLabel="About luck">
                    Luck
                  </VaultLabelWithHelp>
                </th>
              </tr>
            </thead>
            <tbody>
              {season.teams.map((t) => {
                const manager = managerById(snap, t.manager_id);
                return (
                  <tr
                    key={t.id}
                    className={t.final_rank === 1 ? 'vault-rank-1' : undefined}
                  >
                    <td className="vault-num">{t.final_rank ?? '—'}</td>
                    <td>{t.team_name}</td>
                    <td>
                      {manager ? (
                        <Link
                          href={vaultPath(slug, `/managers/${manager.slug}`)}
                          className={vaultNameFitClass(manager.display_name)}
                          title={manager.display_name}
                        >
                          {manager.display_name}
                        </Link>
                      ) : (
                        '—'
                      )}
                    </td>
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
                      {t.luck_differential != null
                        ? t.luck_differential.toFixed(2)
                        : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="vault-section">
        <div className="vault-section-heading">
          <h2>Scoreboard</h2>
          <p className="vault-muted">Weekly matchups — playoff weeks are marked.</p>
        </div>
        {weekNums.length === 0 ? (
          <p className="vault-muted">No scored matchups yet.</p>
        ) : (
          weekNums.map((week) => {
            const rows = weeks.get(week) ?? [];
            const playoff = rows.some((m) => m.is_playoff);
            return (
              <div key={week} className="vault-week-block">
                <h3 className={`vault-week-heading${playoff ? ' is-playoff' : ''}`}>
                  Week {week}
                  {playoff ? <span>Playoffs</span> : null}
                </h3>
                <table className="vault-table">
                  <tbody>
                    {rows.map((m, i) => (
                      <tr key={`${week}-${i}`}>
                        <td>
                          {teamName(m.team_a_id)} vs {teamName(m.team_b_id)}
                        </td>
                        <td className="vault-num">
                          {m.team_a_score != null && m.team_b_score != null
                            ? `${m.team_a_score.toFixed(1)} – ${m.team_b_score.toFixed(1)}`
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })
        )}
      </section>
    </>
  );
}
