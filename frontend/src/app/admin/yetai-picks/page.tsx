'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/components/Auth';
import Layout from '@/components/Layout';
import AppLoading from '@/components/yetai/AppLoading';
import PageHeader from '@/components/yetai/PageHeader';
import { listPendingPicks, approveAllPicks, type PendingPick } from '@/lib/api/yetai-picks';
import { PendingPickCard } from './PendingPickCard';
import { CheckCircle, RefreshCw } from 'lucide-react';

function ApproveAllButton({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);

  const handleApproveAll = async () => {
    if (!confirm('Approve all pending picks?')) return;
    setBusy(true);
    try {
      await approveAllPicks();
      onDone();
    } catch (err) {
      console.error('Approve-all failed:', err);
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      disabled={busy}
      onClick={handleApproveAll}
      className="inline-flex items-center gap-2 px-4 py-2 bg-green-600 text-white text-sm font-medium rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
    >
      <CheckCircle className="w-4 h-4" />
      {busy ? 'Approving…' : 'Approve All'}
    </button>
  );
}

export default function PendingPicksPage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();

  const [picks, setPicks] = useState<PendingPick[]>([]);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const featureEnabled =
    process.env.NEXT_PUBLIC_AUTO_YETAI_PICKS_ENABLED === 'true';

  useEffect(() => {
    if (!featureEnabled) {
      router.push('/dashboard');
      return;
    }
    if (!loading && (!isAuthenticated || !user?.is_admin)) {
      router.push('/dashboard');
    }
  }, [isAuthenticated, loading, user, router, featureEnabled]);

  const refresh = async () => {
    setFetching(true);
    setError(null);
    try {
      const r = await listPendingPicks();
      setPicks(r.picks);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setFetching(false);
    }
  };

  useEffect(() => {
    if (isAuthenticated && user?.is_admin) {
      refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, user]);

  if (loading) {
    return (
      <Layout requiresAuth fullWidth>
        <AppLoading label="Loading…" />
      </Layout>
    );
  }

  if (!isAuthenticated || !user?.is_admin) {
    return null;
  }

  return (
    <Layout requiresAuth fullWidth>
      <PageHeader
        title="Pending YetAI Picks"
        subtitle="Review and approve auto-generated picks before they go live"
        actions={
          <button
            onClick={router.back}
            className="btn"
          >
            Back to Admin
          </button>
        }
      />

      <div className="space-y-4">
        {/* Toolbar */}
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <button
              onClick={refresh}
              disabled={fetching}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200 disabled:opacity-50 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${fetching ? 'animate-spin' : ''}`} />
              Refresh
            </button>
            {!fetching && (
              <span className="text-sm text-gray-500">
                {picks.length} pending {picks.length === 1 ? 'pick' : 'picks'}
              </span>
            )}
          </div>
          {picks.length > 0 && <ApproveAllButton onDone={refresh} />}
        </div>

        {/* Error state */}
        {error && (
          <div className="alert alert-error">
            <p className="font-medium">Failed to load picks</p>
            <p className="text-sm mt-0.5">{error}</p>
          </div>
        )}

        {/* Loading skeleton */}
        {fetching && !error && (
          <div className="grid gap-4">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="rounded-lg border border-[var(--border)] p-4 bg-white shadow-sm animate-pulse h-40"
              />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!fetching && !error && picks.length === 0 && (
          <div className="card text-center py-12">
            <CheckCircle className="w-12 h-12 text-green-400 mx-auto mb-3" />
            <p className="text-lg font-medium">All clear</p>
            <p className="text-sm text-gray-500 mt-1">No pending YetAI picks to review.</p>
          </div>
        )}

        {/* Pick cards */}
        {!fetching && picks.length > 0 && (
          <div className="grid gap-4">
            {picks.map((p) => (
              <PendingPickCard key={p.id} pick={p} onChanged={refresh} />
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
