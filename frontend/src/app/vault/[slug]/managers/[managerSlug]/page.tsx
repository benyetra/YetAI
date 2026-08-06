import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ManagersMark, TrophyCup } from '../../../../../components/vault/illustrations';
import {
  ManagerRecordsTable,
  ManagerSeasonsTable,
} from '../../../../../components/vault/tables';
import {
  RECORD_HELP,
  RECORD_LABELS,
  fetchVaultSnapshot,
  formatRecord,
  vaultNameFitClass,
  vaultPath,
} from '../../../../../lib/vault';

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

  const heldRecords = snap.records.filter((r) => r.manager_id === manager.id);
  const titleCount = career?.titles ?? 0;

  const seasonRows = [...seasons].reverse().map(({ season, team, champion }) => ({
    season,
    teamName: team?.team_name ?? '—',
    wins: team?.wins ?? 0,
    losses: team?.losses ?? 0,
    recordLabel: `${team?.wins}-${team?.losses}`,
    pf: team?.points_for ?? null,
    pfLabel: team?.points_for?.toFixed(1) ?? '—',
    allPlayWins: team?.all_play_wins ?? null,
    allPlayLabel:
      team?.all_play_wins != null
        ? `${team.all_play_wins}-${team.all_play_losses}`
        : '—',
    luck: team?.luck_differential ?? null,
    luckLabel:
      team?.luck_differential != null ? team.luck_differential.toFixed(2) : '—',
    rank: team?.final_rank ?? null,
    champion,
  }));

  const recordRows = heldRecords.map((r) => {
    const label = RECORD_LABELS[r.record_key] ?? r.record_key;
    return {
      key: `${r.record_key}-${r.season ?? 'all'}-${r.value}`,
      label,
      help: RECORD_HELP[r.record_key],
      value: r.value,
      valueLabel: formatRecord(r.value, r.record_key),
      seasonSort: r.season ?? 0,
      seasonLabel: r.season != null ? String(r.season) : 'Career',
    };
  });

  return (
    <>
      <section className="vault-section vault-manager-header">
        <div className="vault-manager-header-mark" aria-hidden="true">
          <ManagersMark className="vault-illust vault-manager-header-illust" />
        </div>
        <div>
          <p className="vault-muted">
            <Link href={vaultPath(slug, '/managers')}>Managers</Link>
          </p>
          <h1
            className={`vault-display ${vaultNameFitClass(manager.display_name)}`}
            title={manager.display_name}
          >
            {manager.display_name}
          </h1>
          <p className="vault-muted">
            {manager.first_season}–{manager.last_season}
            {career
              ? ` · ${career.wins}-${career.losses} · ${career.titles} title${
                  career.titles === 1 ? '' : 's'
                } · ${career.points_for.toFixed(0)} PF`
              : null}
          </p>
        </div>
        {titleCount > 0 ? (
          <div
            className="vault-manager-title-badge"
            aria-label={`${titleCount} championship titles`}
          >
            <TrophyCup className="vault-illust vault-manager-title-cup" />
            <span className="vault-num">{titleCount}</span>
          </div>
        ) : null}
      </section>
      <section className="vault-section">
        <div className="vault-section-heading">
          <h2>Season-by-season</h2>
          <p className="vault-muted">Every year this manager fielded a team — click a column to sort.</p>
        </div>
        <ManagerSeasonsTable slug={slug} rows={seasonRows} />
      </section>
      {recordRows.length > 0 ? (
        <section className="vault-section">
          <div className="vault-section-heading">
            <h2>Record book</h2>
            <p className="vault-muted">League marks this manager currently holds.</p>
          </div>
          <ManagerRecordsTable rows={recordRows} />
        </section>
      ) : null}
    </>
  );
}
