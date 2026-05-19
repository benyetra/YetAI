'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import PageHeader from '@/components/yetai/PageHeader';
import BetCalculatorPanel from '@/components/yetai/BetCalculatorPanel';
import { useAuth } from '@/components/Auth';
import { Calculator } from 'lucide-react';

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
        title="Bet Calculator"
        subtitle="Single-bet payout, implied probability, and multi-leg parlay math."
        actions={<Calculator size={20} style={{ color: 'var(--accent)' }} />}
      />
      <BetCalculatorPanel />
    </Layout>
  );
}
