'use client';

import { useCallback, useEffect, useState } from 'react';
import { Check, Loader2, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import { getApiUrl } from '@/lib/api-config';

type OwensBet = {
  id: number;
  name: string;
  odds: string;
  date: string | null;
  result: 'Pending' | 'Win' | 'Loss' | 'Push';
};

type ResultFilter = 'all' | 'Pending' | 'Win' | 'Loss' | 'Push';

const RESULT_BADGE: Record<OwensBet['result'], string> = {
  Pending: 'badge',
  Win: 'badge badge-success',
  Loss: 'badge badge-error',
  Push: 'badge badge-warning',
};

function todayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function authHeaders(): HeadersInit {
  const token = typeof window === 'undefined' ? null : localStorage.getItem('auth_token');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export default function AdminOwensBets() {
  const [bets, setBets] = useState<OwensBet[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<ResultFilter>('all');
  const [busyId, setBusyId] = useState<number | null>(null);

  const [form, setForm] = useState({
    name: '',
    odds: '',
    date: todayIso(),
    result: 'Pending' as OwensBet['result'],
  });
  const [submitting, setSubmitting] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<{
    name: string;
    odds: string;
    date: string;
    result: OwensBet['result'];
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = new URL(getApiUrl('/api/admin/owens-bets'));
      if (filter !== 'all') url.searchParams.set('result', filter);
      const res = await fetch(url.toString(), { headers: authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setBets(Array.isArray(data.bets) ? data.bets : []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'failed to load bets');
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(getApiUrl('/api/admin/owens-bets'), {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(`HTTP ${res.status}: ${body || 'create failed'}`);
      }
      setForm({ name: '', odds: '', date: todayIso(), result: 'Pending' });
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'create failed');
    } finally {
      setSubmitting(false);
    }
  };

  const updateResult = async (bet: OwensBet, result: OwensBet['result']) => {
    setBusyId(bet.id);
    setError(null);
    try {
      const res = await fetch(getApiUrl(`/api/admin/owens-bets/${bet.id}`), {
        method: 'PATCH',
        headers: authHeaders(),
        body: JSON.stringify({ result }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'update failed');
    } finally {
      setBusyId(null);
    }
  };

  const startEdit = (bet: OwensBet) => {
    setEditingId(bet.id);
    setEditForm({
      name: bet.name,
      odds: bet.odds,
      date: bet.date ?? todayIso(),
      result: bet.result,
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditForm(null);
  };

  const saveEdit = async () => {
    if (editingId == null || !editForm) return;
    setBusyId(editingId);
    setError(null);
    try {
      const res = await fetch(getApiUrl(`/api/admin/owens-bets/${editingId}`), {
        method: 'PATCH',
        headers: authHeaders(),
        body: JSON.stringify(editForm),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      cancelEdit();
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'update failed');
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (bet: OwensBet) => {
    if (!confirm(`Delete "${bet.name}"?`)) return;
    setBusyId(bet.id);
    setError(null);
    try {
      const res = await fetch(getApiUrl(`/api/admin/owens-bets/${bet.id}`), {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'delete failed');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="card">
        <h2 className="text-xl font-semibold mb-4 flex items-center">
          <Plus className="w-5 h-5 mr-2" />
          Add Owen&apos;s Bet
        </h2>
        <form onSubmit={onCreate} className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div className="md:col-span-2">
            <label className="block text-sm muted mb-1">Pick</label>
            <input
              required
              className="input w-full"
              placeholder="e.g., Yankees ML"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div>
            <label className="block text-sm muted mb-1">Odds</label>
            <input
              required
              className="input w-full"
              placeholder="-110, +150"
              value={form.odds}
              onChange={(e) => setForm({ ...form, odds: e.target.value })}
            />
          </div>
          <div>
            <label className="block text-sm muted mb-1">Date</label>
            <input
              required
              type="date"
              className="input w-full"
              value={form.date}
              onChange={(e) => setForm({ ...form, date: e.target.value })}
            />
          </div>
          <div className="md:col-span-4 flex items-center gap-3 justify-end">
            <label className="text-sm muted">Result</label>
            <select
              className="input"
              value={form.result}
              onChange={(e) =>
                setForm({ ...form, result: e.target.value as OwensBet['result'] })
              }
            >
              <option value="Pending">Pending</option>
              <option value="Win">Win</option>
              <option value="Loss">Loss</option>
              <option value="Push">Push</option>
            </select>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              Add bet
            </button>
          </div>
        </form>
      </div>

      <div className="card">
        <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
          <h2 className="text-xl font-semibold">Owen&apos;s Bets</h2>
          <div className="flex items-center gap-2">
            <select
              className="input"
              value={filter}
              onChange={(e) => setFilter(e.target.value as ResultFilter)}
            >
              <option value="all">All</option>
              <option value="Pending">Pending</option>
              <option value="Win">Win</option>
              <option value="Loss">Loss</option>
              <option value="Push">Push</option>
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
                <th className="py-2 pr-3">Date</th>
                <th className="py-2 pr-3">Pick</th>
                <th className="py-2 pr-3">Odds</th>
                <th className="py-2 pr-3">Result</th>
                <th className="py-2 pr-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && bets.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-6 text-center muted">
                    <Loader2 className="w-4 h-4 animate-spin inline mr-2" /> Loading...
                  </td>
                </tr>
              ) : bets.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-6 text-center muted">
                    No bets to show.
                  </td>
                </tr>
              ) : (
                bets.map((bet) => {
                  const isEditing = editingId === bet.id;
                  const isBusy = busyId === bet.id;
                  if (isEditing && editForm) {
                    return (
                      <tr key={bet.id} className="border-t border-[var(--border)]">
                        <td className="py-2 pr-3">
                          <input
                            type="date"
                            className="input"
                            value={editForm.date}
                            onChange={(e) => setEditForm({ ...editForm, date: e.target.value })}
                          />
                        </td>
                        <td className="py-2 pr-3">
                          <input
                            className="input w-full"
                            value={editForm.name}
                            onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                          />
                        </td>
                        <td className="py-2 pr-3">
                          <input
                            className="input"
                            value={editForm.odds}
                            onChange={(e) => setEditForm({ ...editForm, odds: e.target.value })}
                          />
                        </td>
                        <td className="py-2 pr-3">
                          <select
                            className="input"
                            value={editForm.result}
                            onChange={(e) =>
                              setEditForm({
                                ...editForm,
                                result: e.target.value as OwensBet['result'],
                              })
                            }
                          >
                            <option value="Pending">Pending</option>
                            <option value="Win">Win</option>
                            <option value="Loss">Loss</option>
                            <option value="Push">Push</option>
                          </select>
                        </td>
                        <td className="py-2 pr-3 text-right">
                          <div className="inline-flex gap-1">
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              onClick={saveEdit}
                              disabled={isBusy}
                            >
                              {isBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                              Save
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              onClick={cancelEdit}
                              disabled={isBusy}
                            >
                              <X className="w-3 h-3" /> Cancel
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  }
                  return (
                    <tr key={bet.id} className="border-t border-[var(--border)]">
                      <td className="py-2 pr-3 whitespace-nowrap">{bet.date ?? '—'}</td>
                      <td className="py-2 pr-3">{bet.name}</td>
                      <td className="py-2 pr-3 mono">{bet.odds}</td>
                      <td className="py-2 pr-3">
                        <span className={RESULT_BADGE[bet.result]}>{bet.result}</span>
                      </td>
                      <td className="py-2 pr-3 text-right">
                        <div className="inline-flex gap-1 flex-wrap justify-end">
                          {bet.result === 'Pending' && (
                            <>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                onClick={() => updateResult(bet, 'Win')}
                                disabled={isBusy}
                                title="Mark as Win"
                              >
                                W
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                onClick={() => updateResult(bet, 'Loss')}
                                disabled={isBusy}
                                title="Mark as Loss"
                              >
                                L
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                onClick={() => updateResult(bet, 'Push')}
                                disabled={isBusy}
                                title="Mark as Push"
                              >
                                P
                              </button>
                            </>
                          )}
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() => startEdit(bet)}
                            disabled={isBusy}
                            title="Edit"
                          >
                            <Pencil className="w-3 h-3" />
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() => remove(bet)}
                            disabled={isBusy}
                            title="Delete"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
