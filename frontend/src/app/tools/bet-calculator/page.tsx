'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import PageHeader from '@/components/yetai/PageHeader';
import BetCalculatorPanel from '@/components/yetai/BetCalculatorPanel';
import { useAuth } from '@/components/Auth';

export default function BetCalculatorPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !isAuthenticated) router.push('/?login=true');
  }, [isAuthenticated, loading, router]);

  if (!isAuthenticated) return null;

  return (
    <Layout requiresAuth fullWidth>
      <PageHeader
        title="Bet calculator"
        subtitle="Payout, implied probability, and multi-leg parlay math"
      />
      <BetCalculatorPanel />
    </Layout>
  );
}
