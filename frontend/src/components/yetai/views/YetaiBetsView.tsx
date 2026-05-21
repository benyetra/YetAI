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
  settled_at?: string | null;
  created_at?: string | null;
}

function americanOddsProfit(odds: string): number {
  const n = parseInt(odds, 10);
  if (!Number.isFinite(n) || n === 0) return 0;
  return n > 0 ? n / 100 : 100 / Math.abs(n);
}

export default function YetaiBetsView() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  const [bets, setBets] = useState<BestBet[]>([]);
  const [loadingBets, setLoadingBets] = useState(true);
  const [todayWinRate, setTodayWinRate] = useState(0);
  const [weekRoi, setWeekRoi] = useState<number | null>(null);
  const [modelConfidence, setModelConfidence] = useState<number | null>(null);
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
          const list: BestBet[] = Array.isArray(data.bets) ? data.bets : [];
          setBets(list);

          const now = new Date();
          const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
          const sevenDaysAgo = now.getTime() - 7 * 24 * 60 * 60 * 1000;
          const settledTimestamp = (b: BestBet) =>
            b.settled_at ? new Date(b.settled_at).getTime() : b.created_at ? new Date(b.created_at).getTime() : 0;

          const settledToday = list.filter(
            (b) => (b.status === 'won' || b.status === 'lost') && settledTimestamp(b) >= startOfToday,
          );
          const wonToday = settledToday.filter((b) => b.status === 'won');
          setTodayWinRate(
            settledToday.length ? Math.round((wonToday.length / settledToday.length) * 100) : 0,
          );

          const settledWeek = list.filter(
            (b) => (b.status === 'won' || b.status === 'lost') && settledTimestamp(b) >= sevenDaysAgo,
          );
          if (settledWeek.length > 0) {
            const units = settledWeek.reduce(
              (acc, b) => acc + (b.status === 'won' ? americanOddsProfit(b.odds) : -1),
              0,
            );
            setWeekRoi(Math.round((units / settledWeek.length) * 100));
          } else {
            setWeekRoi(null);
          }

          const pending = list.filter((b) => b.status === 'pending');
          if (pending.length > 0) {
            const avg = pending.reduce((s, b) => s + (b.confidence || 0), 0) / pending.length;
            setModelConfidence(Math.round(avg));
          } else {
            setModelConfidence(null);
          }
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
        roiLabel={
          weekRoi === null ? undefined : `${weekRoi > 0 ? '+' : ''}${weekRoi}%`
        }
        modelConfidence={modelConfidence === null ? undefined : `${modelConfidence}%`}
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
