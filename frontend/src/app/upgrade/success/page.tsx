'use client';

import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Layout from '@/components/Layout';
import { Check } from 'lucide-react';

export default function UpgradeSuccessPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionId = searchParams.get('session_id');

  useEffect(() => {
    // Redirect to dashboard after 3 seconds
    const timer = setTimeout(() => {
      router.push('/dashboard');
    }, 3000);

    return () => clearTimeout(timer);
  }, [router]);

  return (
    <Layout requiresAuth>
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
    </Layout>
  );
}
