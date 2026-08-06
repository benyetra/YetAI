import { notFound } from 'next/navigation';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { StadiumMark } from '../../../../components/vault/illustrations';
import { SeasonsIndexTable } from '../../../../components/vault/tables';
import { PAGE_HELP, fetchVaultSnapshot, isDraftPending } from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function SeasonsIndexPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const rows = [...snap.seasons].reverse().map((s) => {
    const draft = s.drafts[0];
    const pending = isDraftPending(draft);
    const draftLabel =
      !draft || draft.picks.length === 0 ? 'Draft' : pending ? 'Order' : 'Draft';
    return {
      season: s.season,
      championName: s.champion?.display_name ?? '',
      teams: s.team_count ?? s.teams.length,
      draftLabel,
    };
  });

  return (
    <>
      <VaultPageHeader
        kicker="Year by year"
        title="Seasons"
        blurb="Open a year for standings, the scoreboard, and that season’s draft."
        help={PAGE_HELP.seasons}
        illustration={<StadiumMark className="vault-illust" />}
      />
      <section className="vault-section">
        <SeasonsIndexTable slug={slug} rows={rows} />
      </section>
    </>
  );
}
