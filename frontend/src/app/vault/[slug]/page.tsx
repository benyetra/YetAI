import Link from 'next/link';
import { notFound } from 'next/navigation';
import { DynastyBar } from '../../../components/vault/VaultChrome';
import { fetchVaultSnapshot, latestDraftSeason, vaultPath } from '../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

export default async function VaultHomePage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  const champ = snap.reigning_champion;
  const draftSeason = latestDraftSeason(snap);

  return (
    <>
      <section className="vault-hero">
        <p className="vault-hero-kicker">
          Est. {snap.first_season ?? '—'} · {snap.seasons.length} seasons
        </p>
        <h1 className="vault-display">{snap.display_name}</h1>
        {snap.tagline ? <p className="vault-muted">{snap.tagline}</p> : null}
        <div className="vault-champ">
          <span className="vault-champ-label">Reigning champion</span>
          <span className="vault-champ-name vault-display">
            {champ ? (
              <Link href={vaultPath(slug, `/managers/${champ.slug}`)}>
                {champ.display_name}
              </Link>
            ) : (
              'TBD'
            )}
          </span>
          {champ?.season ? (
            <span className="vault-muted">{champ.season} season</span>
          ) : null}
        </div>
        <DynastyBar timeline={snap.dynasty_timeline} slug={slug} />
      </section>

      <section className="vault-section">
        <h2>Explore</h2>
        <div className="vault-grid-links">
          <Link href={vaultPath(slug, '/trophies')}>Trophy Room</Link>
          <Link href={vaultPath(slug, '/records')}>Record Book</Link>
          <Link href={vaultPath(slug, '/managers')}>Managers</Link>
          <Link href={vaultPath(slug, '/seasons')}>Seasons</Link>
          <Link href={vaultPath(slug, '/h2h')}>Head-to-Head</Link>
          <Link href={vaultPath(slug, '/transactions')}>Transactions</Link>
          {draftSeason ? (
            <Link href={vaultPath(slug, `/drafts/${draftSeason}`)}>
              Draft {draftSeason}
            </Link>
          ) : null}
        </div>
      </section>
    </>
  );
}
