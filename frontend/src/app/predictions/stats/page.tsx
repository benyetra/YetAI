'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import PageHeader from '@/components/yetai/PageHeader';
import { useAuth } from '@/components/Auth';
import { BarChart3, ChevronRight } from 'lucide-react';

const SPORTS = [
  { href: '/predictions/mlb', emoji: '⚾', label: 'MLB', desc: 'Strikeouts, home runs, and game-level slate projections.' },
  { href: '/predictions/nba', emoji: '🏀', label: 'NBA', desc: 'Points, assists, rebounds, threes, steals, blocks, and PRA.' },
  { href: '/predictions/nfl', emoji: '🏈', label: 'NFL', desc: 'QB passing and kicker field goal projections.' },
  { href: '/predictions/nhl', emoji: '🏒', label: 'NHL', desc: 'Goalie saves and player shots on goal.' },
];

export default function StatProjectionsHubPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !isAuthenticated) router.push('/?login=true');
  }, [isAuthenticated, loading, router]);

  if (!isAuthenticated) return null;

  return (
    <Layout requiresAuth fullWidth>
      <PageHeader
        title="Stat Projections"
        subtitle="ML-powered player and game projections by league."
        actions={<BarChart3 size={20} style={{ color: 'var(--accent)' }} />}
      />
      <div style={{ display: 'grid', gap: 12 }}>
        {SPORTS.map((s) => (
          <Link key={s.href} href={s.href} className="card card-hover" style={{ padding: 'var(--pad-card)', display: 'flex', alignItems: 'center', gap: 16 }}>
            <span style={{ fontSize: 28 }}>{s.emoji}</span>
            <span style={{ flex: 1 }}>
              <div className="type-section-title">{s.label}</div>
              <p className="dim" style={{ fontSize: 12, marginTop: 4 }}>{s.desc}</p>
            </span>
            <ChevronRight size={18} className="dim" />
          </Link>
        ))}
      </div>
    </Layout>
  );
}
