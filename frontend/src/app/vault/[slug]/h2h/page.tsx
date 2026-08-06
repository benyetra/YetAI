import Link from 'next/link';
import { notFound } from 'next/navigation';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { RivalryMark } from '../../../../components/vault/illustrations';
import {
  COLUMN_HELP,
  PAGE_HELP,
  fetchVaultSnapshot,
  h2hShortName,
  vaultPath,
} from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function H2HPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const managers = [...snap.managers].sort((a, b) =>
    a.display_name.localeCompare(b.display_name),
  );

  const cell = (a: number, b: number) => {
    if (a === b) {
      return { text: '—', isSelf: true, isWinning: false };
    }
    const row = snap.h2h[String(a)]?.[String(b)];
    if (!row) {
      return { text: '0-0', isSelf: false, isWinning: false };
    }
    return {
      text: `${row.wins}-${row.losses}${row.ties ? `-${row.ties}` : ''}`,
      isSelf: false,
      isWinning: row.wins > row.losses,
    };
  };

  return (
    <>
      <VaultPageHeader
        kicker="Rivalries"
        title="Head-to-Head"
        blurb="All-time matrix. Rows vs columns — scroll sideways on smaller screens."
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
        <div className="vault-matrix">
          <table>
            <thead>
              <tr>
                <th />
                {managers.map((m) => (
                  <th key={m.id}>
                    <Link
                      href={vaultPath(slug, `/managers/${m.slug}`)}
                      aria-label={m.display_name}
                      title={m.display_name}
                    >
                      {h2hShortName(m.display_name)}
                    </Link>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {managers.map((row) => (
                <tr key={row.id}>
                  <td>
                    <Link href={vaultPath(slug, `/managers/${row.slug}`)}>
                      {row.display_name}
                    </Link>
                  </td>
                  {managers.map((col) => {
                    const result = cell(row.id, col.id);
                    const aria =
                      row.id === col.id
                        ? `${row.display_name} versus self`
                        : `${row.display_name} versus ${col.display_name}: ${result.text}`;
                    return (
                      <td
                        key={col.id}
                        aria-label={aria}
                        className={[
                          'vault-num',
                          result.isSelf ? 'vault-matrix-self' : '',
                          result.isWinning ? 'vault-matrix-win' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                      >
                        {result.text}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
