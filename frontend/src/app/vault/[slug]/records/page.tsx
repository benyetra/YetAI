import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Medal } from '../../../../components/vault/illustrations';
import {
  RECORD_LABELS,
  fetchVaultSnapshot,
  formatRecord,
  managerById,
  vaultPath,
  type VaultRecord,
} from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function RecordsPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const career = snap.records.filter(
    (r) =>
      r.scope === 'career' ||
      r.record_key === 'career_titles' ||
      r.record_key === 'career_wins' ||
      r.record_key === 'titles',
  );
  const featured = snap.records.filter(
    (r) =>
      r.scope !== 'career' &&
      r.record_key !== 'career_titles' &&
      r.record_key !== 'career_wins' &&
      r.record_key !== 'titles',
  );

  const recordRowKey = (r: VaultRecord) =>
    `${r.record_key}-${r.manager_id}-${r.season}-${r.value}`;

  const careerHighlightKeys = (() => {
    const maxByKey = new Map<string, number>();
    for (const r of career) {
      const prev = maxByKey.get(r.record_key);
      if (prev === undefined || r.value > prev) {
        maxByKey.set(r.record_key, r.value);
      }
    }
    const keys = new Set<string>();
    for (const r of career) {
      if (r.value === maxByKey.get(r.record_key)) {
        keys.add(recordRowKey(r));
      }
    }
    return keys;
  })();

  const renderRows = (
    rows: VaultRecord[],
    isHighlighted: (r: VaultRecord) => boolean,
  ) =>
    rows.map((r) => {
      const mgr = managerById(snap, r.manager_id);
      const label = RECORD_LABELS[r.record_key] ?? r.record_key;
      const contextSeason =
        typeof r.context?.season === 'number' || typeof r.context?.season === 'string'
          ? String(r.context.season)
          : null;
      const detailParts = [
        r.season != null ? String(r.season) : contextSeason,
        r.context?.week != null ? `Wk ${r.context.week}` : null,
      ].filter(Boolean);
      return (
        <tr
          key={recordRowKey(r)}
          className={isHighlighted(r) ? 'vault-record-highlight' : undefined}
        >
          <th scope="row">{label}</th>
          <td className="vault-num">{formatRecord(r.value, r.record_key)}</td>
          <td className="vault-muted">
            {mgr ? (
              <Link href={vaultPath(slug, `/managers/${mgr.slug}`)}>
                {mgr.display_name}
              </Link>
            ) : detailParts.length ? (
              <span>Matchup</span>
            ) : (
              '—'
            )}
            {detailParts.length ? ` · ${detailParts.join(' · ')}` : null}
          </td>
        </tr>
      );
    });

  return (
    <>
      <section className="vault-section">
        <h1 className="vault-display">Record Book</h1>
        <p className="vault-muted">All-time marks — including all-play and luck.</p>
      </section>
      {career.length > 0 ? (
        <section className="vault-section">
          <div className="vault-record-section-heading">
            <Medal className="vault-illust vault-record-heading-medal" rank={1} />
            <h2>Career</h2>
          </div>
          <table className="vault-table">
            <tbody>
              {renderRows(career, (r) => careerHighlightKeys.has(recordRowKey(r)))}
            </tbody>
          </table>
        </section>
      ) : null}
      <section className="vault-section">
        <h2>Single-season &amp; single-game</h2>
        {featured.length === 0 ? (
          <p className="vault-muted">Records will appear after the first compute pass.</p>
        ) : (
          <table className="vault-table">
            <tbody>{renderRows(featured, () => true)}</tbody>
          </table>
        )}
      </section>
    </>
  );
}
