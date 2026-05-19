'use client';

import { useEffect, useState } from 'react';
import { getApiUrl } from './api-config';

export type OwensBet = {
  id: number;
  name: string;
  odds: string;
  date: string | null;
  result: string;
};

export type OwensSummary = {
  total_historical: number;
  wins: number;
  losses: number;
  success_rate: number;
  implied_units: number;
  implied_units_display: string;
};

type OwensState = {
  pending: OwensBet[];
  historical: OwensBet[];
  summary: OwensSummary | null;
  loading: boolean;
  error: string | null;
};

export function useOwensBettingCorner(enabled = true): OwensState {
  const [state, setState] = useState<OwensState>({
    pending: [],
    historical: [],
    summary: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    if (!enabled) return;
    const ac = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));

    const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;

    fetch(getApiUrl('/api/v1/tools/owens-betting-corner'), {
      signal: ac.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text().catch(() => '');
          throw new Error(text || `HTTP ${res.status}`);
        }
        return res.json();
      })
      .then((json) => {
        setState({
          pending: json.pending_bets ?? [],
          historical: json.historical_bets ?? [],
          summary: json.summary ?? null,
          loading: false,
          error: null,
        });
      })
      .catch((e) => {
        if (e?.name === 'AbortError') return;
        setState({
          pending: [],
          historical: [],
          summary: null,
          loading: false,
          error: e?.message ?? 'Failed to load',
        });
      });

    return () => ac.abort();
  }, [enabled]);

  return state;
}
