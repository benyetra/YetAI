import Link from 'next/link';
import { notFound } from 'next/navigation';
import {
  DraftLotteryClient,
  type LotteryPayload,
} from '../../../../components/vault/DraftLotteryClient';
import { VaultPageHeader } from '../../../../components/vault/VaultPageHeader';
import { DraftBoard } from '../../../../components/vault/illustrations';
import { fetchVaultSnapshot, vaultPath } from '../../../../lib/vault';

type Props = { params: Promise<{ slug: string }> };

function apiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.replace(/\/$/, '');
  }
  if (process.env.VERCEL_ENV === 'production' || process.env.NODE_ENV === 'production') {
    return 'https://api.yetai.app';
  }
  return 'http://localhost:8000';
}

async function fetchLottery(slug: string): Promise<LotteryPayload | null> {
  const url = `${apiBase()}/api/vault/${encodeURIComponent(slug)}/lottery`;
  const res = await fetch(url, { next: { revalidate: 30 } });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Lottery fetch failed: ${res.status}`);
  }
  return (await res.json()) as LotteryPayload;
}

export default async function DraftLotteryPage({ params }: Props) {
  const { slug } = await params;
  const snap = await fetchVaultSnapshot(slug);
  if (!snap) notFound();
  const lottery = await fetchLottery(slug);
  if (!lottery) notFound();

  return (
    <>
      <VaultPageHeader
        kicker={<Link href={vaultPath(slug, '/seasons')}>Seasons</Link>}
        title={`${lottery.upcoming_season} Draft Lottery`}
        blurb={`Weighted order for next year’s draft, seeded from the ${lottery.source_season} finish — classic NBA ping-pong odds.`}
        help="Non-playoff teams enter a weighted lottery for the top picks. Playoff teams fill the rest of the board in reverse playoff finish. Running the lottery locks the order permanently."
        illustration={<DraftBoard className="vault-illust" />}
      />
      <DraftLotteryClient slug={slug} initial={lottery} apiBase={apiBase()} />
    </>
  );
}
