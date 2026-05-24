'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/components/Auth';
import Layout from '@/components/Layout';
import { Calendar, Clock, Pencil, RefreshCw, Workflow } from 'lucide-react';
import {
  fetchPipelineSchedule,
  type ContinuousEntry,
  type ScheduleResponse,
  type ScheduledEntry,
} from '@/lib/api/pipelines';
import { PipelineScheduleEditModal } from '@/components/admin/PipelineScheduleEditModal';

// Sport → accent color. Falls back to neutral when sport is unknown.
const SPORT_COLOR: Record<string, string> = {
  nba: 'bg-orange-500',
  wnba: 'bg-pink-500',
  mlb: 'bg-blue-500',
  nfl: 'bg-emerald-500',
  nhl: 'bg-cyan-500',
  yetai: 'bg-violet-500',
};

function sportColor(sport: string): string {
  return SPORT_COLOR[sport.toLowerCase()] ?? 'bg-zinc-500';
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: 'America/New_York',
  });
}

function hourFromIso(iso: string): number {
  // Use the ET-rendered hour for the marker position.
  return new Date(iso).getHours();
}

function TimelineRow({
  entry,
  onEdit,
}: {
  entry: ScheduledEntry;
  onEdit: (e: ScheduledEntry) => void;
}) {
  return (
    <div className="flex items-center gap-3 py-3 border-b border-zinc-800/50 last:border-0">
      <div className="w-44 shrink-0 flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${sportColor(entry.sport)}`} />
        <div className="min-w-0">
          <div className="text-sm text-zinc-200 truncate flex items-center gap-1.5">
            {entry.label}
            {entry.is_overridden && (
              <span
                className="text-[9px] px-1 py-0.5 rounded bg-purple-900/50 text-purple-300 border border-purple-800/50"
                title="Schedule overridden from default"
              >
                MOD
              </span>
            )}
          </div>
          <div className="text-[11px] text-zinc-500 truncate">{entry.human}</div>
        </div>
      </div>
      <div className="flex-1 relative h-8 bg-zinc-900/60 rounded border border-zinc-800/60">
        {/* hour ticks */}
        {Array.from({ length: 24 }, (_, h) => (
          <div
            key={h}
            className="absolute top-0 bottom-0 border-l border-zinc-800/40"
            style={{ left: `${(h / 24) * 100}%` }}
          />
        ))}
        {/* fire markers */}
        {entry.next_fires_today_et.map((iso, i) => {
          const minutes =
            new Date(iso).getHours() * 60 + new Date(iso).getMinutes();
          const pct = (minutes / 1440) * 100;
          return (
            <div
              key={i}
              className={`absolute top-1 bottom-1 w-1.5 rounded-sm ${sportColor(entry.sport)} group`}
              style={{ left: `calc(${pct}% - 3px)` }}
              title={`${entry.label} · ${formatTime(iso)}`}
            >
              <div className="hidden group-hover:block absolute -top-7 left-1/2 -translate-x-1/2 whitespace-nowrap text-[11px] bg-zinc-950 border border-zinc-700 rounded px-1.5 py-0.5 text-zinc-200">
                {formatTime(iso)}
              </div>
            </div>
          );
        })}
      </div>
      {entry.is_orchestrator ? (
        <button
          onClick={() => onEdit(entry)}
          className="flex items-center gap-1 px-2.5 py-1 text-xs text-zinc-300 hover:text-white border border-zinc-700 hover:border-zinc-500 rounded transition-colors"
          title="Edit this pipeline's schedule"
        >
          <Pencil className="w-3 h-3" />
          Edit
        </button>
      ) : (
        <div
          className="w-[60px] text-[10px] text-zinc-600 text-center"
          title="Only orchestrator pipelines are editable"
        >
          —
        </div>
      )}
    </div>
  );
}

function HourScale() {
  return (
    <div className="flex items-center gap-3 pb-2 text-[11px] text-zinc-500">
      <div className="w-44 shrink-0" />
      <div className="flex-1 relative h-4">
        {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
          <div
            key={h}
            className="absolute -translate-x-1/2"
            style={{ left: `${(h / 24) * 100}%` }}
          >
            {h === 0 ? '12a' : h === 12 ? '12p' : h < 12 ? `${h}a` : `${h - 12}p`}
          </div>
        ))}
      </div>
      <div className="w-16 shrink-0" />
    </div>
  );
}

function ContinuousRow({ entry }: { entry: ContinuousEntry }) {
  return (
    <div className="flex items-center justify-between py-2 px-3 rounded border border-zinc-800/50 bg-zinc-900/30">
      <div className="flex items-center gap-2 min-w-0">
        <span className={`w-2 h-2 rounded-full ${sportColor(entry.sport)}`} />
        <div className="min-w-0">
          <div className="text-sm text-zinc-200 truncate">{entry.label}</div>
          <div className="text-[11px] text-zinc-500 truncate font-mono">{entry.task_name}</div>
        </div>
      </div>
      <div className="text-xs text-zinc-400 shrink-0">{entry.human}</div>
    </div>
  );
}

export default function PipelinesSchedulePage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();

  const [data, setData] = useState<ScheduleResponse | null>(null);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ScheduledEntry | null>(null);

  const isAdmin = !!user?.is_admin;

  useEffect(() => {
    if (loading) return;
    if (!isAuthenticated || !isAdmin) {
      router.push('/');
    }
  }, [loading, isAuthenticated, isAdmin, router]);

  const reload = async () => {
    setFetching(true);
    setError(null);
    try {
      const r = await fetchPipelineSchedule();
      setData(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setFetching(false);
    }
  };

  useEffect(() => {
    if (isAuthenticated && isAdmin) {
      reload();
    }
  }, [isAuthenticated, isAdmin]);

  const orchestratorCount = useMemo(() => {
    if (!data) return 0;
    return (
      data.scheduled.filter((s) => s.is_orchestrator).length +
      data.continuous.filter((c) => c.is_orchestrator).length
    );
  }, [data]);

  if (loading || !isAuthenticated || !isAdmin) {
    return null;
  }

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-6 py-10 space-y-8 text-zinc-100">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Pipeline Schedule</h1>
            <p className="text-sm text-zinc-400 mt-1">
              Daily timeline of every Celery beat-scheduled task. Times are
              shown in America/New_York. Click <span className="text-zinc-300">Edit</span>{' '}
              on an orchestrator row to change its schedule; changes apply
              within ~30 seconds.
            </p>
          </div>
          <button
            onClick={reload}
            disabled={fetching}
            className="inline-flex items-center gap-2 px-3 py-1.5 text-sm border border-zinc-700 rounded hover:bg-zinc-800/50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${fetching ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {error && (
          <div className="border border-red-800/60 bg-red-950/30 text-red-300 text-sm rounded p-3">
            {error}
          </div>
        )}

        {data && (
          <>
            {data.auto_yetai_picks_enabled === false && (
              <div className="border border-amber-800/60 bg-amber-950/30 text-amber-200 text-sm rounded p-3">
                YetAI auto-pick beat tasks are hidden because{' '}
                <code className="text-amber-100">AUTO_YETAI_PICKS_ENABLED</code> is not set on
                this API service. Set it on <strong>YetAI</strong> and <strong>celery-worker</strong>,
                then redeploy both.
              </div>
            )}
            <div className="flex items-center gap-4 text-xs text-zinc-500">
              <span className="inline-flex items-center gap-1.5">
                <Workflow className="w-3.5 h-3.5" />
                {orchestratorCount} orchestrators
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5" />
                {data.scheduled.length} scheduled
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5" />
                {data.continuous.length} continuous
              </span>
            </div>

            <section className="space-y-2">
              <h2 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">
                Scheduled today
              </h2>
              <div className="border border-zinc-800/60 rounded-lg bg-zinc-950/40 px-4 py-3">
                <HourScale />
                <div>
                  {data.scheduled.length === 0 ? (
                    <div className="text-sm text-zinc-500 py-6 text-center">
                      Nothing scheduled today.
                    </div>
                  ) : (
                    data.scheduled.map((s) => (
                      <TimelineRow key={s.key} entry={s} onEdit={setEditing} />
                    ))
                  )}
                </div>
              </div>
            </section>

            <section className="space-y-2">
              <h2 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">
                Continuous & high-frequency
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {data.continuous.map((c) => (
                  <ContinuousRow key={c.key} entry={c} />
                ))}
              </div>
            </section>
          </>
        )}

        {!data && fetching && (
          <div className="text-sm text-zinc-500">Loading schedule…</div>
        )}

        {editing && (
          <PipelineScheduleEditModal
            entry={editing}
            onClose={() => setEditing(null)}
            onSaved={() => {
              setEditing(null);
              reload();
            }}
          />
        )}
      </div>
    </Layout>
  );
}
