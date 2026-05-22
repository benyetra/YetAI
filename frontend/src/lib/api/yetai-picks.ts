/**
 * Typed API client for the YetAI auto-picks admin endpoints.
 * Uses apiRequest from api-config, which automatically attaches the
 * stored bearer token and handles session expiry on 401.
 */
import { apiRequest, parseApiErrorResponse } from '@/lib/api-config';

export type PendingPick = {
  id: string;
  title?: string;
  selection?: string;
  bet_type?: string | null;
  sport?: string | null;
  odds?: number | null;
  status: string;
  tier_requirement: 'free' | 'pro' | 'elite';
  confidence_score: number | null;
  score_breakdown: Record<string, number> | null;
  reasoning: string | null;
  source: 'manual' | 'auto' | null;
  created_at: string | null;
};

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiRequest(path, init);
  if (!res.ok) {
    const msg = await parseApiErrorResponse(res);
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function listPendingPicks(): Promise<{ picks: PendingPick[] }> {
  return apiFetch<{ picks: PendingPick[] }>('/api/admin/yetai-picks/pending');
}

export async function approvePick(id: string): Promise<PendingPick> {
  return apiFetch<PendingPick>(`/api/admin/yetai-picks/${id}/approve`, {
    method: 'POST',
  });
}

export async function rejectPick(id: string): Promise<PendingPick> {
  return apiFetch<PendingPick>(`/api/admin/yetai-picks/${id}/reject`, {
    method: 'POST',
  });
}

export async function editPick(
  id: string,
  patch: Partial<Pick<PendingPick, 'tier_requirement' | 'reasoning' | 'selection' | 'odds' | 'title'>>,
): Promise<PendingPick> {
  return apiFetch<PendingPick>(`/api/admin/yetai-picks/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
}

export async function approveAllPicks(): Promise<{ approved: string[] }> {
  return apiFetch<{ approved: string[] }>('/api/admin/yetai-picks/approve-all', {
    method: 'POST',
  });
}
