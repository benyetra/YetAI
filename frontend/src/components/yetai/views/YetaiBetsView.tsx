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
  commence_time?: string | null;
  settled_at?: string | null;
  created_at?: string | null;
}

const UNAVAILABLE = 'YetAI Bets is temporarily unavailable. Please try again.';

export default function YetaiBetsView() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  const [bets, setBets] = useState<BestBet[]>([]);
  const [historyBets, setHistoryBets] = useState<YetaiHistoryBet[]>([]);
  const [historyStats, setHistoryStats] = useState<YetaiHistoryStats | null>(null);
  const [loadingBets, setLoadingBets] = useState(true);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [todayWinRate, setTodayWinRate] = useState<number | null>(null);
  const [weekRoi, setWeekRoi] = useState<number | null>(null);
  const [modelConfidence, setModelConfidence] = useState<number | null>(null);
  const [selectedBet, setSelectedBet] = useState<BestBet | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!loading && !isAuthenticated) router.push(buildLoginUrl());
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (!isAuthenticated || !user) return;
    // Live picks and history load independently: one failing must not blank the other.
    const token = localStorage.getItem('auth_token');
    const headers = {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    };

    const loadLive = async () => {
      setLoadingBets(true);
      setError(null);
      try {
        const res = await fetch(getApiUrl('/api/yetai-bets'), { headers });
        if (!res.ok) throw new Error(`live ${res.status}`);
        const liveData = await res.json();
        const liveList: BestBet[] = Array.isArray(liveData.bets) ? liveData.bets : [];
        setBets(liveList);

        const pending = liveList.filter((b) => b.status === 'pending' || b.status === 'active');
        if (pending.length > 0) {
          const avg = pending.reduce((s, b) => s + (b.confidence || 0), 0) / pending.length;
          setModelConfidence(Math.round(avg));
        } else {
          setModelConfidence(null);
        }
      } catch (e) {
        console.error(e);
        setError(UNAVAILABLE);
      } finally {
        setLoadingBets(false);
      }
    };

    const loadHistory = async () => {
      setLoadingHistory(true);
      setHistoryError(null);
      try {
        const res = await fetch(getApiUrl('/api/yetai-bets/history?days=90&limit=100'), { headers });
        if (!res.ok) throw new Error(`history ${res.status}`);
        const data = await res.json();
        const list: YetaiHistoryBet[] = Array.isArray(data.bets) ? data.bets : [];
        setHistoryBets(list);
        setHistoryStats(data.stats ?? null);
        setTodayWinRate(data.today?.win_rate ?? null);
        const wk = data.last_7d;
        setWeekRoi(wk?.graded ? Math.round((wk.units / wk.graded) * 100) : null);
      } catch (e) {
        console.error(e);
        setHistoryError(UNAVAILABLE);
      } finally {
        setLoadingHistory(false);
      }
    };

    const load = () => Promise.all([loadLive(), loadHistory()]);
    load();
  }, [isAuthenticated, user, reloadKey]);

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
        error={error}
        historyError={historyError}
        onRetry={() => setReloadKey((k) => k + 1)}
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
