'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { BarChart3, Calendar, History } from 'lucide-react';
import { useAuth } from '@/components/Auth';
import BetHistory from '@/components/BetHistory';
import UserBetPerformance from '@/components/UserBetPerformance';
import Layout from '@/components/Layout';
import AppLoading from '@/components/yetai/AppLoading';
import PageHeader from '@/components/yetai/PageHeader';

type BetsTab = 'history' | 'performance';

function TabButton({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ElementType;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
        active
          ? 'bg-white text-gray-900 shadow-sm border border-gray-200'
          : 'text-gray-600 hover:text-gray-900'
      }`}
    >
      <Icon size={16} />
      {label}
    </button>
  );
}

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
      <PageHeader
        title="My Bets"
        subtitle="Performance analytics and bet history in one place"
        actions={
          activeTab === 'performance' ? (
            <div className="flex items-center space-x-2">
              <Calendar className="w-4 h-4 text-gray-500" />
              <select
                value={selectedPeriod}
                onChange={(e) => setSelectedPeriod(Number(e.target.value))}
                className="px-3 py-1 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white"
                aria-label="Performance period"
              >
                <option value={7}>Last 7 days</option>
                <option value={30}>Last 30 days</option>
                <option value={90}>Last 3 months</option>
                <option value={365}>All time</option>
              </select>
            </div>
          ) : undefined
        }
      />

      <div
        className="flex gap-1 p-1 rounded-lg border border-gray-200 bg-gray-50 w-fit mb-6"
        role="tablist"
        aria-label="Bets views"
      >
        <TabButton
          active={activeTab === 'history'}
          onClick={() => setTab('history')}
          icon={History}
          label="Bet History"
        />
        <TabButton
          active={activeTab === 'performance'}
          onClick={() => setTab('performance')}
          icon={BarChart3}
          label="Performance"
        />
      </div>

      {activeTab === 'history' ? (
        <BetHistory embedded />
      ) : (
        <UserBetPerformance selectedPeriod={selectedPeriod} />
      )}
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
