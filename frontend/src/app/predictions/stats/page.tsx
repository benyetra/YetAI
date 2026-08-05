'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import PageHeader from '@/components/yetai/PageHeader';
import { useAuth } from '@/components/Auth';
import {
  fetchAccuracyOverview,
  type AccuracyOverviewItem,
  type AccuracySport,
  type AccuracyTone,
} from '@/lib/api/accuracy';
import { BarChart3, ChevronRight } from 'lucide-react';
import { buildLoginUrl } from '@/lib/auth-redirect';

const SPORTS: Array<{
  sport: AccuracySport;
  href: string;
  emoji: string;
  label: string;
  desc: string;
}> = [
  { sport: 'mlb', href: '/predictions/mlb', emoji: '⚾', label: 'MLB', desc: 'Strikeouts, home runs, and game-level slate projections.' },
  { sport: 'nba', href: '/predictions/nba', emoji: '🏀', label: 'NBA', desc: 'Points, assists, rebounds, threes, steals, blocks, and PRA.' },
  { sport: 'wnba', href: '/predictions/wnba', emoji: '🏀', label: 'WNBA', desc: 'Game totals O/U, spread/win-probability, and player props (points, assists, rebounds).' },
  { sport: 'nfl', href: '/predictions/nfl', emoji: '🏈', label: 'NFL', desc: 'QB passing and kicker field goal projections.' },
  { sport: 'nhl', href: '/predictions/nhl', emoji: '🏒', label: 'NHL', desc: 'Goalie saves and player shots on goal.' },
];

function toneColor(tone: AccuracyTone): string {
  if (tone === 'good') return 'var(--win)';
  if (tone === 'warn') return '#fbbf24';
  return 'var(--text-3)';
}

export default function StatProjectionsHubPage() {
  const { isAuthenticated, loading, token } = useAuth();
  const router = useRouter();
  const [overviewItems, setOverviewItems] = useState<AccuracyOverviewItem[] | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !isAuthenticated) router.push(buildLoginUrl());
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (!isAuthenticated || loading || !token) return;
    let cancelled = false;
    setOverviewLoading(true);
    setOverviewError(null);
    fetchAccuracyOverview('season')
      .then((r) => {
        if (!cancelled) setOverviewItems(r.items);
      })
      .catch((e) => {
        if (!cancelled) {
          setOverviewError(e instanceof Error ? e.message : String(e));
          setOverviewItems(null);
        }
      })
      .finally(() => {
        if (!cancelled) setOverviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, loading, token]);

  const overviewBySport = useMemo(() => {
    const m: Partial<Record<AccuracySport, AccuracyOverviewItem>> = {};
    for (const it of overviewItems ?? []) {
      m[it.sport] = it;
    }
    return m;
  }, [overviewItems]);

  if (!isAuthenticated) return null;

  return (
    <Layout requiresAuth fullWidth>
      <PageHeader
        title="Stat Projections"
        subtitle="ML-powered player and game projections by league."
        actions={<BarChart3 size={20} style={{ color: 'var(--accent)' }} />}
      />
      {overviewLoading && overviewItems === null && !overviewError ? (
        <p className="dim" style={{ fontSize: 12, marginBottom: 12 }}>
          Loading season model summaries…
        </p>
      ) : null}
      {overviewError ? (
        <p className="alert-error" style={{ fontSize: 12, marginBottom: 12, padding: 10, borderRadius: 8 }} role="alert">
          Season summaries could not be loaded. {overviewError}
        </p>
      ) : null}
      <div style={{ display: 'grid', gap: 12 }}>
        {SPORTS.map((s) => {
          const ov = overviewBySport[s.sport];
          const summaryLine =
            ov &&
            (ov.has_data
              ? `Season model: ${ov.primary} · ${ov.secondary}`
              : ov.primary);
          const summaryTitle = ov
            ? ov.has_data
              ? `${s.label} season-to-date: ${ov.primary} across ${ov.graded_count} graded picks.`
              : `${s.label}: ${ov.primary}`
            : undefined;
          const summaryTone = ov?.tone ?? 'neutral';
          return (
            <Link
              key={s.href}
              href={s.href}
              className="card card-hover"
              style={{ padding: 'var(--pad-card)', display: 'flex', alignItems: 'center', gap: 16 }}
            >
              <span style={{ fontSize: 28 }}>{s.emoji}</span>
              <span style={{ flex: 1 }}>
                <div className="type-section-title">{s.label}</div>
                <p className="dim" style={{ fontSize: 12, marginTop: 4 }}>
                  {s.desc}
                </p>
                {summaryLine ? (
                  <p
                    className="dim"
                    style={{
                      fontSize: 11,
                      marginTop: 6,
                      color: toneColor(summaryTone),
                    }}
                    title={summaryTitle}
                  >
                    {summaryLine}
                  </p>
                ) : null}
              </span>
              <ChevronRight size={18} className="dim" />
            </Link>
          );
        })}
      </div>
    </Layout>
  );
}
