import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ShareSeasonCard } from '../../../../components/vault/ShareSeasonCard';
import { DroughtStreakStrip } from '../../../../components/vault/VaultIntrigue';
import { VaultHelp } from '../../../../components/vault/VaultHelp';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { Medal, Podium, TrophyCup } from '../../../../components/vault/illustrations';
import { TitlesTable } from '../../../../components/vault/tables';
import {
  PAGE_HELP,
  fetchVaultSnapshot,
  managerById,
  type VaultManager,
  vaultNameFitClass,
  vaultPath,
} from '../../../../lib/vault';
import {
  buildShareSeasonCard,
  buildTitleDroughts,
  buildTitleStreaks,
} from '../../../../lib/vault-intrigue';

type Props = { params: Promise<{ slug: string }> };
type TitleLeader = { manager: VaultManager; n: number };
type PodiumSlot = { rank: 1 | 2 | 3; leader: TitleLeader; className: string };

function titleCopy(count: number): string {
  return count === 1 ? 'title' : 'titles';
}

function rankClass(index: number): string | undefined {
  if (index === 0) return 'vault-rank-1';
  if (index === 1) return 'vault-rank-2';
  if (index === 2) return 'vault-rank-3';
  return undefined;
}

export default async function TrophiesPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const titleCounts = new Map<number, number>();
  for (const s of snap.seasons) {
    if (s.champion?.id != null) {
      titleCounts.set(s.champion.id, (titleCounts.get(s.champion.id) ?? 0) + 1);
    }
  }
  const leaderboard = [...titleCounts.entries()]
    .flatMap<TitleLeader>(([id, n]) => {
      const manager = managerById(snap, id);
      return manager ? [{ manager, n }] : [];
    })
    .sort((a, b) => b.n - a.n || a.manager.display_name.localeCompare(b.manager.display_name));
  const podiumSlots = [
    { rank: 1 as const, leader: leaderboard[0], className: 'is-first' },
    { rank: 2 as const, leader: leaderboard[1], className: 'is-second' },
    { rank: 3 as const, leader: leaderboard[2], className: 'is-third' },
  ].filter((slot): slot is PodiumSlot => Boolean(slot.leader));

  const streaks = buildTitleStreaks(snap);
  const droughts = buildTitleDroughts(snap);
  const shareCards = [...snap.seasons]
    .reverse()
    .map((s) => buildShareSeasonCard(snap, s, slug))
    .filter((c): c is NonNullable<typeof c> => Boolean(c))
    .slice(0, 3);

  return (
    <>
      <VaultPageHeader
        kicker="League honors"
        title="Trophy Room"
        blurb={`Champions, runners-up, and the ${snap.last_place_label}.`}
        help={PAGE_HELP.trophies}
        illustration={<TrophyCup className="vault-illust" />}
      />

      <DroughtStreakStrip slug={slug} streaks={streaks} droughts={droughts} />

      {shareCards.length > 0 ? (
        <section className="vault-section vault-share-section" aria-labelledby="share-heading">
          <div className="vault-section-heading">
            <h2 id="share-heading">Shareable crowns</h2>
            <p className="vault-muted">Postcard the latest title years into the chat.</p>
          </div>
          <div className="vault-share-grid">
            {shareCards.map((card) => (
              <ShareSeasonCard key={card.season} card={card} />
            ))}
          </div>
        </section>
      ) : null}

      <section className="vault-section vault-title-podium" aria-labelledby="title-podium-heading">
        <div className="vault-section-heading">
          <h2 id="title-podium-heading">
            <span className="vault-label-with-help">
              Title leaders podium
              <VaultHelp
                text="Managers ranked by championships recorded in finished seasons."
                label="About title leaders podium"
              />
            </span>
          </h2>
          <p className="vault-muted">The managers with the most recorded championships.</p>
        </div>
        {podiumSlots.length === 0 ? (
          <p className="vault-muted">No champions recorded yet.</p>
        ) : (
          <div className="vault-podium-stage">
            <Podium className="vault-illust vault-podium-illust" />
            <div className="vault-podium-slots">
              {podiumSlots.map(({ rank, leader, className }) => (
                <Link
                  key={leader.manager.id}
                  href={vaultPath(slug, `/managers/${leader.manager.slug}`)}
                  className={`vault-podium-card ${className} vault-rank-${rank}`}
                >
                  <Medal className="vault-illust vault-podium-medal" rank={rank} />
                  <span className="vault-podium-rank">No. {rank}</span>
                  <span
                    className={`vault-podium-name ${vaultNameFitClass(leader.manager.display_name)}`}
                    title={leader.manager.display_name}
                  >
                    {leader.manager.display_name}
                  </span>
                  <span className="vault-podium-count">
                    <strong className="vault-num">{leader.n}</strong> {titleCopy(leader.n)}
                  </span>
                </Link>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="vault-section">
        <div className="vault-section-heading">
          <h2>Season chronicle</h2>
          <p className="vault-muted">Every year’s podium finish and final footnote.</p>
        </div>
        <div className="vault-season-chronicle">
          {[...snap.seasons].reverse().map((s) => {
            const isComplete = Boolean(s.champion);
            return (
              <article
                key={s.season}
                className={`vault-season-entry${isComplete ? '' : ' is-in-progress'}`}
              >
                <div className="vault-season-year">
                  <span className="vault-num">{s.season}</span>
                </div>
                <div className="vault-season-results">
                  <div
                    className={`vault-season-result is-champion${s.champion ? '' : ' is-no-medal'}`}
                  >
                    {s.champion ? (
                      <>
                        <Medal className="vault-illust vault-season-medal" rank={1} />
                        <span className="vault-season-label">Champion</span>
                        <Link
                          href={vaultPath(slug, `/managers/${s.champion.slug}`)}
                          className={vaultNameFitClass(s.champion.display_name)}
                          title={s.champion.display_name}
                        >
                          {s.champion.display_name}
                        </Link>
                      </>
                    ) : (
                      <>
                        <span className="vault-season-label">Season status</span>
                        <span className="vault-muted">In progress</span>
                      </>
                    )}
                  </div>
                  <div
                    className={`vault-season-result is-runner-up${s.runner_up && !isComplete ? ' is-no-medal' : ''}`}
                  >
                    {s.runner_up ? (
                      <>
                        {isComplete ? (
                          <Medal className="vault-illust vault-season-medal" rank={2} />
                        ) : null}
                        <span className="vault-season-label">Runner-up</span>
                        <Link
                          href={vaultPath(slug, `/managers/${s.runner_up.slug}`)}
                          className={vaultNameFitClass(s.runner_up.display_name)}
                          title={s.runner_up.display_name}
                        >
                          {s.runner_up.display_name}
                        </Link>
                      </>
                    ) : (
                      <>
                        <span className="vault-season-label">Runner-up</span>
                        <span className="vault-muted">—</span>
                      </>
                    )}
                  </div>
                  <div className="vault-season-result is-last-place">
                    <span className="vault-season-label">{snap.last_place_label}</span>
                    {s.last_place ? (
                      <Link
                        href={vaultPath(slug, `/managers/${s.last_place.slug}`)}
                        className={vaultNameFitClass(s.last_place.display_name)}
                        title={s.last_place.display_name}
                      >
                        {s.last_place.display_name}
                      </Link>
                    ) : (
                      <span className="vault-muted">—</span>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="vault-section">
        <div className="vault-section-heading">
          <h2>Titles</h2>
          <p className="vault-muted">Full championship tally for every manager with a crown.</p>
        </div>
        {leaderboard.length === 0 ? (
          <p className="vault-muted">No champions recorded yet.</p>
        ) : (
          <TitlesTable
            slug={slug}
            rows={leaderboard.map(({ manager, n }, index) => ({
              id: manager.id,
              slug: manager.slug,
              displayName: manager.display_name,
              titles: n,
              titleLabel: titleCopy(n),
              rankClass: rankClass(index),
            }))}
          />
        )}
      </section>
    </>
  );
}
