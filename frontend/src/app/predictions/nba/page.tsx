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

function propColumns(propKey: string, propLabel: string): ColumnDef[] {
  return [
    { key: 'player_name', label: 'Player', format: (v) => formatString(v) },
    { key: 'opponent_team_name', label: 'Opp', format: (v) => formatString(v) },
    { key: propKey, label: propLabel, align: 'right', format: (v) => formatNumber(v, 1) },
    { key: 'fanduel_line', label: 'FD Line', align: 'right', format: (v) => formatNumber(v, 1) },
    { key: 'fanduel_over_under', label: 'FD O/U', format: (v) => formatString(v) },
  ];
}

const PROP_GROUPS: Array<{
  title: string;
  responseKey: string;
  columns: ColumnDef[];
}> = [
  { title: 'Points', responseKey: 'points', columns: propColumns('projected_points', 'Proj Pts') },
  { title: 'Assists', responseKey: 'assists', columns: propColumns('projected_assists', 'Proj Ast') },
  { title: 'Rebounds', responseKey: 'rebounds', columns: propColumns('projected_rebounds', 'Proj Reb') },
  { title: 'Three-Pointers', responseKey: 'three_point', columns: propColumns('projected_three_pt_made', 'Proj 3PM') },
  { title: 'Steals', responseKey: 'steals', columns: propColumns('projected_steals', 'Proj Stl') },
  { title: 'Blocks', responseKey: 'blocks', columns: propColumns('projected_blocks', 'Proj Blk') },
  { title: 'PRA (Pts + Reb + Ast)', responseKey: 'pra', columns: propColumns('projected_pra', 'Proj PRA') },
];

export default function NBAPredictionsPage() {
  const { isAuthenticated, loading: authLoading } = useAuth();
  const router = useRouter();
  const [date, setDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const { data, loading, error, paywalled } = usePredictions('nba', date, { enabled: isAuthenticated });

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
              <span>🏀 NBA Predictions</span>
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-purple-100 text-purple-800">
                <Crown className="w-3 h-3" /> PRO
              </span>
            </h1>
            <p className="text-gray-600 mt-1">Points, assists, rebounds, threes, steals, blocks, and PRA projections.</p>
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
            {PROP_GROUPS.map((g) => (
              <PredictionsTable
                key={g.responseKey}
                title={g.title}
                rows={data?.[g.responseKey] ?? []}
                columns={g.columns}
                loading={loading}
              />
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
