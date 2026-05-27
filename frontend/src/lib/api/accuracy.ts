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

export type AccuracyOverviewWindow = 'season' | 'last_30';

export interface AccuracyOverviewItem {
  sport: AccuracySport;
  label: string;
  primary: string;
  secondary: string;
  tone: AccuracyTone;
  has_data: boolean;
  graded_count: number;
}

export interface AccuracyOverviewResponse {
  window: AccuracyOverviewWindow;
  as_of: string;
  items: AccuracyOverviewItem[];
}

export async function fetchAccuracyOverview(
  window: AccuracyOverviewWindow = 'season',
): Promise<AccuracyOverviewResponse> {
  const res = await apiRequest(
    `/api/v1/predictions/accuracy/overview?window=${encodeURIComponent(window)}`,
  );
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Accuracy overview fetch failed (${res.status}): ${body}`);
  }
  return res.json();
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
