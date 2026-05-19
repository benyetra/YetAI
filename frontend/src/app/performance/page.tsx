'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import AppLoading from '@/components/yetai/AppLoading';
import Layout from '@/components/Layout';

/** Legacy route — merged into /bets */
export default function PerformanceRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/bets?tab=performance');
  }, [router]);

  return (
    <Layout>
      <AppLoading />
    </Layout>
  );
}
