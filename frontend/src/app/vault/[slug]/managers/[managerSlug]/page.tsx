import Link from 'next/link';
import { notFound } from 'next/navigation';
import { VaultLabelWithHelp } from '../../../../../components/vault/VaultHelp';
import { ManagersMark, TrophyCup } from '../../../../../components/vault/illustrations';
import {
  COLUMN_HELP,
  RECORD_HELP,
  RECORD_LABELS,
  fetchVaultSnapshot,
  formatRecord,
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
          <h1 className="vault-display">{manager.display_name}</h1>
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
          <p className="vault-muted">Every year this manager fielded a team in the vault.</p>
        </div>
        <table className="vault-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>Team</th>
              <th>Record</th>
              <th>
                <VaultLabelWithHelp help={COLUMN_HELP.pf} helpLabel="About points for">
                  PF
                </VaultLabelWithHelp>
              </th>
              <th>
                <VaultLabelWithHelp help={COLUMN_HELP.all_play} helpLabel="About all-play">
                  All-play
                </VaultLabelWithHelp>
              </th>
              <th>
                <VaultLabelWithHelp help={COLUMN_HELP.luck} helpLabel="About luck">
                  Luck
                </VaultLabelWithHelp>
              </th>
              <th>Rank</th>
            </tr>
          </thead>
          <tbody>
            {[...seasons].reverse().map(({ season, team, champion }) => (
              <tr
                key={season}
                className={champion ? 'vault-manager-season-champion' : undefined}
              >
                <td className="vault-num">
                  <Link href={vaultPath(slug, `/seasons/${season}`)}>{season}</Link>
                  {champion ? (
                    <span className="vault-champion-season-badge">
                      <span className="vault-css-star" aria-hidden="true" />
                      Champion
                    </span>
                  ) : null}
                </td>
                <td>{team?.team_name ?? '—'}</td>
                <td className="vault-num">
                  {team?.wins}-{team?.losses}
                </td>
                <td className="vault-num">{team?.points_for?.toFixed(1) ?? '—'}</td>
                <td className="vault-num">
                  {team?.all_play_wins != null
                    ? `${team.all_play_wins}-${team.all_play_losses}`
                    : '—'}
                </td>
                <td className="vault-num">
                  {team?.luck_differential != null
                    ? team.luck_differential.toFixed(2)
                    : '—'}
                </td>
                <td className="vault-num">{team?.final_rank ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {heldRecords.length > 0 ? (
        <section className="vault-section">
          <div className="vault-section-heading">
            <h2>Record book</h2>
            <p className="vault-muted">League marks this manager currently holds.</p>
          </div>
          <table className="vault-table">
            <thead>
              <tr>
                <th>Record</th>
                <th>Value</th>
                <th>Season</th>
              </tr>
            </thead>
            <tbody>
              {heldRecords.map((r) => {
                const label = RECORD_LABELS[r.record_key] ?? r.record_key;
                return (
                  <tr key={`${r.record_key}-${r.season ?? 'all'}-${r.value}`}>
                    <td>
                      <VaultLabelWithHelp
                        help={RECORD_HELP[r.record_key]}
                        helpLabel={`About ${label}`}
                      >
                        {label}
                      </VaultLabelWithHelp>
                    </td>
                    <td className="vault-num">{formatRecord(r.value, r.record_key)}</td>
                    <td className="vault-num">{r.season ?? 'Career'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      ) : null}
    </>
  );
}
