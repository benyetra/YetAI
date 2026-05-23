'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import PageHeader from '@/components/yetai/PageHeader';
import OwensBettingCornerView from '@/components/yetai/OwensBettingCornerView';
import { useAuth } from '@/components/Auth';

export default function OwensBettingCornerPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !isAuthenticated) router.push('/?login=true');
  }, [isAuthenticated, loading, router]);

  if (!isAuthenticated) return null;

  return (
    <Layout requiresAuth fullWidth>
      <PageHeader
        eyebrow="Hand-picked picks"
        title="Owen's Corner"
        subtitle="Pending picks and historical results · success rate and units won"
      />
      <OwensBettingCornerView />
    </Layout>
  );
}
