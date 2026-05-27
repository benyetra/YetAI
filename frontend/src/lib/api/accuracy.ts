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

function normalizeOverviewItem(raw: Record<string, unknown>): AccuracyOverviewItem | null {
  const sportRaw = String(raw.sport ?? '').toLowerCase();
  if (!['mlb', 'nba', 'nfl', 'nhl', 'wnba'].includes(sportRaw)) {
    return null;
  }
  const sport = sportRaw as AccuracySport;
  const toneRaw = String(raw.tone ?? 'neutral');
  const tone = (['good', 'warn', 'neutral'].includes(toneRaw) ? toneRaw : 'neutral') as AccuracyTone;
  const hasData = Boolean(raw.has_data ?? raw.hasData);
  const graded = Number(raw.graded_count ?? raw.gradedCount ?? 0);
  return {
    sport,
    label: String(raw.label ?? ''),
    primary: String(raw.primary ?? ''),
    secondary: String(raw.secondary ?? ''),
    tone,
    has_data: hasData,
    graded_count: Number.isFinite(graded) ? graded : 0,
  };
}

export async function fetchAccuracyOverview(
  window: AccuracyOverviewWindow = 'season',
): Promise<AccuracyOverviewResponse> {
  const res = await apiRequest(
    `/api/v1/predictions/accuracy/overview?window=${encodeURIComponent(window)}`,
    { cache: 'no-store' },
  );
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Accuracy overview fetch failed (${res.status}): ${body}`);
  }
  const data = (await res.json()) as Record<string, unknown>;
  const rawItems = (data.items ?? data.Items) as unknown;
  if (!Array.isArray(rawItems)) {
    throw new Error('Accuracy overview: response missing items array');
  }
  const win = (data.window ?? data.Window ?? window) as AccuracyOverviewWindow;
  const asOf = String(data.as_of ?? data.asOf ?? '');
  return {
    window: win === 'last_30' || win === 'season' ? win : window,
    as_of: asOf,
    items: rawItems
      .map((row) => normalizeOverviewItem(row as Record<string, unknown>))
      .filter((x): x is AccuracyOverviewItem => x !== null),
  };
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
