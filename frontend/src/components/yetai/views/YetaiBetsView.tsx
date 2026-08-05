'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getApiUrl } from '@/lib/api-config';
import { useAuth } from '@/components/Auth';
import YetAIBetModal from '@/components/YetAIBetModal';
import { apiBetToDesignPick } from '@/lib/yetai-mappers';
import type { YetaiHistoryBet, YetaiHistoryStats } from '@/components/yetai/YetaiBetsHistory';
import YetaiBetsScreen from '../screens/YetaiBetsScreen';
import type { DesignPick } from '../types';
import { buildLoginUrl } from '@/lib/auth-redirect';

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

function computeStatsFromHistory(history: YetaiHistoryBet[]) {
  const now = Date.now();
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const startOfTodayMs = startOfToday.getTime();
  const sevenDaysAgo = now - 7 * 24 * 60 * 60 * 1000;

  const settledTs = (b: YetaiHistoryBet) =>
    b.settled_at
      ? new Date(b.settled_at).getTime()
      : b.created_at
        ? new Date(b.created_at).getTime()
        : 0;

  const graded = history.filter((b) => b.status === 'won' || b.status === 'lost');

  const settledToday = graded.filter((b) => settledTs(b) >= startOfTodayMs);
  const wonToday = settledToday.filter((b) => b.status === 'won');
  const todayWinRate = settledToday.length
    ? Math.round((wonToday.length / settledToday.length) * 100)
    : 0;

  const settledWeek = graded.filter((b) => settledTs(b) >= sevenDaysAgo);
  let weekRoi: number | null = null;
  if (settledWeek.length > 0) {
    const units = settledWeek.reduce(
      (acc, b) => acc + (b.status === 'won' ? americanOddsProfit(String(b.odds)) : -1),
      0,
    );
    weekRoi = Math.round((units / settledWeek.length) * 100);
  }

  return { todayWinRate, weekRoi };
}

export default function YetaiBetsView() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  const [bets, setBets] = useState<BestBet[]>([]);
  const [historyBets, setHistoryBets] = useState<YetaiHistoryBet[]>([]);
  const [historyStats, setHistoryStats] = useState<YetaiHistoryStats | null>(null);
  const [loadingBets, setLoadingBets] = useState(true);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [todayWinRate, setTodayWinRate] = useState(0);
  const [weekRoi, setWeekRoi] = useState<number | null>(null);
  const [modelConfidence, setModelConfidence] = useState<number | null>(null);
  const [selectedBet, setSelectedBet] = useState<BestBet | null>(null);
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    if (!loading && !isAuthenticated) router.push(buildLoginUrl());
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (!isAuthenticated || !user) return;
    const load = async () => {
      setLoadingBets(true);
      setLoadingHistory(true);
      try {
        const token = localStorage.getItem('auth_token');
        const headers = {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        };

        const [liveRes, historyRes] = await Promise.all([
          fetch(getApiUrl('/api/yetai-bets'), { headers }),
          fetch(getApiUrl('/api/yetai-bets/history?days=90&limit=100'), { headers }),
        ]);

        if (liveRes.ok) {
          const data = await liveRes.json();
          const list: BestBet[] = Array.isArray(data.bets) ? data.bets : [];
          setBets(list);

          const pending = list.filter((b) => b.status === 'pending' || b.status === 'active');
          if (pending.length > 0) {
            const avg = pending.reduce((s, b) => s + (b.confidence || 0), 0) / pending.length;
            setModelConfidence(Math.round(avg));
          } else {
            setModelConfidence(null);
          }
        }

        if (historyRes.ok) {
          const data = await historyRes.json();
          const list: YetaiHistoryBet[] = Array.isArray(data.bets) ? data.bets : [];
          setHistoryBets(list);
          setHistoryStats(data.stats ?? null);
          const { todayWinRate: twr, weekRoi: wr } = computeStatsFromHistory(list);
          setTodayWinRate(twr);
          setWeekRoi(wr);
        }
      } catch (e) {
        console.error(e);
      } finally {
        setLoadingBets(false);
        setLoadingHistory(false);
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
        roiLabel={weekRoi === null ? undefined : `${weekRoi > 0 ? '+' : ''}${weekRoi}%`}
        modelConfidence={modelConfidence === null ? undefined : `${modelConfidence}%`}
        onAddToSlip={onAdd}
        historyBets={historyBets}
        historyStats={historyStats}
        historyLoading={loadingHistory}
      />
      <YetAIBetModal
        isOpen={showModal}
        onClose={() => {
          setShowModal(false);
          setSelectedBet(null);
        }}
        bet={selectedBet as React.ComponentProps<typeof YetAIBetModal>['bet']}
        onBetPlaced={() => {
          setShowModal(false);
          setSelectedBet(null);
        }}
      />
    </>
  );
}
