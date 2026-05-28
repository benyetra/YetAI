'use client';

import { useCallback, useEffect, useState } from 'react';
import { Layers, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import { getApiUrl } from '@/lib/api-config';

export type YetaiAdminBet = {
  id: string;
  sport: string;
  game: string;
  pick: string;
  odds: string;
  bet_type: string;
  bet_category: 'straight' | 'parlay' | string;
  status: string;
  game_time?: string;
  created_at?: string | null;
  parlay_legs?: unknown[];
};

type StatusFilter = 'all' | 'live' | 'settled' | 'pending_approval' | 'rejected';

const STATUS_BADGE: Record<string, string> = {
  pending: 'badge',
  active: 'badge badge-success',
  pending_approval: 'badge badge-warning',
  won: 'badge badge-success',
  lost: 'badge badge-error',
  pushed: 'badge badge-warning',
  rejected: 'badge badge-error',
  expired: 'badge',
};

function authHeaders(): HeadersInit {
  const token = typeof window === 'undefined' ? null : localStorage.getItem('auth_token');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function statusLabel(status: string): string {
  return status.replace(/_/g, ' ');
}

type AdminYetaiBetsManageProps = {
  /** Bump after creating a bet so the list reloads. */
  refreshToken?: number;
};

export default function AdminYetaiBetsManage({ refreshToken = 0 }: AdminYetaiBetsManageProps) {
  const [bets, setBets] = useState<YetaiAdminBet[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = new URL(getApiUrl('/api/admin/yetai-bets'));
      url.searchParams.set('include_settled', 'true');
      url.searchParams.set('include_stale_pending', 'true');
      const res = await fetch(url.toString(), { headers: authHeaders() });
      if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(body || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setBets(Array.isArray(data.bets) ? data.bets : []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load YetAI bets');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshToken]);

  const filtered = bets.filter((bet) => {
    const s = (bet.status || '').toLowerCase();
    if (filter === 'all') return true;
    if (filter === 'live') return s === 'pending' || s === 'active';
    if (filter === 'settled') return s === 'won' || s === 'lost' || s === 'pushed';
    if (filter === 'pending_approval') return s === 'pending_approval';
    if (filter === 'rejected') return s === 'rejected' || s === 'expired';
    return true;
  });

  const remove = async (bet: YetaiAdminBet) => {
    const label = bet.bet_category === 'parlay' ? bet.game || 'Parlay' : bet.pick;
    const confirmed = confirm(
      `Permanently delete this YetAI bet?\n\n${label}\n${bet.game || ''}\n\nThis hard-deletes the row and cannot be undone. It will disappear from Predictions for subscribers.`,
    );
    if (!confirmed) return;

    setBusyId(bet.id);
    setError(null);
    try {
      const res = await fetch(getApiUrl(`/api/admin/yetai-bets/${bet.id}`), {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Delete failed');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <div>
          <h2 className="text-xl font-semibold">Manage YetAI Bets</h2>
          <p className="text-sm muted mt-1">
            Hard-delete bets you created here or approved from pending picks.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="input"
            value={filter}
            onChange={(e) => setFilter(e.target.value as StatusFilter)}
          >
            <option value="all">All statuses</option>
            <option value="live">Live (pending / active)</option>
            <option value="settled">Settled</option>
            <option value="pending_approval">Pending approval</option>
            <option value="rejected">Rejected / expired</option>
          </select>
          <button type="button" className="btn btn-ghost" onClick={() => load()} disabled={loading}>
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            Refresh
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error mb-3">{error}</div>}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left muted">
              <th className="py-2 pr-3">Created</th>
              <th className="py-2 pr-3">Sport</th>
              <th className="py-2 pr-3">Game</th>
              <th className="py-2 pr-3">Pick</th>
              <th className="py-2 pr-3">Odds</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 pr-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && bets.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-6 text-center muted">
                  <Loader2 className="w-4 h-4 animate-spin inline mr-2" /> Loading…
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-6 text-center muted">
                  No YetAI bets match this filter.
                </td>
              </tr>
            ) : (
              filtered.map((bet) => {
                const isBusy = busyId === bet.id;
                const statusKey = (bet.status || 'pending').toLowerCase();
                const created = bet.created_at
                  ? new Date(bet.created_at).toLocaleDateString()
                  : '—';
                return (
                  <tr key={bet.id} className="border-t border-[var(--border)]">
                    <td className="py-2 pr-3 whitespace-nowrap">{created}</td>
                    <td className="py-2 pr-3 whitespace-nowrap">{bet.sport}</td>
                    <td className="py-2 pr-3 max-w-[12rem] truncate" title={bet.game}>
                      {bet.game}
                    </td>
                    <td className="py-2 pr-3 max-w-[14rem]">
                      <div className="flex items-center gap-1">
                        {bet.bet_category === 'parlay' && (
                          <Layers className="w-3 h-3 shrink-0 muted" aria-hidden />
                        )}
                        <span className="truncate" title={bet.pick}>
                          {bet.pick}
                        </span>
                      </div>
                      {bet.bet_category === 'parlay' && bet.parlay_legs && (
                        <span className="text-xs muted">
                          {Array.isArray(bet.parlay_legs) ? bet.parlay_legs.length : 0} legs
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3 mono whitespace-nowrap">{bet.odds}</td>
                    <td className="py-2 pr-3">
                      <span className={STATUS_BADGE[statusKey] ?? 'badge'}>
                        {statusLabel(bet.status || 'unknown')}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-right">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm text-red-400 hover:text-red-300"
                        onClick={() => remove(bet)}
                        disabled={isBusy}
                        title="Hard delete"
                      >
                        {isBusy ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Trash2 className="w-3 h-3" />
                        )}
                        <span className="sr-only">Delete</span>
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
