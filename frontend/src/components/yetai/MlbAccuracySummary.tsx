'use client';

import { useEffect, useState } from 'react';
import { Target, CheckCircle2, AlertCircle } from 'lucide-react';
import { fetchMlbAccuracy, type MlbAccuracy } from '@/lib/api/mlb-accuracy';

interface Props {
  date: string;
}

function pct(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return '—';
  return `${Math.round(rate * 100)}%`;
}

function Tile({
  icon,
  label,
  primary,
  secondary,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  primary: string;
  secondary: string;
  tone: 'good' | 'warn' | 'neutral';
}) {
  const ring =
    tone === 'good'
      ? 'border-emerald-700/40 bg-emerald-950/20'
      : tone === 'warn'
      ? 'border-amber-700/40 bg-amber-950/20'
      : 'border-zinc-800 bg-zinc-900/40';
  const accent =
    tone === 'good'
      ? 'text-emerald-300'
      : tone === 'warn'
      ? 'text-amber-300'
      : 'text-zinc-300';
  return (
    <div className={`rounded-lg border ${ring} p-4 flex flex-col gap-2`}>
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-zinc-400">
        {icon}
        <span>{label}</span>
      </div>
      <div className={`text-2xl font-semibold ${accent}`}>{primary}</div>
      <div className="text-xs text-zinc-500">{secondary}</div>
    </div>
  );
}

function toneForRate(rate: number | null | undefined): 'good' | 'warn' | 'neutral' {
  if (rate === null || rate === undefined) return 'neutral';
  if (rate >= 0.6) return 'good';
  if (rate >= 0.4) return 'warn';
  return 'warn';
}

export default function MlbAccuracySummary({ date }: Props) {
  const [data, setData] = useState<MlbAccuracy | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    fetchMlbAccuracy(date)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [date]);

  if (err) {
    return (
      <div className="border border-red-800/50 bg-red-950/20 text-red-300 text-xs rounded p-3">
        Accuracy unavailable: {err}
      </div>
    );
  }

  if (loading || !data) {
    return (
      <div className="text-xs text-zinc-500 px-1 py-2">Loading accuracy…</div>
    );
  }

  if (!data.available) {
    return (
      <div className="border border-zinc-800/60 bg-zinc-900/30 text-zinc-400 text-xs rounded p-3">
        No projection data recorded for {date} yet.
      </div>
    );
  }

  const k = data.pitcher_ks_ou;
  const h = data.projected_hits;
  const hr = data.projected_homers;

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">
        Accuracy · {data.date}
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Tile
          icon={<Target className="w-3.5 h-3.5" />}
          label="Pitcher Ks O/U Calls"
          primary={`${k.correct}/${k.total} · ${pct(k.accuracy)}`}
          secondary={
            k.mae !== null
              ? `K MAE ${k.mae.toFixed(2)}${k.push ? ` · ${k.push} push` : ''}`
              : k.push
              ? `${k.push} push`
              : 'No graded calls'
          }
          tone={toneForRate(k.accuracy)}
        />
        <Tile
          icon={<CheckCircle2 className="w-3.5 h-3.5" />}
          label="Projected Hits"
          primary={`${h.hits_made}/${h.projected_batters} · ${pct(h.success_rate)}`}
          secondary={`Batters projected to record ≥1 hit`}
          tone={toneForRate(h.success_rate)}
        />
        <Tile
          icon={<AlertCircle className="w-3.5 h-3.5" />}
          label="Projected Home Runs"
          primary={`${hr.hr_hit}/${hr.projected_batters} · ${pct(hr.success_rate)}`}
          secondary={`Batters projected to hit ≥1 HR`}
          tone={toneForRate(hr.success_rate)}
        />
      </div>
    </section>
  );
}
