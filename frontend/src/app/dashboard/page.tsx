'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Dashboard from '@/components/Dashboard';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';

export default function DashboardPage() {
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
        <div className="min-h-screen flex items-center justify-center">
          <div
            className="animate-spin rounded-full h-12 w-12 border-2 border-transparent"
            style={{ borderBottomColor: 'var(--accent)' }}
          />
        </div>
      </Layout>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <Layout requiresAuth fullWidth>
      <Dashboard />
    </Layout>
  );
}