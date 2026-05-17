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

const STRIKEOUT_COLUMNS: ColumnDef[] = [
  { key: 'pitcher_name', label: 'Pitcher', format: (v) => formatString(v) },
  { key: 'projected_strikeouts', label: 'Proj K', align: 'right', format: (v) => formatNumber(v, 1) },
  { key: 'projected_innings_pitched', label: 'Proj IP', align: 'right', format: (v) => formatNumber(v, 1) },
  { key: 'fanduel_line', label: 'FD Line', align: 'right', format: (v) => formatNumber(v, 1) },
  { key: 'fanduel_over_under', label: 'FD O/U', format: (v) => formatString(v) },
];

const HR_COLUMNS: ColumnDef[] = [
  { key: 'player_name', label: 'Hitter', format: (v) => formatString(v) },
  { key: 'team', label: 'Team', format: (v) => formatString(v) },
  { key: 'opponent', label: 'Opp', format: (v) => formatString(v) },
  { key: 'opponent_pitcher', label: 'vs Pitcher', format: (v) => formatString(v) },
  { key: 'venue_name', label: 'Venue', format: (v) => formatString(v) },
];

export default function MLBPredictionsPage() {
  const { isAuthenticated, loading: authLoading } = useAuth();
  const router = useRouter();
  const [date, setDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const { data, loading, error, paywalled } = usePredictions('mlb', date, { enabled: isAuthenticated });

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
              <span>⚾ MLB Predictions</span>
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-purple-100 text-purple-800">
                <Crown className="w-3 h-3" /> PRO
              </span>
            </h1>
            <p className="text-gray-600 mt-1">Pitcher strikeout projections & home run picks.</p>
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
              title="Pitcher Strikeout Projections"
              rows={data?.strikeout_projections ?? []}
              columns={STRIKEOUT_COLUMNS}
              loading={loading}
            />
            <PredictionsTable
              title="Home Run Predictions"
              rows={data?.home_run_predictions ?? []}
              columns={HR_COLUMNS}
              loading={loading}
            />
          </div>
        )}
      </div>
    </Layout>
  );
}

