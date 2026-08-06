import Link from 'next/link';
import { notFound } from 'next/navigation';
import { VaultLabelWithHelp } from '../../../../components/vault/VaultHelp';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { StadiumMark } from '../../../../components/vault/illustrations';
import {
  PAGE_HELP,
  fetchVaultSnapshot,
  isDraftPending,
  vaultNameFitClass,
  vaultPath,
} from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function SeasonsIndexPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

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
        <table className="vault-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>Champion</th>
              <th>
                <VaultLabelWithHelp
                  help="Number of teams that competed in the season."
                  helpLabel="About teams column"
                >
                  Teams
                </VaultLabelWithHelp>
              </th>
              <th>
                <VaultLabelWithHelp
                  help="Jump to the draft board or published draft order for that year."
                  helpLabel="About draft links"
                >
                  Draft
                </VaultLabelWithHelp>
              </th>
            </tr>
          </thead>
          <tbody>
            {[...snap.seasons].reverse().map((s) => {
              const draft = s.drafts[0];
              const pending = isDraftPending(draft);
              const draftLabel =
                !draft || draft.picks.length === 0
                  ? 'Draft'
                  : pending
                    ? 'Order'
                    : 'Draft';
              return (
                <tr key={s.season}>
                  <th scope="row">
                    <Link href={vaultPath(slug, `/seasons/${s.season}`)}>{s.season}</Link>
                  </th>
                  <td>
                    {s.champion ? (
                      <span
                        className={vaultNameFitClass(s.champion.display_name)}
                        title={s.champion.display_name}
                      >
                        {s.champion.display_name}
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="vault-num">{s.team_count ?? s.teams.length}</td>
                  <td>
                    <Link href={vaultPath(slug, `/drafts/${s.season}`)}>{draftLabel}</Link>
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
