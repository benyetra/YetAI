/**
 * Vault chrome — editorial media-guide shell (mobile-first).
 */
'use client';

import type { CSSProperties } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { vaultNameFitClass, vaultPath, type VaultSnapshot } from '../../lib/vault';
import { dynastyCellNote } from '../../lib/vault-intrigue';
import { StadiumMark } from './illustrations';

const NAV = [
  { href: '', label: 'Home' },
  { href: '/trophies', label: 'Trophies' },
  { href: '/records', label: 'Records' },
  { href: '/managers', label: 'Managers' },
  { href: '/seasons', label: 'Seasons' },
  { href: '/lottery', label: 'Lottery' },
  { href: '/h2h', label: 'H2H' },
  { href: '/transactions', label: 'Moves' },
] as const;

function navActive(pathname: string, slug: string, href: string): boolean {
  const base = vaultPath(slug);
  const target = vaultPath(slug, href);
  if (!href) {
    return pathname === base || pathname === `${base}/`;
  }
  return pathname === target || pathname.startsWith(`${target}/`);
}

export function VaultNav({
  slug,
  displayName,
}: {
  slug: string;
  displayName: string;
}) {
  const pathname = usePathname() || '';
  return (
    <header className="vault-header">
      <div className="vault-header-inner">
        <Link href={vaultPath(slug)} className="vault-brand">
          <span className="vault-brand-mark">
            <StadiumMark className="vault-brand-icon" />
            <span>League Vault</span>
          </span>
          <span
            className={`vault-brand-name ${vaultNameFitClass(displayName)}`}
            title={displayName}
          >
            {displayName}
          </span>
        </Link>
        <nav className="vault-nav" aria-label="League sections">
          {NAV.map((item) => {
            const active = navActive(pathname, slug, item.href);
            return (
              <Link
                key={item.href}
                href={vaultPath(slug, item.href)}
                className={`vault-nav-link${active ? ' is-active' : ''}`}
                aria-current={active ? 'page' : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

export function VaultFooter({ slug }: { slug: string }) {
  return (
    <footer className="vault-footer">
      <div className="vault-footer-inner">
        <div className="vault-footer-brand">
          <StadiumMark className="vault-footer-mark" />
          <div>
            <strong>League Vault</strong>
            <span>Championship archives, records, and draft boards.</span>
          </div>
        </div>
        <p>
          Powered by{' '}
          <a href="https://yetai.app" rel="noopener noreferrer">
            YetAI
          </a>
          {' · '}
          <Link href={vaultPath(slug)}>Back to vault home</Link>
        </p>
      </div>
    </footer>
  );
}

export function DynastyBar({
  timeline,
  slug,
  snapshot,
}: {
  timeline: VaultSnapshot['dynasty_timeline'];
  slug?: string;
  /** When provided, cell notes include back-to-backs / three-peats. */
  snapshot?: VaultSnapshot;
}) {
  const mostRecentChampionSeason = [...timeline]
    .reverse()
    .find((cell) => cell.champion)?.season;

  return (
    <div className="vault-dynasty" role="list" aria-label="Championship timeline">
      {timeline.map((cell, index) => {
        const isMostRecentChampion = cell.season === mostRecentChampionSeason;
        const note = snapshot
          ? dynastyCellNote(snapshot, cell.season, cell.champion?.id)
          : cell.champion
            ? isMostRecentChampion
              ? 'Current crown'
              : 'Champion'
            : 'In progress';
        const streaky = /peat|Back-to-back|Year \d/.test(note);
        return (
          <div
            key={cell.season}
            className={`vault-dynasty-cell${isMostRecentChampion ? ' is-current-champ' : ''}${
              streaky ? ' is-streak' : ''
            }`}
            role="listitem"
            style={{ '--vault-dynasty-delay': `${index * 55}ms` } as CSSProperties}
          >
            <span className="vault-dynasty-year">{cell.season}</span>
            <span className="vault-dynasty-name">
              {cell.champion && slug ? (
                <Link
                  href={vaultPath(slug, `/managers/${cell.champion.slug}`)}
                  className={vaultNameFitClass(cell.champion.display_name)}
                  title={cell.champion.display_name}
                >
                  {cell.champion.display_name}
                </Link>
              ) : (
                <span
                  className={vaultNameFitClass(cell.champion?.display_name ?? 'TBD')}
                  title={cell.champion?.display_name}
                >
                  {cell.champion?.display_name ?? 'TBD'}
                </span>
              )}
            </span>
            <span className="vault-dynasty-note">{note}</span>
          </div>
        );
      })}
    </div>
  );
}
