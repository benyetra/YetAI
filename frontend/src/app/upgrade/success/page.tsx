'use client';

import { useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Layout from '@/components/Layout';
import { Check } from 'lucide-react';

function SuccessContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionId = searchParams.get('session_id');

  useEffect(() => {
    // Update subscription status on backend and refresh user data
    const updateSubscription = async () => {
      if (!sessionId) return;

      try {
        // Step 1: Update subscription in backend
        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/api/subscription/session-status/${sessionId}`,
          {
            headers: {
              'Authorization': `Bearer ${localStorage.getItem('auth_token')}`,
            },
          }
        );

        const data = await response.json();
        console.log('Subscription update response:', data);

        if (data.status === 'complete') {
          console.log('Subscription activated successfully!');

          // Step 2: Fetch fresh user data from backend
          const userResponse = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/auth/me`,
            {
              headers: {
                'Authorization': `Bearer ${localStorage.getItem('auth_token')}`,
              },
            }
          );

          if (userResponse.ok) {
            const userData = await userResponse.json();
            console.log('Fresh user data:', userData);

            if (userData.status === 'success' && userData.user) {
              // Update localStorage with fresh user data
              localStorage.setItem('user_data', JSON.stringify(userData.user));
              console.log('Updated user data in localStorage');

              // Trigger a storage event to update Auth context
              window.dispatchEvent(new Event('storage'));
            }
          }
        }
      } catch (error) {
        console.error('Error updating subscription:', error);
      }
    };

    updateSubscription();

    // Redirect to dashboard after 3 seconds
    const timer = setTimeout(() => {
      router.push('/dashboard');
    }, 3000);

    return () => clearTimeout(timer);
  }, [router, sessionId]);

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="max-w-md w-full text-center">
        <div className="bg-green-100 rounded-full w-20 h-20 flex items-center justify-center mx-auto mb-6">
          <Check className="w-12 h-12 text-green-600" />
        </div>

        <h1 className="text-3xl font-bold text-gray-900 mb-4">
          Welcome to Pro!
        </h1>

        <p className="text-gray-600 mb-8">
          Your upgrade was successful. You now have access to all Pro features.
        </p>

        {sessionId && (
          <p className="text-sm text-gray-500 mb-6">
            Session ID: {sessionId.substring(0, 20)}...
          </p>
        )}

        <button
          onClick={() => router.push('/dashboard')}
          className="bg-gradient-to-r from-purple-600 to-blue-600 text-white px-8 py-3 rounded-lg font-medium hover:from-purple-700 hover:to-blue-700 transition-colors"
        >
          Go to Dashboard
        </button>

        <p className="text-sm text-gray-500 mt-4">
          Redirecting automatically in 3 seconds...
        </p>
      </div>
    </div>
  );
}

export default function UpgradeSuccessPage() {
  return (
    <Layout requiresAuth>
      <Suspense fallback={
        <div className="min-h-[60vh] flex items-center justify-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
      }>
        <SuccessContent />
      </Suspense>
    </Layout>
  );
}
