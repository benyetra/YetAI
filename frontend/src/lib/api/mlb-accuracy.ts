import { apiRequest } from '@/lib/api-config';

export interface MlbAccuracy {
  date: string;
  available: boolean;
  pitcher_ks_ou: {
    total: number;
    correct: number;
    push: number;
    accuracy: number | null;
    mae: number | null;
  };
  projected_hits: {
    projected_batters: number;
    hits_made: number;
    success_rate: number | null;
  };
  projected_homers: {
    projected_batters: number;
    hr_hit: number;
    success_rate: number | null;
  };
}

export async function fetchMlbAccuracy(date: string): Promise<MlbAccuracy> {
  const res = await apiRequest(
    `/api/v1/predictions/mlb/accuracy?date=${encodeURIComponent(date)}`,
  );
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Accuracy fetch failed (${res.status}): ${body}`);
  }
  return res.json();
}
