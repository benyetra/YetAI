import Link from 'next/link';
import { notFound } from 'next/navigation';
import { VaultLabelWithHelp } from '../../../../components/vault/VaultHelp';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { ManagersMark, Medal } from '../../../../components/vault/illustrations';
import { COLUMN_HELP, PAGE_HELP, fetchVaultSnapshot, vaultPath } from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function ManagersPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const rows = [...snap.managers].sort((a, b) => {
    const careerA = snap.manager_careers[String(a.id)];
    const careerB = snap.manager_careers[String(b.id)];
    return (
      (careerB?.titles ?? 0) - (careerA?.titles ?? 0) ||
      (careerB?.wins ?? 0) - (careerA?.wins ?? 0) ||
      a.display_name.localeCompare(b.display_name)
    );
  });
  const topTitleCount = Math.max(
    0,
    ...rows.map((m) => snap.manager_careers[String(m.id)]?.titles ?? 0),
  );

  return (
    <>
      <VaultPageHeader
        kicker="The roster"
        title="Managers"
        blurb="Every owner in the archive — sorted by titles, then wins."
        help={PAGE_HELP.managers}
        illustration={<ManagersMark className="vault-illust" />}
      />
      <section className="vault-section">
        <table className="vault-table">
          <thead>
            <tr>
              <th>Manager</th>
              <th>
                <VaultLabelWithHelp
                  help={COLUMN_HELP.seasons_span}
                  helpLabel="About seasons column"
                >
                  Seasons
                </VaultLabelWithHelp>
              </th>
              <th>
                <VaultLabelWithHelp help={COLUMN_HELP.record} helpLabel="About record column">
                  Record
                </VaultLabelWithHelp>
              </th>
              <th>
                <VaultLabelWithHelp help={COLUMN_HELP.titles} helpLabel="About titles column">
                  Titles
                </VaultLabelWithHelp>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m, index) => {
              const career = snap.manager_careers[String(m.id)];
              const titles = career?.titles ?? 0;
              const record = career
                ? `${career.wins}-${career.losses}${career.ties ? `-${career.ties}` : ''}`
                : '—';
              return (
                <tr
                  key={m.id}
                  className={index === 0 && topTitleCount > 0 ? 'vault-rank-1' : undefined}
                >
                  <th scope="row">
                    <Link href={vaultPath(slug, `/managers/${m.slug}`)}>
                      {m.display_name}
                    </Link>
                  </th>
                  <td className="vault-muted">
                    {m.first_season}–{m.last_season}
                  </td>
                  <td className="vault-num">{record}</td>
                  <td className="vault-num">
                    {titles > 0 ? (
                      <span className="vault-title-count">
                        <Medal className="vault-illust vault-title-count-medal" rank={1} />
                        {titles}
                      </span>
                    ) : (
                      titles
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </>
  );
}
