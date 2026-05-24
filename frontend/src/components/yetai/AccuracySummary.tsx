'use client';

import { useEffect, useState } from 'react';
import { Target } from 'lucide-react';
import {
  fetchAccuracy,
  type AccuracyBucket,
  type AccuracySport,
  type AccuracySummary as Summary,
  type AccuracyTone,
} from '@/lib/api/accuracy';

interface Props {
  sport: AccuracySport;
  date: string;
}

function Tile({ bucket }: { bucket: AccuracyBucket }) {
  const ringByTone: Record<AccuracyTone, string> = {
    good: 'border-emerald-700/40 bg-emerald-950/20',
    warn: 'border-amber-700/40 bg-amber-950/20',
    neutral: 'border-zinc-800 bg-zinc-900/40',
  };
  const accentByTone: Record<AccuracyTone, string> = {
    good: 'text-emerald-300',
    warn: 'text-amber-300',
    neutral: 'text-zinc-200',
  };
  return (
    <div
      className={`rounded-lg border ${ringByTone[bucket.tone]} p-4 flex flex-col gap-2`}
    >
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-zinc-400">
        <Target className="w-3.5 h-3.5" />
        <span>{bucket.label}</span>
      </div>
      <div className={`text-2xl font-semibold ${accentByTone[bucket.tone]}`}>
        {bucket.primary}
      </div>
      <div className="text-xs text-zinc-500">{bucket.secondary}</div>
    </div>
  );
}

export default function AccuracySummary({ sport, date }: Props) {
  const [data, setData] = useState<Summary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    fetchAccuracy(sport, date)
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
  }, [sport, date]);

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

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">
        Accuracy · {data.date}
      </h2>
      <div
        className="grid grid-cols-1 gap-3"
        // Match the bucket count to the column count up to 4-wide.
        style={{
          gridTemplateColumns: `repeat(auto-fit, minmax(220px, 1fr))`,
        }}
      >
        {data.buckets.map((b) => (
          <Tile key={b.key} bucket={b} />
        ))}
      </div>
    </section>
  );
}
