import Link from 'next/link';
import { notFound } from 'next/navigation';
import {
  formatDraftPlayer,
  fetchVaultSnapshot,
  managerById,
  vaultPath,
} from '../../../../../lib/vault';

type Props = { params: Promise<{ slug: string; year: string }> };

export default async function DraftPage({ params }: Props) {
  const { slug, year } = await params;
  const seasonYear = Number(year);
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();
  const season = snap.seasons.find((s) => s.season === seasonYear);
  if (!season) notFound();
  const draft = season.drafts[0];
  const teamById = new Map(season.teams.map((t) => [t.id, t]));

  return (
    <>
      <section className="vault-section">
        <p className="vault-muted">
          <Link href={vaultPath(slug, `/seasons/${seasonYear}`)}>{seasonYear} season</Link>
        </p>
        <h1 className="vault-display">{seasonYear} Draft</h1>
        <p className="vault-muted">
          {draft?.draft_type ?? 'Draft'} · {draft?.picks.length ?? 0} picks
          {draft?.rounds != null ? ` · ${draft.rounds} rounds` : ''}
        </p>
      </section>
      <section className="vault-section">
        {!draft || draft.picks.length === 0 ? (
          <p className="vault-muted">No draft data for this season.</p>
        ) : (
          <table className="vault-table">
            <thead>
              <tr>
                <th>Overall</th>
                <th>Rd</th>
                <th>Team</th>
                <th>Manager</th>
                <th>Player</th>
              </tr>
            </thead>
            <tbody>
              {draft.picks.map((p) => {
                const team = p.team_id != null ? teamById.get(p.team_id) : undefined;
                const manager = team ? managerById(snap, team.manager_id) : undefined;
                const overall = p.draft_slot ?? p.pick_no;
                return (
                  <tr key={`${p.round}-${p.pick_no}-${overall}`}>
                    <td className="vault-num">{overall}</td>
                    <td className="vault-num">{p.round}</td>
                    <td>{team?.team_name ?? '—'}</td>
                    <td>
                      {manager ? (
                        <Link href={vaultPath(slug, `/managers/${manager.slug}`)}>
                          {manager.display_name}
                        </Link>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>{formatDraftPlayer(p)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
