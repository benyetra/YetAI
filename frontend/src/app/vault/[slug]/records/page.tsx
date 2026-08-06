import { notFound } from 'next/navigation';
import { VaultLabelWithHelp } from '../../../../components/vault/VaultHelp';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { Medal, RecordBook } from '../../../../components/vault/illustrations';
import { RecordsBookTable, type RecordsBookRow } from '../../../../components/vault/tables';
import {
  PAGE_HELP,
  RECORD_HELP,
  RECORD_LABELS,
  fetchVaultSnapshot,
  formatRecord,
  managerById,
  resolveRecordMatchup,
  type VaultRecord,
  type VaultSnapshot,
} from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

function toRows(
  snap: VaultSnapshot,
  rows: VaultRecord[],
  isHighlighted: (r: VaultRecord) => boolean,
): RecordsBookRow[] {
  return rows.map((r) => {
    const label = RECORD_LABELS[r.record_key] ?? r.record_key;
    const mgr = managerById(snap, r.manager_id);
    const parties = resolveRecordMatchup(snap, r);
    const contextSeason =
      typeof r.context?.season === 'number' || typeof r.context?.season === 'string'
        ? String(r.context.season)
        : null;
    const detailParts = [
      r.season != null ? String(r.season) : contextSeason,
      r.context?.week != null ? `Wk ${r.context.week}` : null,
    ].filter(Boolean);

    if (parties) {
      return {
        key: `${r.record_key}-${r.manager_id}-${r.season}-${r.value}`,
        label,
        help: RECORD_HELP[r.record_key],
        value: r.value,
        valueLabel: formatRecord(r.value, r.record_key),
        holderName: `${parties.managerA.display_name} vs ${parties.managerB.display_name}`,
        holderSlug: null,
        matchup: {
          managerA: {
            slug: parties.managerA.slug,
            displayName: parties.managerA.display_name,
          },
          managerB: {
            slug: parties.managerB.slug,
            displayName: parties.managerB.display_name,
          },
        },
        detail: detailParts.join(' · '),
        highlight: isHighlighted(r),
      };
    }

    return {
      key: `${r.record_key}-${r.manager_id}-${r.season}-${r.value}`,
      label,
      help: RECORD_HELP[r.record_key],
      value: r.value,
      valueLabel: formatRecord(r.value, r.record_key),
      holderName: mgr?.display_name ?? (detailParts.length ? 'Matchup' : ''),
      holderSlug: mgr?.slug ?? null,
      detail: detailParts.join(' · '),
      highlight: isHighlighted(r),
    };
  });
}

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
          <RecordsBookTable
            slug={slug}
            rows={toRows(snap, career, (r) => careerHighlightKeys.has(recordRowKey(r)))}
          />
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
            Matchup marks show both managers. Click a column to sort; use the ? for
            definitions.
          </p>
        </div>
        {featured.length === 0 ? (
          <p className="vault-muted">Records will appear after the first compute pass.</p>
        ) : (
          <RecordsBookTable slug={slug} rows={toRows(snap, featured, () => true)} />
        )}
      </section>
    </>
  );
}
