import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ShareSeasonCard } from '../../../../../components/vault/ShareSeasonCard';
import { SeasonStoryBeats } from '../../../../../components/vault/VaultIntrigue';
import { VaultPageHeader } from '../../../../../components/vault/VaultPageHeader';
import { StadiumMark } from '../../../../../components/vault/illustrations';
import {
  SeasonStandingsTable,
  WeekScoreboardTable,
} from '../../../../../components/vault/tables';
import {
  fetchVaultSnapshot,
  managerById,
  vaultNameFitClass,
  vaultPath,
} from '../../../../../lib/vault';
import {
  buildSeasonBeats,
  buildShareSeasonCard,
} from '../../../../../lib/vault-intrigue';

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

  const standingsRows = season.teams.map((t) => {
    const manager = managerById(snap, t.manager_id);
    return {
      id: t.id,
      rank: t.final_rank,
      teamName: t.team_name ?? '—',
      managerName: manager?.display_name ?? '',
      managerSlug: manager?.slug ?? null,
      wins: t.wins ?? 0,
      losses: t.losses ?? 0,
      recordLabel: `${t.wins}-${t.losses}`,
      pf: t.points_for,
      pfLabel: t.points_for?.toFixed(1) ?? '—',
      allPlayWins: t.all_play_wins,
      allPlayLabel:
        t.all_play_wins != null ? `${t.all_play_wins}-${t.all_play_losses}` : '—',
      luck: t.luck_differential,
      luckLabel: t.luck_differential != null ? t.luck_differential.toFixed(2) : '—',
    };
  });

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

  const storyBeats = buildSeasonBeats(snap, season);
  const shareCard = buildShareSeasonCard(snap, season, slug);

  return (
    <>
      <VaultPageHeader
        kicker={<Link href={vaultPath(slug, '/seasons')}>Seasons</Link>}
        title={`${season.season} Season`}
        blurb={blurb}
        help="Standings, weekly scores, and a link to this year’s draft board."
        illustration={<StadiumMark className="vault-illust" />}
      />

      <SeasonStoryBeats beats={storyBeats} />
      {shareCard ? (
        <section className="vault-section vault-share-section">
          <div className="vault-section-heading">
            <h2>Share the season</h2>
            <p className="vault-muted">A postcard for the group chat.</p>
          </div>
          <ShareSeasonCard card={shareCard} />
        </section>
      ) : null}

      <section className="vault-section">
        <div className="vault-section-heading">
          <h2>Standings</h2>
          <p className="vault-muted">
            Final ranks when available — click any column to sort.
          </p>
        </div>
        {standingsRows.length === 0 ? (
          <p className="vault-muted">No teams for this season yet.</p>
        ) : (
          <SeasonStandingsTable slug={slug} rows={standingsRows} />
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
            const scoreRows = rows.map((m, i) => {
              const combined =
                m.team_a_score != null && m.team_b_score != null
                  ? m.team_a_score + m.team_b_score
                  : -1;
              return {
                key: `${week}-${i}`,
                matchup: `${teamName(m.team_a_id)} vs ${teamName(m.team_b_id)}`,
                scoreSort: combined,
                scoreLabel:
                  m.team_a_score != null && m.team_b_score != null
                    ? `${m.team_a_score.toFixed(1)} – ${m.team_b_score.toFixed(1)}`
                    : '—',
              };
            });
            return (
              <div key={week} className="vault-week-block">
                <h3 className={`vault-week-heading${playoff ? ' is-playoff' : ''}`}>
                  Week {week}
                  {playoff ? <span>Playoffs</span> : null}
                </h3>
                <WeekScoreboardTable rows={scoreRows} />
              </div>
            );
          })
        )}
      </section>
    </>
  );
}
