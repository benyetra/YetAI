'use client';

import { useAuth } from '@/components/Auth';
import BetHistory from '@/components/BetHistory';
import Layout from '@/components/Layout';
import AppLoading from '@/components/yetai/AppLoading';
import PageHeader from '@/components/yetai/PageHeader';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

export default function BetsPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

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
      <PageHeader title="Bet History" subtitle="Your wagers, results, and parlays" />
      <BetHistory />
    </Layout>
  );
}