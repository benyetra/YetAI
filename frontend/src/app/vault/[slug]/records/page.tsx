import Link from 'next/link';
import { notFound } from 'next/navigation';
import { VaultLabelWithHelp } from '../../../../components/vault/VaultHelp';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { Medal, RecordBook } from '../../../../components/vault/illustrations';
import {
  PAGE_HELP,
  RECORD_HELP,
  RECORD_LABELS,
  fetchVaultSnapshot,
  formatRecord,
  managerById,
  vaultNameFitClass,
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
      const help = RECORD_HELP[r.record_key];
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
          <th scope="row">
            <VaultLabelWithHelp help={help} helpLabel={`About ${label}`}>
              {label}
            </VaultLabelWithHelp>
          </th>
          <td className="vault-num">{formatRecord(r.value, r.record_key)}</td>
          <td className="vault-muted">
            {mgr ? (
              <Link
                href={vaultPath(slug, `/managers/${mgr.slug}`)}
                className={vaultNameFitClass(mgr.display_name)}
                title={mgr.display_name}
              >
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
      <VaultPageHeader
        kicker="All-time marks"
        title="Record Book"
        blurb="Career peaks and single-game extremes — including all-play and luck."
        help={PAGE_HELP.records}
        illustration={<RecordBook className="vault-illust" />}
      />
      {career.length > 0 ? (
        <section className="vault-section">
          <div className="vault-record-section-heading">
            <Medal className="vault-illust vault-record-heading-medal" rank={1} />
            <h2>
              <VaultLabelWithHelp
                help="Career-long marks that span a manager’s full history in this vault."
                helpLabel="About career records"
              >
                Career
              </VaultLabelWithHelp>
            </h2>
          </div>
          <table className="vault-table">
            <tbody>
              {renderRows(career, (r) => careerHighlightKeys.has(recordRowKey(r)))}
            </tbody>
          </table>
        </section>
      ) : null}
      <section className="vault-section">
        <div className="vault-section-heading">
          <h2>
            <VaultLabelWithHelp
              help="Peak performances from a single season or a single matchup."
              helpLabel="About single-season and single-game records"
            >
              Single-season &amp; single-game
            </VaultLabelWithHelp>
          </h2>
          <p className="vault-muted">
            Use the ? beside a mark for a plain-English definition — including all-play and luck.
          </p>
        </div>
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
