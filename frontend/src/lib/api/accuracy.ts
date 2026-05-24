import { apiRequest } from '@/lib/api-config';

export type AccuracySport = 'mlb' | 'nba' | 'nfl' | 'nhl' | 'wnba';

export type AccuracyTone = 'good' | 'warn' | 'neutral';

export interface AccuracyBucket {
  key: string;
  label: string;
  primary: string;
  secondary: string;
  tone: AccuracyTone;
}

export interface AccuracySummary {
  date: string;
  available: boolean;
  buckets: AccuracyBucket[];
}

export async function fetchAccuracy(
  sport: AccuracySport,
  date: string,
): Promise<AccuracySummary> {
  const res = await apiRequest(
    `/api/v1/predictions/${sport}/accuracy?date=${encodeURIComponent(date)}`,
  );
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Accuracy fetch failed (${res.status}): ${body}`);
  }
  return res.json();
}
