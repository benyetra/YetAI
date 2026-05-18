'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import PageHeader from '@/components/yetai/PageHeader';
import { LeagueChip } from '@/components/yetai/primitives';
import {
  PredictionsTable,
  PredictionsPaywall,
  PredictionsError,
  type ColumnDef,
} from '@/components/PredictionsTable';
import { usePredictions, type PredictionSport } from '@/lib/usePredictions';
import { Crown } from 'lucide-react';

export type PropGroup = {
  title: string;
  responseKey: string;
  columns: ColumnDef[];
};

export default function SportPredictionsPage({
  sport,
  leagueLabel,
  emoji,
  subtitle,
  groups,
}: {
  sport: PredictionSport;
  leagueLabel: string;
  emoji: string;
  subtitle: string;
  groups: PropGroup[];
}) {
  const { isAuthenticated, loading: authLoading } = useAuth();
  const router = useRouter();
  const [date, setDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const { data, loading, error, paywalled } = usePredictions(sport, date, { enabled: isAuthenticated });

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [authLoading, isAuthenticated, router]);

  if (!isAuthenticated) return null;

  const dateControl = (
    <input
      type="date"
      className="input"
      value={date}
      onChange={(e) => setDate(e.target.value)}
      style={{ width: 'auto' }}
    />
  );

  return (
    <Layout requiresAuth fullWidth>
      <PageHeader
        title={`${emoji} ${leagueLabel} Predictions`}
        subtitle={subtitle}
        actions={
          <>
            <span className="badge badge-gold" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Crown size={12} /> PRO
            </span>
            <LeagueChip league={leagueLabel} />
            {dateControl}
          </>
        }
      />

      {paywalled ? (
        <PredictionsPaywall onUpgrade={() => router.push('/upgrade')} />
      ) : error ? (
        <PredictionsError message={error} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {groups.map((g) => (
            <PredictionsTable
              key={g.responseKey}
              title={g.title}
              rows={(data?.[g.responseKey] as Array<Record<string, unknown>>) ?? []}
              columns={g.columns}
              loading={loading}
            />
          ))}
        </div>
      )}
    </Layout>
  );
}
