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
import { countTopPlays, isTopPlay } from '@/lib/propProjectionDisplay';
import { Crown, Sparkles } from 'lucide-react';

export type PropGroup = {
  title: string;
  responseKey: string;
  columns: ColumnDef[];
  rowClassName?: (row: Record<string, unknown>) => string | undefined;
};

export type GroupsContext = {
  date: string;
  isPastDate: boolean;
};

export type GroupsProp = PropGroup[] | ((ctx: GroupsContext) => PropGroup[]);

function todayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

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
  accuracySummary,
}: {
  sport: PredictionSport;
  leagueLabel: string;
  emoji: string;
  subtitle: string;
  groups: GroupsProp;
  topSection?: (ctx: {
    data: Record<string, Array<Record<string, unknown>>> | null;
    loading: boolean;
    isPastDate: boolean;
  }) => ReactNode;
  accuracySummary?: (ctx: GroupsContext) => ReactNode;
}) {
  const { isAuthenticated, loading: authLoading } = useAuth();
  const router = useRouter();
  const [date, setDate] = useState<string>(todayIso);
  const { data, loading, error, paywalled } = usePredictions(sport, date, { enabled: isAuthenticated });

  const isPastDate = useMemo(() => date < todayIso(), [date]);
  const resolvedGroups = useMemo<PropGroup[]>(
    () => (typeof groups === 'function' ? groups({ date, isPastDate }) : groups),
    [groups, date, isPastDate]
  );

  const storageKey = `yetai-predictions-expanded:${sport}`;
  const topPlaysStorageKey = `yetai-predictions-top-plays:${sport}`;
  const [topPlaysOnly, setTopPlaysOnly] = useState(() => {
    if (typeof window === 'undefined') return false;
    try {
      return window.localStorage.getItem(topPlaysStorageKey) === '1';
    } catch {
      return false;
    }
  });
  const [expandedByKey, setExpandedByKey] = useState<Record<string, boolean>>(() => {
    const defaults = expandedMap(resolvedGroups, true);
    if (typeof window === 'undefined') return defaults;
    try {
      const raw = window.localStorage.getItem(`yetai-predictions-expanded:${sport}`);
      if (!raw) return defaults;
      const parsed = JSON.parse(raw) as Record<string, boolean>;
      for (const g of resolvedGroups) {
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
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(topPlaysStorageKey, topPlaysOnly ? '1' : '0');
    } catch {
      /* ignore quota errors */
    }
  }, [topPlaysOnly, topPlaysStorageKey]);

  useEffect(() => {
    setExpandedByKey((prev) => {
      const next = { ...prev };
      for (const g of resolvedGroups) {
        if (!(g.responseKey in next)) next[g.responseKey] = true;
      }
      return next;
    });
  }, [resolvedGroups]);

  const setAllExpanded = useCallback((value: boolean) => {
    setExpandedByKey(expandedMap(resolvedGroups, value));
  }, [resolvedGroups]);

  const allExpanded = useMemo(
    () => resolvedGroups.every((g) => expandedByKey[g.responseKey] !== false),
    [resolvedGroups, expandedByKey]
  );
  const allCollapsed = useMemo(
    () => resolvedGroups.every((g) => expandedByKey[g.responseKey] === false),
    [resolvedGroups, expandedByKey]
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

  const hasTopPlayGroups = useMemo(
    () => resolvedGroups.some((g) => g.rowClassName != null),
    [resolvedGroups]
  );

  const topPlayCount = useMemo(() => {
    if (!data || !hasTopPlayGroups) return 0;
    return resolvedGroups.reduce((sum, g) => {
      if (!g.rowClassName) return sum;
      const rows = (data[g.responseKey] as Array<Record<string, unknown>>) ?? [];
      return sum + countTopPlays(rows);
    }, 0);
  }, [data, hasTopPlayGroups, resolvedGroups]);

  const showPropToolbar = resolvedGroups.length > 1 || hasTopPlayGroups;

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
          {topSection ? topSection({ data, loading, isPastDate }) : null}

          {accuracySummary && isPastDate
            ? accuracySummary({ date, isPastDate })
            : null}

          {showPropToolbar && (
            <div className="predictions-toolbar card" role="toolbar" aria-label="Prop table filters">
              <div className="predictions-toolbar-actions">
                {hasTopPlayGroups && (
                  <button
                    type="button"
                    className={`predictions-chip predictions-chip-featured ${topPlaysOnly ? 'is-active' : ''}`}
                    aria-pressed={topPlaysOnly}
                    onClick={() => setTopPlaysOnly((prev) => !prev)}
                    disabled={loading}
                  >
                    <Sparkles size={13} aria-hidden />
                    Top plays only
                    {!loading && topPlayCount > 0 ? (
                      <span className="predictions-chip-count">{topPlayCount}</span>
                    ) : null}
                  </button>
                )}
                {resolvedGroups.length > 1 && (
                  <>
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
                  </>
                )}
              </div>
              {resolvedGroups.length > 1 && (
                <div className="predictions-toolbar-chips">
                  {resolvedGroups.map((g) => {
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
              )}
            </div>
          )}

          {topPlaysOnly && !loading && topPlayCount === 0 && hasTopPlayGroups ? (
            <div className="card" style={{ padding: '16px 20px' }}>
              <p className="dim" style={{ margin: 0, fontSize: 13 }}>
                No top plays for this date. Try another slate or turn off the filter.
              </p>
            </div>
          ) : null}

          {resolvedGroups.map((g) => {
            const allRows = (data?.[g.responseKey] as Array<Record<string, unknown>>) ?? [];
            const rows =
              topPlaysOnly && g.rowClassName ? allRows.filter(isTopPlay) : allRows;
            if (topPlaysOnly && g.rowClassName && rows.length === 0) {
              return null;
            }
            return (
              <PredictionsTable
                key={g.responseKey}
                title={g.title}
                rows={rows}
                columns={g.columns}
                loading={loading}
                expanded={expandedByKey[g.responseKey] !== false}
                onExpandedChange={(next) =>
                  setExpandedByKey((prev) => ({ ...prev, [g.responseKey]: next }))
                }
                rowClassName={g.rowClassName}
                emptyMessage={
                  topPlaysOnly && g.rowClassName
                    ? 'No top plays in this category for this date.'
                    : undefined
                }
              />
            );
          })}
        </div>
      )}
    </Layout>
  );
}
