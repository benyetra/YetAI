import { notFound } from 'next/navigation';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { RivalryMark } from '../../../../components/vault/illustrations';
import { H2HMatrixTable, type H2HCell } from '../../../../components/vault/tables';
import { COLUMN_HELP, PAGE_HELP, fetchVaultSnapshot } from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function H2HPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const managers = [...snap.managers]
    .sort((a, b) => a.display_name.localeCompare(b.display_name))
    .map((m) => ({
      id: m.id,
      slug: m.slug,
      displayName: m.display_name,
    }));

  const matrix: Record<string, Record<string, H2HCell>> = {};
  for (const row of managers) {
    matrix[String(row.id)] = {};
    for (const col of managers) {
      if (row.id === col.id) {
        matrix[String(row.id)][String(col.id)] = {
          text: '—',
          isSelf: true,
          isWinning: false,
        };
        continue;
      }
      const rec = snap.h2h[String(row.id)]?.[String(col.id)];
      if (!rec) {
        matrix[String(row.id)][String(col.id)] = {
          text: '0-0',
          isSelf: false,
          isWinning: false,
        };
        continue;
      }
      matrix[String(row.id)][String(col.id)] = {
        text: `${rec.wins}-${rec.losses}${rec.ties ? `-${rec.ties}` : ''}`,
        isSelf: false,
        isWinning: rec.wins > rec.losses,
      };
    }
  }

  return (
    <>
      <VaultPageHeader
        kicker="Rivalries"
        title="Head-to-Head"
        blurb="All-time matrix. Sort managers with the corner control — scroll sideways on smaller screens."
        help={COLUMN_HELP.h2h_matrix}
        illustration={<RivalryMark className="vault-illust" />}
      />
      <section className="vault-section">
        <p className="vault-muted" style={{ marginTop: 0 }}>
          {PAGE_HELP.h2h}
        </p>
        <ul className="vault-legend" aria-label="Matrix legend">
          <li>
            <span className="vault-legend-swatch is-win" aria-hidden="true" />
            Winning record for the row manager
          </li>
          <li>
            <span className="vault-legend-swatch is-self" aria-hidden="true" />
            Same manager (diagonal)
          </li>
        </ul>
        <H2HMatrixTable slug={slug} managers={managers} matrix={matrix} />
      </section>
    </>
  );
}
