'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getApiUrl } from '@/lib/api-config';
import { useAuth } from '@/components/Auth';
import YetAIBetModal from '@/components/YetAIBetModal';
import { apiBetToDesignPick } from '@/lib/yetai-mappers';
import YetaiBetsScreen from '../screens/YetaiBetsScreen';
import type { DesignPick } from '../types';

interface BestBet {
  id: string;
  sport: string;
  game: string;
  bet_type: string;
  pick: string;
  odds: string;
  confidence: number;
  reasoning: string;
  status: string;
  is_premium: boolean;
  game_time: string;
}

export default function YetaiBetsView() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  const [bets, setBets] = useState<BestBet[]>([]);
  const [loadingBets, setLoadingBets] = useState(true);
  const [todayWinRate, setTodayWinRate] = useState(0);
  const [selectedBet, setSelectedBet] = useState<BestBet | null>(null);
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    if (!loading && !isAuthenticated) router.push('/?login=true');
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (!isAuthenticated || !user) return;
    const load = async () => {
      setLoadingBets(true);
      try {
        const token = localStorage.getItem('auth_token');
        const res = await fetch(getApiUrl('/api/yetai-bets'), {
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        });
        if (res.ok) {
          const data = await res.json();
          const list = Array.isArray(data.bets) ? data.bets : [];
          setBets(list);
          const settled = list.filter((b: BestBet) => b.status === 'won' || b.status === 'lost');
          const won = list.filter((b: BestBet) => b.status === 'won');
          setTodayWinRate(settled.length ? Math.round((won.length / settled.length) * 100) : 0);
        }
      } catch (e) {
        console.error(e);
      } finally {
        setLoadingBets(false);
      }
    };
    load();
  }, [isAuthenticated, user]);

  const picks: DesignPick[] = bets.map(apiBetToDesignPick);

  const onAdd = (pick: DesignPick) => {
    const bet = bets.find((b) => b.id === pick.id);
    if (bet) {
      setSelectedBet(bet);
      setShowModal(true);
    }
  };

  if (loading || loadingBets) {
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
    <>
      <YetaiBetsScreen
        picks={picks}
        hitRate={todayWinRate}
        roiLabel={todayWinRate ? `+${todayWinRate}%` : undefined}
        onAddToSlip={onAdd}
      />
      <YetAIBetModal
        isOpen={showModal}
        onClose={() => {
          setShowModal(false);
          setSelectedBet(null);
        }}
        bet={selectedBet}
        onBetPlaced={() => {
          setShowModal(false);
          setSelectedBet(null);
        }}
      />
    </>
  );
}
