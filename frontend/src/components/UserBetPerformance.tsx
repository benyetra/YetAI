'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { BarChart3 } from 'lucide-react';
import AppLoading from '@/components/yetai/AppLoading';
import BreakdownBars, { type BreakdownItem } from '@/components/yetai/BreakdownBars';
import MyBetsPnLChart from '@/components/yetai/MyBetsPnLChart';
import { EmptyState } from '@/components/yetai/primitives';
import { StatTile } from '@/components/yetai/primitives';
import { sportsAPI } from '@/lib/api';
import { getApiUrl } from '@/lib/api-config';
import { fmtMoney } from '@/lib/yetai-format';

export interface PerformanceData {
  status: string;
  period_days: number;
  overview: {
    total_bets: number;
    total_wagered: number;
    total_profit: number;
    win_rate: number;
    roi: number;
    won_bets: number;
    lost_bets: number;
    pending_bets: number;
  };
  sport_breakdown: Array<{
    sport: string;
    sport_name: string;
    total_bets: number;
    total_wagered: number;
    profit_loss: number;
    win_rate: number;
    roi: number;
  }>;
  bet_type_breakdown: Array<{
    bet_type: string;
    bet_type_name: string;
    total_bets: number;
    total_wagered: number;
    profit_loss: number;
    win_rate: number;
    roi: number;
  }>;
  daily_pnl: number[];
  win_rate_delta?: number;
  profit_delta?: number;
  chart_days?: number;
}

type UserBetPerformanceProps = {
  selectedPeriod: number;
};

function periodLabel(days: number): string {
  if (days >= 365) return 'all time';
  if (days >= 90) return 'last 3 months';
  if (days >= 30) return 'last 30 days';
  if (days >= 14) return 'last 14 days';
  return `last ${days} days`;
}

/** API uses `total` (betting analytics) or `count` (performance tracker). */
function mapMetricsBreakdownEntry(
  key: string,
  data: Record<string, unknown>,
  labelFormatter: (k: string) => string,
): {
  key: string;
  sport: string;
  sport_name: string;
  bet_type: string;
  bet_type_name: string;
  total_bets: number;
  total_wagered: number;
  profit_loss: number;
  win_rate: number;
  roi: number;
} {
  const total_bets = Number(data.total ?? data.count ?? 0);
  const total_wagered = Number(data.total_wagered ?? 0);
  const profit_loss = Number(data.net_profit ?? data.profit_loss ?? 0);
  const win_rate = Math.round(Number(data.win_rate ?? 0));
  const label = labelFormatter(key);
  return {
    key,
    sport: key,
    sport_name: label,
    bet_type: key,
    bet_type_name: label,
    total_bets,
    total_wagered,
    profit_loss,
    win_rate,
    roi:
      total_wagered > 0 ? Math.round((profit_loss / total_wagered) * 100) : 0,
  };
}

export default function UserBetPerformance({ selectedPeriod }: UserBetPerformanceProps) {
  const router = useRouter();
  const [performanceData, setPerformanceData] = useState<PerformanceData | null>(null);
  const [isLoadingData, setIsLoadingData] = useState(true);
  const [error, setError] = useState('');
  const [actualPendingCount, setActualPendingCount] = useState(0);

  useEffect(() => {
    fetchPerformanceData();
    fetchPendingBetsCount();
  }, [selectedPeriod]);

  const fetchPendingBetsCount = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(getApiUrl('/api/bets/history'), {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          status: 'pending',
          limit: 100,
          offset: 0,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        if (data.status === 'success' && typeof data.total === 'number') {
          setActualPendingCount(data.total);
        }
      }
    } catch (err) {
      console.error('Error fetching pending bets count:', err);
    }
  };

  const fetchPerformanceData = async () => {
    try {
      setIsLoadingData(true);
      setError('');

      const token = localStorage.getItem('auth_token');
      const response = await sportsAPI.getUserPerformance(selectedPeriod, token ?? undefined);

      if (response.status === 'success') {
        const metrics = response.metrics || {};
        const personal = response.personal_stats || {};
        const trends = metrics.trends || {};

        const apiPeriodDays = Number(response.metrics?.period_days ?? selectedPeriod);
        const apiChartDays = Number(response.metrics?.chart_days ?? Math.min(apiPeriodDays, 14));
        const profitChange = trends.profit_change;

        const transformedData: PerformanceData = {
          status: response.status,
          period_days: apiPeriodDays,
          overview: {
            total_bets: metrics.total_predictions || 0,
            total_wagered: metrics.total_wagered || 0,
            total_profit: metrics.net_profit || 0,
            win_rate: Math.round(metrics.overall_accuracy || 0),
            roi:
              metrics.total_wagered > 0
                ? Math.round((metrics.net_profit / metrics.total_wagered) * 100)
                : 0,
            won_bets: Math.round(
              (metrics.resolved_predictions || 0) * (metrics.success_rate || 0),
            ),
            lost_bets:
              (metrics.resolved_predictions || 0) -
              Math.round((metrics.resolved_predictions || 0) * (metrics.success_rate || 0)),
            pending_bets: metrics.pending_predictions || 0,
          },
          sport_breakdown: metrics.by_sport
            ? Object.entries(metrics.by_sport)
                .map(([sport, data]) =>
                  mapMetricsBreakdownEntry(sport, data as Record<string, unknown>, (s) =>
                    s.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase()),
                  ),
                )
                .filter((row) => row.total_bets > 0)
            : [],
          bet_type_breakdown: metrics.by_type
            ? Object.entries(metrics.by_type)
                .map(([type, data]) =>
                  mapMetricsBreakdownEntry(type, data as Record<string, unknown>, (t) =>
                    t.charAt(0).toUpperCase() + t.slice(1),
                  ),
                )
                .filter((row) => row.total_bets > 0)
            : [],
          daily_pnl: Array.isArray(personal.daily_pnl) ? personal.daily_pnl : [],
          win_rate_delta: trends.accuracy_change,
          profit_delta: typeof profitChange === 'number' ? profitChange : undefined,
          chart_days: apiChartDays,
        };

        setPerformanceData(transformedData);
      } else {
        setError('Failed to load performance data');
      }
    } catch (err) {
      console.error('Error fetching performance data:', err);
      setError('Failed to load performance data');
    } finally {
      setIsLoadingData(false);
    }
  };

  const sportItems: BreakdownItem[] = useMemo(() => {
    if (!performanceData?.sport_breakdown?.length) return [];
    return performanceData.sport_breakdown.slice(0, 6).map((s) => ({
      key: s.sport,
      label: s.sport_name,
      sublabel: `${s.total_bets} bets · ${s.win_rate}%`,
      profit: s.profit_loss,
      weight: s.total_bets,
    }));
  }, [performanceData]);

  const typeItems: BreakdownItem[] = useMemo(() => {
    if (!performanceData?.bet_type_breakdown?.length) return [];
    return performanceData.bet_type_breakdown.slice(0, 6).map((t) => ({
      key: t.bet_type,
      label: t.bet_type_name,
      sublabel: `${t.total_bets} bet${t.total_bets !== 1 ? 's' : ''} · ${t.win_rate}%`,
      profit: t.profit_loss,
      weight: t.total_bets,
    }));
  }, [performanceData]);

  if (isLoadingData) {
    return <AppLoading />;
  }

  if (error || !performanceData?.overview) {
    return (
      <div className="card">
        {error ? (
          <EmptyState
            title="Could not load performance"
            body={error}
            action={
              <button type="button" className="btn btn-primary" onClick={fetchPerformanceData}>
                Try again
              </button>
            }
          />
        ) : (
          <EmptyState
            icon={<BarChart3 size={16} />}
            title="No betting data yet"
            body="Start placing bets to see performance analytics here."
            action={
              <button type="button" className="btn btn-primary" onClick={() => router.push('/bet')}>
                Place a bet
              </button>
            }
          />
        )}
      </div>
    );
  }

  const { overview, daily_pnl, win_rate_delta, profit_delta, period_days, chart_days } =
    performanceData;
  const pending = actualPendingCount > 0 ? actualPendingCount : overview.pending_bets;
  const chartDayCount = chart_days ?? Math.min(period_days, 14);
  const chartData = daily_pnl.length ? daily_pnl.slice(-chartDayCount) : [];
  const chartPeriodText = periodLabel(chartDayCount);

  return (
    <>
      <div className="stat-grid cols-4">
        <StatTile
          label={`Net profit · ${period_days}d`}
          value={fmtMoney(overview.total_profit, { signed: true })}
          delta={
            profit_delta != null ? fmtMoney(profit_delta, { signed: true }) : undefined
          }
          deltaKind={profit_delta != null && profit_delta < 0 ? 'down' : 'up'}
          sub="vs prev 7 days"
        />
        <StatTile
          label="Win rate"
          value={`${overview.win_rate}%`}
          delta={
            win_rate_delta != null
              ? `${win_rate_delta >= 0 ? '+' : ''}${win_rate_delta}pp`
              : undefined
          }
          deltaKind={win_rate_delta != null && win_rate_delta < 0 ? 'down' : 'up'}
          sub="vs prev 7 days"
        />
        <StatTile
          label="Bets"
          value={overview.total_bets}
          sub={`${overview.won_bets}W · ${overview.lost_bets}L · ${pending}P`}
        />
        <StatTile
          label="Wagered"
          value={fmtMoney(overview.total_wagered)}
          sub={`${overview.roi}% ROI`}
        />
      </div>

      <MyBetsPnLChart
        data={chartData}
        periodLabel={chartPeriodText}
        dayCount={chartDayCount}
      />

      <div className="my-bets-breakdown-grid">
        <div className="card">
          <div className="section-title" style={{ marginBottom: 12 }}>
            By sport
          </div>
          <BreakdownBars items={sportItems} />
        </div>
        <div className="card">
          <div className="section-title" style={{ marginBottom: 12 }}>
            By bet type
          </div>
          <BreakdownBars items={typeItems} />
        </div>
      </div>
    </>
  );
}
