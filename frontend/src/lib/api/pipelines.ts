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
  is_overridden?: boolean;
  is_enabled?: boolean;
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
  is_overridden?: boolean;
  is_enabled?: boolean;
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

export interface UpdateScheduleRequest {
  hour: number;
  minute: number;
  enabled: boolean;
}

export interface UpdateScheduleResponse {
  task_name: string;
  hour: number;
  minute: number;
  enabled: boolean;
}

export async function updatePipelineSchedule(
  taskName: string,
  body: UpdateScheduleRequest,
): Promise<UpdateScheduleResponse> {
  const res = await apiRequest(
    `/api/admin/pipelines/${encodeURIComponent(taskName)}/schedule`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    throw new Error(`Update failed (${res.status}): ${await res.text().catch(() => '')}`);
  }
  return res.json();
}

export async function resetPipelineSchedule(
  taskName: string,
): Promise<{ reset: boolean }> {
  const res = await apiRequest(
    `/api/admin/pipelines/${encodeURIComponent(taskName)}/schedule/reset`,
    { method: 'POST' },
  );
  if (!res.ok) {
    throw new Error(`Reset failed (${res.status}): ${await res.text().catch(() => '')}`);
  }
  return res.json();
}
