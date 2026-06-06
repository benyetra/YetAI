'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import OwensCornerHero from '@/components/yetai/OwensCornerHero';
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
      <OwensCornerHero />
      <OwensBettingCornerView />
    </Layout>
  );
}
