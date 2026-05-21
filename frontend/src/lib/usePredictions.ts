'use client';

import { useEffect, useState } from 'react';
import { getApiUrl } from './api-config';

export type PredictionSport = 'mlb' | 'nba' | 'nfl' | 'nhl';
type Sport = PredictionSport;

type PredictionsState = {
  data: Record<string, Array<Record<string, unknown>>> | null;
  loading: boolean;
  error: string | null;
  paywalled: boolean;
};

type UsePredictionsOptions = {
  enabled?: boolean;
};

export function usePredictions(
  sport: Sport,
  date?: string,
  { enabled = true }: UsePredictionsOptions = {},
): PredictionsState {
  const [state, setState] = useState<PredictionsState>({
    data: null,
    loading: true,
    error: null,
    paywalled: false,
  });

  useEffect(() => {
    if (!enabled) {
      // Stay in loading=true until the caller flips enabled on.
      // Prevents API calls before auth resolves.
      return;
    }
    const ac = new AbortController();
    setState({ data: null, loading: true, error: null, paywalled: false });

    const url = new URL(getApiUrl(`/api/v1/predictions/${sport}`));
    if (date) url.searchParams.set('date', date);
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (tz) url.searchParams.set('tz', tz);
    } catch {
      /* browsers without Intl resolvedOptions — let the API default to UTC */
    }

    const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;

    fetch(url.toString(), {
      signal: ac.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
      .then(async (res) => {
        if (res.status === 403) {
          setState({ data: null, loading: false, error: null, paywalled: true });
          return;
        }
        if (!res.ok) {
          const text = await res.text().catch(() => '');
          setState({
            data: null,
            loading: false,
            error: `HTTP ${res.status}: ${text || 'request failed'}`,
            paywalled: false,
          });
          return;
        }
        const json = await res.json();
        setState({ data: json, loading: false, error: null, paywalled: false });
      })
      .catch((e) => {
        if (e?.name === 'AbortError') return;
        setState({
          data: null,
          loading: false,
          error: e?.message ?? 'request failed',
          paywalled: false,
        });
      });

    return () => ac.abort();
  }, [sport, date, enabled]);

  return state;
}
