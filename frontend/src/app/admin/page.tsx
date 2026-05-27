'use client';

import { useEffect, useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import AppLoading from '@/components/yetai/AppLoading';
import PageHeader from '@/components/yetai/PageHeader';
import { useAuth } from '@/components/Auth';
import {
  Users,
  Target,
  Workflow,
  Brain,
  ClipboardList,
  Clock,
} from 'lucide-react';

export default function AdminPage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();

  const [showVerificationPanel, setShowVerificationPanel] = useState(false);
  const [verificationStats, setVerificationStats] = useState<any>(null);
  const [isVerifying, setIsVerifying] = useState(false);
  const [message, setMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);

  useEffect(() => {
    if (!loading && (!isAuthenticated || !user?.is_admin)) {
      router.push('/dashboard');
    }
  }, [isAuthenticated, loading, user, router]);

  useEffect(() => {
    if (showVerificationPanel && !verificationStats) {
      const fetchVerificationStats = async () => {
        try {
          const token = localStorage.getItem('auth_token');
          const response = await fetch(
            getApiUrl('/api/admin/bets/verification/stats'),
            {
              method: 'GET',
              headers: {
                Authorization: `Bearer ${token}`,
                'Content-Type': 'application/json',
              },
            }
          );

          if (response.ok) {
            const data = await response.json();
            setVerificationStats(data.data || data);
          } else {
            setMessage({ type: 'error', text: 'Failed to fetch verification stats' });
          }
        } catch (error) {
          console.error('Error fetching verification stats:', error);
          setMessage({ type: 'error', text: 'Failed to fetch verification stats' });
        }
      };
      fetchVerificationStats();
    }
  }, [showVerificationPanel, verificationStats]);

  const fetchVerificationStats = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(getApiUrl('/api/admin/bets/verification/stats'), {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setVerificationStats(data.data || data);
      } else {
        setMessage({ type: 'error', text: 'Failed to fetch verification stats' });
      }
    } catch (error) {
      console.error('Error fetching verification stats:', error);
      setMessage({ type: 'error', text: 'Failed to fetch verification stats' });
    }
  };

  const triggerVerificationInternal = async (retryCount = 0) => {
    setIsVerifying(true);
    const maxRetries = 2;

    try {
      const token = localStorage.getItem('auth_token');

      if (retryCount > 0) {
        await new Promise((resolve) => setTimeout(resolve, 1000 * retryCount));
      }

      const response = await fetch(getApiUrl('/api/admin/bets/verify'), {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({}),
      });

      if (response.ok) {
        const data = await response.json();
        setMessage({
          type: 'success',
          text: `Verification completed: ${data.result?.message || 'Success'}`,
        });
        setVerificationStats(null);
      } else if (response.status >= 500 && retryCount < maxRetries) {
        return triggerVerificationInternal(retryCount + 1);
      } else {
        let errorText = `HTTP ${response.status}: ${response.statusText}`;
        try {
          const errorData = await response.json();
          errorText = `${errorText} - ${errorData.detail || 'Unknown error'}`;
        } catch {
          errorText = `${errorText} - Unable to parse error response`;
        }
        setMessage({ type: 'error', text: `Verification failed: ${errorText}` });
      }
    } catch (error) {
      if (
        retryCount < maxRetries &&
        (error instanceof TypeError ||
          (error instanceof Error && error.message.includes('Failed to fetch')))
      ) {
        return triggerVerificationInternal(retryCount + 1);
      }
      const errorMsg =
        error instanceof Error ? error.message : 'Network or connection error';
      setMessage({
        type: 'error',
        text: `Failed to trigger bet verification: ${errorMsg}. Check console for details.`,
      });
    } finally {
      if (retryCount === 0) {
        setIsVerifying(false);
      }
    }
  };

  const triggerVerification = () => {
    triggerVerificationInternal();
  };

  if (loading) {
    return (
      <Layout requiresAuth fullWidth>
        <AppLoading label="Loading admin…" />
      </Layout>
    );
  }

  if (!isAuthenticated || !user?.is_admin) {
    return null;
  }

  return (
    <Layout requiresAuth fullWidth>
      <PageHeader
        title="Admin Dashboard"
        subtitle="Choose a section to manage YetAI operations"
      />

      <div className="space-y-6">
        {message && (
          <div
            className={`p-4 rounded-lg ${
              message.type === 'success' ? 'alert alert-success' : 'alert alert-error'
            }`}
          >
            {message.text}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-4">
          <button
            type="button"
            onClick={() => router.push('/admin/users')}
            className="card hover:border-blue-500 transition-colors group text-left"
          >
            <div className="flex items-center">
              <Users className="w-8 h-8 text-blue-600 mr-4 shrink-0" />
              <div>
                <h3 className="text-lg font-semibold group-hover:text-blue-600">
                  User Management
                </h3>
                <p className="text-sm muted">View, edit, and manage all user accounts</p>
              </div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => setShowVerificationPanel(true)}
            className="card hover:border-green-500 transition-colors group text-left"
          >
            <div className="flex items-center">
              <Target className="w-8 h-8 text-green-600 mr-4 shrink-0" />
              <div>
                <h3 className="text-lg font-semibold group-hover:text-green-600">
                  Bet Verification
                </h3>
                <p className="text-sm muted">
                  Monitor and control automatic bet verification
                </p>
              </div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => router.push('/admin/yetai-picks')}
            className="card hover:border-violet-500 transition-colors group text-left"
          >
            <div className="flex items-center">
              <Brain className="w-8 h-8 text-violet-600 mr-4 shrink-0" />
              <div>
                <h3 className="text-lg font-semibold group-hover:text-violet-600">
                  Auto-pick approval
                </h3>
                <p className="text-sm muted">
                  Review pending YetAI bets before they go live on Predictions
                </p>
              </div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => router.push('/admin/pipelines')}
            className="card hover:border-purple-500 transition-colors group text-left"
          >
            <div className="flex items-center">
              <Workflow className="w-8 h-8 text-purple-600 mr-4 shrink-0" />
              <div>
                <h3 className="text-lg font-semibold group-hover:text-purple-600">Pipelines</h3>
                <p className="text-sm muted">
                  Celery beat schedule and manual ETL enqueue / verify
                </p>
              </div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => router.push('/admin/bet-entries')}
            className="card hover:border-amber-500 transition-colors group text-left"
          >
            <div className="flex items-center">
              <ClipboardList className="w-8 h-8 text-amber-500 mr-4 shrink-0" />
              <div>
                <h3 className="text-lg font-semibold group-hover:text-amber-400">
                  Admin Bet Entries
                </h3>
                <p className="text-sm muted">
                  Owen&apos;s Bets, YetAI custom bets, and featured games
                </p>
              </div>
            </div>
          </button>
        </div>
      </div>

      {showVerificationPanel && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg max-w-4xl w-full max-h-[90vh] overflow-y-auto">
            <div className="p-6 border-b border-[var(--border)]">
              <div className="flex items-center justify-between">
                <h2 className="text-2xl font-bold flex items-center">
                  <Target className="w-6 h-6 text-green-600 mr-2" />
                  Bet Verification System
                </h2>
                <button
                  type="button"
                  onClick={() => setShowVerificationPanel(false)}
                  className="dim hover:muted"
                >
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M6 18L18 6M6 6l12 12"
                    />
                  </svg>
                </button>
              </div>
            </div>

            <div className="p-6 space-y-6">
              <div className="flex gap-4">
                <button
                  type="button"
                  onClick={triggerVerification}
                  disabled={isVerifying}
                  className="bg-green-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center"
                >
                  {isVerifying ? (
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2" />
                  ) : (
                    <Target className="w-5 h-5 mr-2" />
                  )}
                  {isVerifying ? 'Verifying...' : 'Run Verification Now'}
                </button>

                <button
                  type="button"
                  onClick={fetchVerificationStats}
                  className="bg-blue-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-blue-700 flex items-center"
                >
                  <Clock className="w-5 h-5 mr-2" />
                  Refresh Stats
                </button>
              </div>

              {verificationStats && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  <div className="card card-tight">
                    <h3 className="font-semibold mb-2">Scheduler Status</h3>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span>Status:</span>
                        <span
                          className={`font-medium ${verificationStats.status?.running ? 'text-green-600' : 'text-red-600'}`}
                        >
                          {verificationStats.status?.running ? 'Running' : 'Stopped'}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>Interval:</span>
                        <span className="font-medium">
                          {verificationStats.config?.interval_minutes} min
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>In Quiet Hours:</span>
                        <span
                          className={`font-medium ${verificationStats.status?.in_quiet_hours ? 'text-yellow-600' : 'text-green-600'}`}
                        >
                          {verificationStats.status?.in_quiet_hours ? 'Yes' : 'No'}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="card card-tight">
                    <h3 className="font-semibold mb-2">Run Statistics</h3>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span>Total Runs:</span>
                        <span className="font-medium">
                          {verificationStats.stats?.total_runs || 0}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>Successful:</span>
                        <span className="font-medium text-green-600">
                          {verificationStats.stats?.successful_runs || 0}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>Failed:</span>
                        <span className="font-medium text-red-600">
                          {verificationStats.stats?.failed_runs || 0}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="card card-tight">
                    <h3 className="font-semibold mb-2">Bet Statistics</h3>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span>Total Verified:</span>
                        <span className="font-medium">
                          {verificationStats.stats?.total_bets_verified || 0}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>Total Settled:</span>
                        <span className="font-medium text-blue-600">
                          {verificationStats.stats?.total_bets_settled || 0}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>Success Rate:</span>
                        <span className="font-medium">
                          {verificationStats.stats?.total_runs > 0
                            ? `${Math.round(
                                (verificationStats.stats.successful_runs /
                                  verificationStats.stats.total_runs) *
                                  100
                              )}%`
                            : '0%'}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {verificationStats?.stats && (
                <div className="card card-tight">
                  <h3 className="font-semibold mb-2">Recent Activity</h3>
                  <div className="space-y-2 text-sm">
                    {verificationStats.stats.last_run_time && (
                      <div className="flex justify-between">
                        <span>Last Run:</span>
                        <span className="font-medium">
                          {new Date(verificationStats.stats.last_run_time).toLocaleString()}
                        </span>
                      </div>
                    )}
                    {verificationStats.stats.last_success_time && (
                      <div className="flex justify-between">
                        <span>Last Success:</span>
                        <span className="font-medium text-green-600">
                          {new Date(
                            verificationStats.stats.last_success_time
                          ).toLocaleString()}
                        </span>
                      </div>
                    )}
                    {verificationStats.stats.last_error && (
                      <div className="mt-2">
                        <span className="text-red-600 font-medium">Last Error:</span>
                        <p className="text-red-600 text-xs mt-1 bg-red-50 p-2 rounded">
                          {verificationStats.stats.last_error}
                        </p>
                      </div>
                    )}
                    {verificationStats.status?.next_run_estimate && (
                      <div className="flex justify-between">
                        <span>Next Run:</span>
                        <span className="font-medium text-blue-600">
                          {new Date(
                            verificationStats.status.next_run_estimate
                          ).toLocaleString()}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {verificationStats?.config && (
                <div className="card card-tight">
                  <h3 className="font-semibold mb-2">Configuration</h3>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div className="flex justify-between">
                      <span>Check Interval:</span>
                      <span className="font-medium">
                        {verificationStats.config.interval_minutes} minutes
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Retry Interval:</span>
                      <span className="font-medium">
                        {verificationStats.config.retry_interval_minutes} minutes
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Max Retries:</span>
                      <span className="font-medium">{verificationStats.config.max_retries}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Quiet Hours:</span>
                      <span className="font-medium">
                        {verificationStats.config.quiet_hours_start}:00 -{' '}
                        {verificationStats.config.quiet_hours_end}:00 UTC
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
