import { apiRequest } from '@/lib/api-config';

export interface ScheduledEntry {
  key: string;
  task_name: string;
  label: string;
  sport: string;
  is_orchestrator: boolean;
  schedule_type: 'crontab';
  crontab: {
    minute: number[] | '*';
    hour: number[] | '*';
    day_of_week: number[] | '*';
    day_of_month: number[] | '*';
    month_of_year: number[] | '*';
  };
  human: string;
  next_fires_today_et: string[];
}

export interface ContinuousEntry {
  key: string;
  task_name: string;
  label: string;
  sport: string;
  is_orchestrator: boolean;
  schedule_type: 'interval' | 'crontab_frequent';
  interval_seconds: number;
  human: string;
}

export interface ScheduleResponse {
  scheduled: ScheduledEntry[];
  continuous: ContinuousEntry[];
}

export async function fetchPipelineSchedule(): Promise<ScheduleResponse> {
  const res = await apiRequest('/api/admin/pipelines/schedule');
  if (!res.ok) {
    const msg = await res.text().catch(() => '');
    throw new Error(`Failed to load pipeline schedule (${res.status}): ${msg}`);
  }
  return res.json();
}
