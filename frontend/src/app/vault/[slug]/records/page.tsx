import Link from 'next/link';
import { notFound } from 'next/navigation';
import {
  RECORD_LABELS,
  fetchVaultSnapshot,
  formatRecord,
  managerById,
  vaultPath,
} from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function RecordsPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const featured = snap.records.filter(
    (r) =>
      r.scope !== 'career' &&
      r.record_key !== 'career_titles' &&
      r.record_key !== 'career_wins',
  );

  return (
    <>
      <section className="vault-section">
        <h1 className="vault-display">Record Book</h1>
        <p className="vault-muted">All-time marks — including all-play and luck.</p>
      </section>
      <section className="vault-section">
        {featured.length === 0 ? (
          <p className="vault-muted">Records will appear after the first compute pass.</p>
        ) : (
          <table className="vault-table">
            <tbody>
              {featured.map((r) => {
                const mgr = managerById(snap, r.manager_id);
                const label = RECORD_LABELS[r.record_key] ?? r.record_key;
                const detailParts = [
                  r.season ? String(r.season) : null,
                  r.context?.week != null ? `Wk ${r.context.week}` : null,
                ].filter(Boolean);
                return (
                  <tr key={`${r.record_key}-${r.manager_id}-${r.season}-${r.value}`}>
                    <th scope="row">{label}</th>
                    <td className="vault-num">{formatRecord(r.value, r.record_key)}</td>
                    <td className="vault-muted">
                      {mgr ? (
                        <Link href={vaultPath(slug, `/managers/${mgr.slug}`)}>
                          {mgr.display_name}
                        </Link>
                      ) : null}
                      {mgr && detailParts.length ? ' · ' : null}
                      {detailParts.join(' · ')}
                    </td>
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
