'use client';

import { useAuth } from '@/components/Auth';
import BetHistory from '@/components/BetHistory';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

export default function BetsPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/');
    }
  }, [isAuthenticated, loading, router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-lg">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null; // Will redirect in useEffect
  }

  return <BetHistory />;
}