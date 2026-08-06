import Link from 'next/link';
import { notFound } from 'next/navigation';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { RivalryMark } from '../../../../components/vault/illustrations';
import {
  COLUMN_HELP,
  PAGE_HELP,
  fetchVaultSnapshot,
  vaultNameFitClass,
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
        blurb="All-time matrix. Columns use numbers keyed to the roster list below — scroll sideways on smaller screens."
        help={COLUMN_HELP.h2h_matrix}
        illustration={<RivalryMark className="vault-illust" />}
      />
      <section className="vault-section">
        <p className="vault-muted" style={{ marginTop: 0 }}>
          {PAGE_HELP.h2h}
        </p>

        <ol className="vault-h2h-key" aria-label="Manager column key">
          {managers.map((m, index) => (
            <li key={m.id} className="vault-h2h-key-item">
              <span className="vault-h2h-key-num" aria-hidden="true">
                {index + 1}
              </span>
              <Link
                href={vaultPath(slug, `/managers/${m.slug}`)}
                className={vaultNameFitClass(m.display_name)}
                title={m.display_name}
              >
                {m.display_name}
              </Link>
            </li>
          ))}
        </ol>

        <ul className="vault-legend" aria-label="Matrix legend">
          <li>
            <span className="vault-legend-swatch is-win" aria-hidden="true" />
            Winning record for the row manager
          </li>
          <li>
            <span className="vault-legend-swatch is-self" aria-hidden="true" />
            Same manager (diagonal)
          </li>
          <li>Column numbers match the roster key above</li>
        </ul>

        <div className="vault-matrix">
          <table>
            <thead>
              <tr>
                <th scope="col" className="vault-matrix-corner">
                  <span className="vault-matrix-corner-label">Manager</span>
                </th>
                {managers.map((m, index) => (
                  <th key={m.id} scope="col">
                    <Link
                      href={vaultPath(slug, `/managers/${m.slug}`)}
                      className="vault-h2h-col-head"
                      aria-label={`Column ${index + 1}: ${m.display_name}`}
                      title={m.display_name}
                    >
                      <span className="vault-h2h-col-num">{index + 1}</span>
                    </Link>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {managers.map((row, rowIndex) => (
                <tr key={row.id}>
                  <th scope="row">
                    <span className="vault-h2h-row-label">
                      <span className="vault-h2h-row-num" aria-hidden="true">
                        {rowIndex + 1}
                      </span>
                      <Link
                        href={vaultPath(slug, `/managers/${row.slug}`)}
                        className={vaultNameFitClass(row.display_name)}
                        title={row.display_name}
                      >
                        {row.display_name}
                      </Link>
                    </span>
                  </th>
                  {managers.map((col, colIndex) => {
                    const result = cell(row.id, col.id);
                    const aria =
                      row.id === col.id
                        ? `${row.display_name} versus self`
                        : `${row.display_name} versus ${col.display_name}: ${result.text}`;
                    return (
                      <td
                        key={col.id}
                        aria-label={aria}
                        title={
                          row.id === col.id
                            ? undefined
                            : `vs ${col.display_name} (#${colIndex + 1})`
                        }
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
