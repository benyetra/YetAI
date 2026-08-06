import Link from 'next/link';
import { notFound } from 'next/navigation';
import { DynastyBar } from '../../../components/vault/VaultChrome';
import {
  VaultExploreIcon,
  type VaultExploreIconName,
} from '../../../components/vault/VaultExploreIcon';
import { TrophyCup } from '../../../components/vault/illustrations';
import {
  fetchVaultSnapshot,
  latestDraftSeason,
  vaultNameFitClass,
  vaultPath,
} from '../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

type ExploreTile = {
  href: string;
  label: string;
  tease: string;
  icon: VaultExploreIconName;
};

export default async function VaultHomePage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const champ = snap.reigning_champion;
  const draftSeason = latestDraftSeason(snap);
  const exploreTiles: ExploreTile[] = [
    {
      href: vaultPath(slug, '/trophies'),
      label: 'Trophies',
      tease: 'Champions, runners-up, and every finished season.',
      icon: 'trophy',
    },
    {
      href: vaultPath(slug, '/records'),
      label: 'Records',
      tease: 'Career marks and single-season league highs.',
      icon: 'records',
    },
    {
      href: vaultPath(slug, '/managers'),
      label: 'Managers',
      tease: 'Profiles for every owner in the vault.',
      icon: 'managers',
    },
    {
      href: vaultPath(slug, '/seasons'),
      label: 'Seasons',
      tease: 'Standings, matchups, and playoff paths by year.',
      icon: 'seasons',
    },
    {
      href: vaultPath(slug, '/h2h'),
      label: 'H2H',
      tease: 'Rivalry records across the whole league.',
      icon: 'h2h',
    },
    {
      href: vaultPath(slug, '/transactions'),
      label: 'Moves',
      tease: 'Waivers, trades, and roster churn by season.',
      icon: 'moves',
    },
    ...(draftSeason
      ? [
          {
            href: vaultPath(slug, `/drafts/${draftSeason}`),
            label: 'Draft',
            tease: `Latest board from the ${draftSeason} draft.`,
            icon: 'draft' as const,
          },
        ]
      : []),
  ];

  return (
    <>
      <section className="vault-hero">
        <div className="vault-hero-copy">
          <p className="vault-hero-kicker">
            Est. {snap.first_season ?? '—'} · {snap.seasons.length} seasons
          </p>
          <h1 className="vault-display">{snap.display_name}</h1>
        </div>

        <div className="vault-champ">
          <TrophyCup className="vault-illust vault-hero-trophy" />
          <div className="vault-champ-copy">
            <span className="vault-champ-label">Reigning champion</span>
            {champ ? (
              <Link
                href={vaultPath(slug, `/managers/${champ.slug}`)}
                className={`vault-champ-name vault-display vault-shimmer ${vaultNameFitClass(champ.display_name)}`}
                title={champ.display_name}
              >
                {champ.display_name}
              </Link>
            ) : (
              <span className="vault-champ-name vault-display vault-shimmer vault-name">TBD</span>
            )}
            {champ?.season ? (
              <span className="vault-champ-season">{champ.season} season title holder</span>
            ) : null}
          </div>
        </div>

        <div className="vault-hero-ctas" aria-label="Primary vault destinations">
          <Link href={vaultPath(slug, '/trophies')}>Trophy Room</Link>
          <Link href={vaultPath(slug, '/records')}>Record Book</Link>
        </div>

        <DynastyBar timeline={snap.dynasty_timeline} slug={slug} />
      </section>

      <section className="vault-section vault-explore">
        <div className="vault-section-heading">
          <h2>Explore</h2>
          <p className="vault-muted">Jump into the rooms that make up this league’s archive.</p>
        </div>
        <div className="vault-explore-grid">
          {exploreTiles.map((tile) => (
            <Link key={tile.href} href={tile.href} className="vault-explore-tile">
              <span className="vault-explore-copy">
                <span className="vault-explore-label">{tile.label}</span>
                <span className="vault-explore-tease">{tile.tease}</span>
              </span>
              <span className="vault-explore-icon" aria-hidden="true">
                <VaultExploreIcon name={tile.icon} />
              </span>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
