'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { Crown } from 'lucide-react';
import {
  PredictionsTable,
  PredictionsPaywall,
  PredictionsError,
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';
import { usePredictions } from '@/lib/usePredictions';

const QB_COLUMNS: ColumnDef[] = [
  { key: 'qb_player_name', label: 'QB', format: (v) => formatString(v) },
  { key: 'opponent_team_name', label: 'Opp', format: (v) => formatString(v) },
  { key: 'predicted_passing_yards', label: 'Pass Yds', align: 'right', format: (v) => formatNumber(v, 0) },
  { key: 'predicted_completions', label: 'Comp', align: 'right', format: (v) => formatNumber(v, 1) },
  { key: 'predicted_touchdowns', label: 'TD', align: 'right', format: (v) => formatNumber(v, 1) },
  { key: 'betting_recommendation', label: 'Pick', format: (v) => formatString(v) },
];

const KICKER_COLUMNS: ColumnDef[] = [
  { key: 'kicker_player_name', label: 'Kicker', format: (v) => formatString(v) },
  { key: 'opponent_team_name', label: 'Opp', format: (v) => formatString(v) },
  { key: 'predicted_fg_attempts', label: 'FGA', align: 'right', format: (v) => formatNumber(v, 1) },
  { key: 'predicted_fg_made', label: 'FGM', align: 'right', format: (v) => formatNumber(v, 1) },
  { key: 'predicted_success_rate', label: 'Hit %', align: 'right', format: (v) => formatNumber(v, 1) },
];

export default function NFLPredictionsPage() {
  const { isAuthenticated, loading: authLoading } = useAuth();
  const router = useRouter();
  const [date, setDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const { data, loading, error, paywalled } = usePredictions('nfl', date, { enabled: isAuthenticated });

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [authLoading, isAuthenticated, router]);

  if (!isAuthenticated) return null;

  return (
    <Layout>
      <div className="space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
              <span>🏈 NFL Predictions</span>
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-purple-100 text-purple-800">
                <Crown className="w-3 h-3" /> PRO
              </span>
            </h1>
            <p className="text-gray-600 mt-1">Quarterback passing projections and kicker field goal predictions.</p>
          </div>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
        </header>

        {paywalled ? (
          <PredictionsPaywall onUpgrade={() => router.push('/upgrade')} />
        ) : error ? (
          <PredictionsError message={error} />
        ) : (
          <div className="space-y-6">
            <PredictionsTable
              title="Quarterback Predictions"
              rows={data?.qb_predictions ?? []}
              columns={QB_COLUMNS}
              loading={loading}
            />
            <PredictionsTable
              title="Kicker Predictions"
              rows={data?.kicker_predictions ?? []}
              columns={KICKER_COLUMNS}
              loading={loading}
            />
          </div>
        )}
      </div>
    </Layout>
  );
}
