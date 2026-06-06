'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import DashboardScreen from '@/components/yetai/screens/DashboardScreen';
import type { ActivityBet, DesignPick } from '@/components/yetai/types';

const MOCK_PICKS: DesignPick[] = [];

const MOCK_BETS: ActivityBet[] = [
  {
    id: '1',
    pick: 'New York Knicks +6.5',
    odds: -110,
    matchup: 'Knicks @ Pacers',
    date: '2026-06-06',
    source: 'Manual',
    status: 'won',
    stake: 50,
    payout: 95.45,
  },
  {
    id: '2',
    pick: 'Parlay (2 legs)',
    odds: 241,
    matchup: 'Multi-game',
    date: '2026-06-05',
    source: 'Manual',
    status: 'lost',
    stake: 25,
    payout: 0,
  },
  {
    id: '3',
    pick: 'Julio Rodriguez OVER 0.5 hits',
    odds: -110,
    matchup: 'SEA @ BAL',
    date: '2026-06-04',
    source: 'Manual',
    status: 'pending',
    stake: 40,
    payout: 0,
  },
];

const MOCK_PNL = [
  -12, 8, -5, 15, -20, 10, 5, -8, 22, -3, 12, -15, 7, 0, -10, 18, -6, 9, -4, 11,
  -7, 14, -2, 6, -9, 13, -1, 4, -5, 214,
];

export default function DashboardPreviewPage() {
  const router = useRouter();

  useEffect(() => {
    if (process.env.NODE_ENV !== 'development') {
      router.replace('/');
    }
  }, [router]);

  if (process.env.NODE_ENV !== 'development') {
    return null;
  }

  return (
    <Layout>
      <DashboardScreen
        userName="Bennett"
        bankroll={2487.27}
        profitChange={-15}
        winRate={46}
        winRateDelta={23.8}
        openBets={0}
        openPotential={0}
        streak={1}
        featuredPicks={MOCK_PICKS}
        recentBets={MOCK_BETS}
        dailyPnl={MOCK_PNL}
      />
    </Layout>
  );
}
