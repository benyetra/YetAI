/**
 * Vault chrome — editorial media-guide shell (mobile-first).
 */
import Link from 'next/link';
import { vaultPath, type VaultSnapshot } from '../../lib/vault';

const NAV = [
  { href: '', label: 'Home' },
  { href: '/trophies', label: 'Trophies' },
  { href: '/records', label: 'Records' },
  { href: '/managers', label: 'Managers' },
  { href: '/seasons', label: 'Seasons' },
  { href: '/h2h', label: 'H2H' },
  { href: '/transactions', label: 'Moves' },
] as const;

export function VaultNav({
  slug,
  displayName,
}: {
  slug: string;
  displayName: string;
}) {
  return (
    <header className="vault-header">
      <div className="vault-header-inner">
        <Link href={vaultPath(slug)} className="vault-brand">
          <span className="vault-brand-mark">League Vault</span>
          <span className="vault-brand-name">{displayName}</span>
        </Link>
        <nav className="vault-nav" aria-label="League sections">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={vaultPath(slug, item.href)}
              className="vault-nav-link"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}

export function VaultFooter({ slug }: { slug: string }) {
  return (
    <footer className="vault-footer">
      <p>
        Powered by{' '}
        <a href="https://yetai.app" rel="noopener noreferrer">
          YetAI
        </a>
        {' · '}
        <Link href={vaultPath(slug)}>League Vault</Link>
      </p>
    </footer>
  );
}

export function DynastyBar({
  timeline,
}: {
  timeline: VaultSnapshot['dynasty_timeline'];
}) {
  return (
    <div className="vault-dynasty" role="list" aria-label="Championship timeline">
      {timeline.map((cell) => (
        <div key={cell.season} className="vault-dynasty-cell" role="listitem">
          <span className="vault-dynasty-year">{cell.season}</span>
          <span className="vault-dynasty-name">
            {cell.champion?.display_name ?? '—'}
          </span>
        </div>
      ))}
    </div>
  );
}

export function RecordTable({
  rows,
}: {
  rows: Array<{ label: string; value: string; detail?: string }>;
}) {
  return (
    <table className="vault-table">
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}>
            <th scope="row">{r.label}</th>
            <td className="vault-num">{r.value}</td>
            <td className="vault-muted">{r.detail}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
