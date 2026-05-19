'use client';

import { useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Layout from '@/components/Layout';
import PageHeader from '@/components/yetai/PageHeader';
import AppLoading from '@/components/yetai/AppLoading';
import { Check } from 'lucide-react';
import { getApiUrl } from '@/lib/api-config';

function SuccessContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionId = searchParams.get('session_id');

  useEffect(() => {
    const updateSubscription = async () => {
      if (!sessionId) return;
      try {
        const response = await fetch(
          getApiUrl(`/api/subscription/session-status/${sessionId}`),
          {
            headers: { Authorization: `Bearer ${localStorage.getItem('auth_token')}` },
          },
        );
        const data = await response.json();
        if (data.status === 'complete') {
          const userResponse = await fetch(getApiUrl('/api/auth/me'), {
            headers: { Authorization: `Bearer ${localStorage.getItem('auth_token')}` },
          });
          if (userResponse.ok) {
            const userData = await userResponse.json();
            if (userData.status === 'success' && userData.user) {
              localStorage.setItem('user_data', JSON.stringify(userData.user));
              window.dispatchEvent(new Event('storage'));
            }
          }
        }
      } catch (error) {
        console.error('Error updating subscription:', error);
      }
    };
    updateSubscription();
    const timer = setTimeout(() => router.push('/dashboard'), 3000);
    return () => clearTimeout(timer);
  }, [router, sessionId]);

  return (
    <section className="card" style={{ maxWidth: 440, margin: '48px auto', padding: 40, textAlign: 'center' }}>
      <div
        style={{
          width: 72,
          height: 72,
          borderRadius: '50%',
          background: 'var(--win-soft)',
          display: 'grid',
          placeItems: 'center',
          margin: '0 auto 20px',
        }}
      >
        <Check size={36} style={{ color: 'var(--win)' }} />
      </div>
      <h1 className="type-page-title" style={{ fontSize: 24, marginBottom: 8 }}>
        Welcome to Pro
      </h1>
      <p className="dim" style={{ marginBottom: 24 }}>
        Your upgrade was successful. You now have access to all Pro features.
      </p>
      {sessionId ? (
        <p className="mono dim" style={{ fontSize: 11, marginBottom: 20 }}>
          Session: {sessionId.substring(0, 20)}…
        </p>
      ) : null}
      <button type="button" className="btn btn-primary" onClick={() => router.push('/dashboard')}>
        Go to Dashboard
      </button>
      <p className="dim" style={{ fontSize: 12, marginTop: 16 }}>
        Redirecting automatically in 3 seconds…
      </p>
    </section>
  );
}

export default function UpgradeSuccessPage() {
  return (
    <Layout requiresAuth fullWidth>
      <PageHeader title="Subscription" subtitle="Payment confirmed" />
      <Suspense fallback={<AppLoading label="Confirming subscription…" />}>
        <SuccessContent />
      </Suspense>
    </Layout>
  );
}
