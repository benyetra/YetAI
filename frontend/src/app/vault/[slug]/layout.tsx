import type { Metadata } from 'next';
import { Newsreader, Source_Sans_3 } from 'next/font/google';
import { notFound } from 'next/navigation';
import './../vault.css';
import { VaultFooter, VaultNav } from '../../../components/vault/VaultChrome';
import { fetchVaultSnapshot } from '../../../lib/vault';

const display = Newsreader({
  subsets: ['latin'],
  variable: '--font-vault-display',
  display: 'swap',
});

const sans = Source_Sans_3({
  subsets: ['latin'],
  variable: '--font-vault-sans',
  display: 'swap',
});

type Props = {
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) {
    return { title: 'League Vault' };
  }
  const title = `${snap.display_name} · League Vault`;
  const description =
    snap.tagline ||
    `League history, trophies, and records — Est. ${snap.first_season ?? '—'}`;
  return {
    title,
    description,
    openGraph: {
      title,
      description,
      siteName: 'YetAI League Vault',
      type: 'website',
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description,
    },
  };
}

export default async function VaultLayout({ children, params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();

  return (
    <div className={`vault-root ${display.variable} ${sans.variable} ${sans.className}`}>
      <VaultNav slug={slug} displayName={snap.display_name} />
      <main className="vault-main">{children}</main>
      <VaultFooter slug={slug} />
    </div>
  );
}
