import Link from 'next/link';
import { notFound } from 'next/navigation';
import { fetchVaultSnapshot, h2hShortName, vaultPath } from '../../../../lib/vault';

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
      <section className="vault-section">
        <h1 className="vault-display">Head-to-Head</h1>
        <p className="vault-muted">All-time matrix. Rows vs columns.</p>
      </section>
      <section className="vault-section vault-matrix">
        <table>
          <thead>
            <tr>
              <th />
              {managers.map((m) => (
                <th key={m.id} title={m.display_name}>
                  <Link href={vaultPath(slug, `/managers/${m.slug}`)}>
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
                  return (
                    <td
                      key={col.id}
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
      </section>
    </>
  );
}
