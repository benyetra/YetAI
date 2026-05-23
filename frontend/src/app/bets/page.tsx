'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { BarChart3, Calendar, Clock } from 'lucide-react';
import { useAuth } from '@/components/Auth';
import BetHistory from '@/components/BetHistory';
import UserBetPerformance from '@/components/UserBetPerformance';
import Layout from '@/components/Layout';
import AppLoading from '@/components/yetai/AppLoading';
import PageHeader from '@/components/yetai/PageHeader';

type BetsTab = 'history' | 'performance';

function BetsPageContent() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [selectedPeriod, setSelectedPeriod] = useState(30);

  const activeTab: BetsTab = useMemo(() => {
    const tab = searchParams.get('tab');
    return tab === 'performance' ? 'performance' : 'history';
  }, [searchParams]);

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

  const setTab = (tab: BetsTab) => {
    const params = new URLSearchParams(searchParams.toString());
    if (tab === 'history') {
      params.delete('tab');
    } else {
      params.set('tab', tab);
    }
    const query = params.toString();
    router.replace(query ? `/bets?${query}` : '/bets');
  };

  if (loading) {
    return (
      <Layout>
        <AppLoading />
      </Layout>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <Layout requiresAuth fullWidth>
      <div data-screen-label="My Bets">
        <PageHeader
          title="My bets"
          subtitle="Performance analytics and bet history in one place"
          actions={
            activeTab === 'performance' ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Calendar size={14} style={{ color: 'var(--text-3)' }} />
                <select
                  className="select"
                  value={selectedPeriod}
                  onChange={(e) => setSelectedPeriod(Number(e.target.value))}
                  aria-label="Performance period"
                  style={{ fontFamily: 'var(--mono)', minWidth: 140 }}
                >
                  <option value={7}>Last 7 days</option>
                  <option value={14}>Last 14 days</option>
                  <option value={30}>Last 30 days</option>
                  <option value={90}>Last 3 months</option>
                  <option value={365}>All time</option>
                </select>
              </div>
            ) : undefined
          }
        />

        <div className="tabs" style={{ marginBottom: 16 }} role="tablist" aria-label="Bets views">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'history'}
            className={activeTab === 'history' ? 'active' : ''}
            onClick={() => setTab('history')}
          >
            <Clock size={12} style={{ marginRight: 5, verticalAlign: -2 }} />
            Bet history
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'performance'}
            className={activeTab === 'performance' ? 'active' : ''}
            onClick={() => setTab('performance')}
          >
            <BarChart3 size={12} style={{ marginRight: 5, verticalAlign: -2 }} />
            Performance
          </button>
        </div>

        {activeTab === 'history' ? <BetHistory embedded /> : <UserBetPerformance selectedPeriod={selectedPeriod} />}
      </div>
    </Layout>
  );
}

export default function BetsPage() {
  return (
    <Suspense
      fallback={
        <Layout>
          <AppLoading />
        </Layout>
      }
    >
      <BetsPageContent />
    </Suspense>
  );
}
