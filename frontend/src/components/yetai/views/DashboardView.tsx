'use client';

import React, { useEffect, useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { useAuth } from '@/components/Auth';
import { apiBetToDesignPick, apiHistoryToActivity } from '@/lib/yetai-mappers';
import DashboardScreen from '../screens/DashboardScreen';
import type { ActivityBet, DesignPick } from '../types';

export default function DashboardView() {
  const { user, token } = useAuth();
  const [loading, setLoading] = useState(true);
  const [featuredPicks, setFeaturedPicks] = useState<DesignPick[]>([]);
  const [recentBets, setRecentBets] = useState<ActivityBet[]>([]);
  const [bankroll, setBankroll] = useState(0);
  const [winRate, setWinRate] = useState(0);
  const [winRateDelta, setWinRateDelta] = useState(0);
  const [weekDelta, setWeekDelta] = useState(0);
  const [openBets, setOpenBets] = useState(0);
  const [openPotential, setOpenPotential] = useState(0);
  const [streak, setStreak] = useState(0);
  const [dailyPnl, setDailyPnl] = useState<number[]>([]);

  useEffect(() => {
    if (!token) return;

    const load = async () => {
      setLoading(true);
      try {
        const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

        const [perfRes, betsRes, historyRes] = await Promise.all([
          fetch(getApiUrl('/api/user/performance'), { headers }),
          fetch(getApiUrl('/api/yetai-bets'), { headers }),
          fetch(getApiUrl('/api/bets/history'), {
            method: 'POST',
            headers,
            body: JSON.stringify({ limit: 10 }),
          }),
        ]);

        if (perfRes.ok) {
          const perf = await perfRes.json();
          const ps = perf.personal_stats || {};
          setBankroll(ps.bankroll ?? ps.total_profit ?? 0);
          setWinRate(ps.accuracy_rate ?? 0);
          setWinRateDelta(ps.accuracy_change ?? 0);
          setWeekDelta(ps.weekly_bet_change ?? 0);
          setStreak(ps.win_streak ?? 0);
          if (Array.isArray(ps.daily_pnl)) {
            setDailyPnl(ps.daily_pnl);
          }
        }

        if (betsRes.ok) {
          const data = await betsRes.json();
          const list = Array.isArray(data.bets) ? data.bets : [];
          setFeaturedPicks(list.slice(0, 3).map(apiBetToDesignPick));
        }

        if (historyRes.ok) {
          const data = await historyRes.json();
          const list = data.history || data.bets || [];
          setRecentBets(list.map(apiHistoryToActivity));
          const pending = list.filter((b: { status?: string }) => (b.status || '').toLowerCase() === 'pending');
          setOpenBets(pending.length);
          setOpenPotential(
            pending.reduce((s: number, b: { potential_win?: number }) => s + (b.potential_win || 0), 0)
          );
        }
      } catch (e) {
        console.error('Dashboard load failed', e);
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [token]);

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
    <DashboardScreen
      userName={user?.first_name}
      bankroll={bankroll}
      weekDelta={weekDelta}
      winRate={winRate}
      winRateDelta={winRateDelta}
      openBets={openBets}
      openPotential={openPotential}
      streak={streak}
      featuredPicks={featuredPicks}
      recentBets={recentBets}
      dailyPnl={dailyPnl}
    />
  );
}
