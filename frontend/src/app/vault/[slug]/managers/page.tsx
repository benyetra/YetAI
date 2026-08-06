import { notFound } from 'next/navigation';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { ManagersMark } from '../../../../components/vault/illustrations';
import { ManagersRosterTable } from '../../../../components/vault/tables';
import { PAGE_HELP, fetchVaultSnapshot } from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function ManagersPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const sorted = [...snap.managers].sort((a, b) => {
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
    ...sorted.map((m) => snap.manager_careers[String(m.id)]?.titles ?? 0),
  );

  const rows = sorted.map((m, index) => {
    const career = snap.manager_careers[String(m.id)];
    const titles = career?.titles ?? 0;
    return {
      id: m.id,
      slug: m.slug,
      displayName: m.display_name,
      seasonsLabel: `${m.first_season}–${m.last_season}`,
      firstSeason: m.first_season ?? 0,
      wins: career?.wins ?? 0,
      recordLabel: career
        ? `${career.wins}-${career.losses}${career.ties ? `-${career.ties}` : ''}`
        : '—',
      titles,
      highlight: index === 0 && topTitleCount > 0,
    };
  });

  return (
    <>
      <VaultPageHeader
        kicker="The roster"
        title="Managers"
        blurb="Every owner in the archive — click a column to sort."
        help={PAGE_HELP.managers}
        illustration={<ManagersMark className="vault-illust" />}
      />
      <section className="vault-section">
        <ManagersRosterTable slug={slug} rows={rows} />
      </section>
    </>
  );
}
