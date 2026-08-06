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
    if (a === b) return '—';
    const row = snap.h2h[String(a)]?.[String(b)];
    if (!row) return '0-0';
    return `${row.wins}-${row.losses}${row.ties ? `-${row.ties}` : ''}`;
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
                {managers.map((col) => (
                  <td key={col.id} className="vault-num">
                    {cell(row.id, col.id)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
