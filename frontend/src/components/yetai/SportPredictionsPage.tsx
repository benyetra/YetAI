'use client';

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
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

function expandedMap(groups: PropGroup[], value: boolean): Record<string, boolean> {
  return Object.fromEntries(groups.map((g) => [g.responseKey, value]));
}

export default function SportPredictionsPage({
  sport,
  leagueLabel,
  emoji,
  subtitle,
  groups,
  topSection,
}: {
  sport: PredictionSport;
  leagueLabel: string;
  emoji: string;
  subtitle: string;
  groups: PropGroup[];
  topSection?: (ctx: {
    data: Record<string, Array<Record<string, unknown>>> | null;
    loading: boolean;
  }) => ReactNode;
}) {
  const { isAuthenticated, loading: authLoading } = useAuth();
  const router = useRouter();
  const [date, setDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const { data, loading, error, paywalled } = usePredictions(sport, date, { enabled: isAuthenticated });

  const storageKey = `yetai-predictions-expanded:${sport}`;
  const [expandedByKey, setExpandedByKey] = useState<Record<string, boolean>>(() => {
    const defaults = expandedMap(groups, true);
    if (typeof window === 'undefined') return defaults;
    try {
      const raw = window.localStorage.getItem(`yetai-predictions-expanded:${sport}`);
      if (!raw) return defaults;
      const parsed = JSON.parse(raw) as Record<string, boolean>;
      for (const g of groups) {
        if (typeof parsed[g.responseKey] === 'boolean') {
          defaults[g.responseKey] = parsed[g.responseKey];
        }
      }
    } catch {
      /* ignore corrupt storage */
    }
    return defaults;
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(expandedByKey));
    } catch {
      /* ignore quota errors */
    }
  }, [expandedByKey, storageKey]);

  useEffect(() => {
    setExpandedByKey((prev) => {
      const next = { ...prev };
      for (const g of groups) {
        if (!(g.responseKey in next)) next[g.responseKey] = true;
      }
      return next;
    });
  }, [groups]);

  const setAllExpanded = useCallback((value: boolean) => {
    setExpandedByKey(expandedMap(groups, value));
  }, [groups]);

  const allExpanded = useMemo(
    () => groups.every((g) => expandedByKey[g.responseKey] !== false),
    [groups, expandedByKey]
  );
  const allCollapsed = useMemo(
    () => groups.every((g) => expandedByKey[g.responseKey] === false),
    [groups, expandedByKey]
  );

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

  const showPropToolbar = groups.length > 1;

  return (
    <Layout requiresAuth fullWidth>
      <PageHeader
        title={`${emoji} ${leagueLabel} Stat Projections`}
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
        <div className="predictions-stack">
          {topSection ? topSection({ data, loading }) : null}

          {showPropToolbar && (
            <div className="predictions-toolbar card" role="toolbar" aria-label="Prop table visibility">
              <div className="predictions-toolbar-actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setAllExpanded(true)}
                  disabled={allExpanded}
                >
                  Show all
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setAllExpanded(false)}
                  disabled={allCollapsed}
                >
                  Hide all
                </button>
              </div>
              <div className="predictions-toolbar-chips">
                {groups.map((g) => {
                  const isOpen = expandedByKey[g.responseKey] !== false;
                  return (
                    <button
                      key={g.responseKey}
                      type="button"
                      className={`predictions-chip ${isOpen ? 'is-active' : ''}`}
                      aria-pressed={isOpen}
                      onClick={() =>
                        setExpandedByKey((prev) => ({
                          ...prev,
                          [g.responseKey]: !isOpen,
                        }))
                      }
                    >
                      {g.title}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {groups.map((g) => (
            <PredictionsTable
              key={g.responseKey}
              title={g.title}
              rows={(data?.[g.responseKey] as Array<Record<string, unknown>>) ?? []}
              columns={g.columns}
              loading={loading}
              expanded={expandedByKey[g.responseKey] !== false}
              onExpandedChange={(next) =>
                setExpandedByKey((prev) => ({ ...prev, [g.responseKey]: next }))
              }
            />
          ))}
        </div>
      )}
    </Layout>
  );
}
