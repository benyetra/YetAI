'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';
import { useAuth } from '@/components/Auth';
import { liveMarketToDesignGame } from '@/lib/yetai-odds';
import LiveBettingScreen from '../screens/LiveBettingScreen';
import type { DesignGame, SlipItem } from '../types';

export default function LiveBettingView() {
  const { isAuthenticated, loading, token } = useAuth();
  const router = useRouter();
  const [games, setGames] = useState<DesignGame[]>([]);
  const [loadingMarkets, setLoadingMarkets] = useState(true);
  const [activeBets, setActiveBets] = useState(0);
  const [potentialPayout, setPotentialPayout] = useState(0);
  const [staked, setStaked] = useState(0);

  useEffect(() => {
    if (!loading && !isAuthenticated) router.push('/?login=true');
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (!token) return;
    const load = async () => {
      setLoadingMarkets(true);
      try {
        const [marketsRes, activeRes, pendingRes] = await Promise.all([
          apiClient.get('/api/live-bets/markets', token),
          apiClient.get('/api/live-bets/active', token),
          apiClient.post('/api/bets/history', { status: 'pending', limit: 50 }, token),
        ]);

        if (marketsRes.status === 'success') {
          const markets = marketsRes.markets || [];
          setGames(markets.map(liveMarketToDesignGame));
        }

        const active = activeRes.status === 'success' ? activeRes.active_bets || [] : [];
        const pending = pendingRes.status === 'success' ? pendingRes.history || [] : [];
        setActiveBets(pending.length);
        setStaked(pending.reduce((s: number, b: { stake?: number }) => s + (b.stake || 0), 0));
        const liveWin = active.reduce(
          (s: number, b: { current_potential_win?: number; potential_win?: number }) =>
            s + (b.current_potential_win || b.potential_win || 0),
          0
        );
        const pendingWin = pending.reduce((s: number, b: { potential_win?: number }) => s + (b.potential_win || 0), 0);
        setPotentialPayout(liveWin + pendingWin);
      } catch (e) {
        console.error(e);
      } finally {
        setLoadingMarkets(false);
      }
    };
    load();
  }, [token]);

  const onAddToSlip = (_item: SlipItem) => {
    router.push('/bet');
  };

  if (loading) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center">
        <div
          className="animate-spin rounded-full h-12 w-12 border-2 border-transparent"
          style={{ borderBottomColor: 'var(--accent)' }}
        />
      </div>
    );
  }

  return (
    <LiveBettingScreen
      games={games}
      activeBets={activeBets}
      staked={staked}
      potentialPayout={potentialPayout}
      onAddToSlip={onAddToSlip}
      loading={loadingMarkets}
    />
  );
}
