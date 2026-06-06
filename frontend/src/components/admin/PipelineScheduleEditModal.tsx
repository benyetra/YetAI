'use client';

import { useState } from 'react';
import { X, RotateCcw } from 'lucide-react';
import {
  updatePipelineSchedule,
  resetPipelineSchedule,
  type ScheduledEntry,
} from '@/lib/api/pipelines';

interface Props {
  entry: ScheduledEntry;
  onClose: () => void;
  onSaved: () => void;
}

function firstOrZero(value: number[] | '*' | undefined): number {
  if (Array.isArray(value) && value.length > 0) return value[0];
  return 0;
}

export function PipelineScheduleEditModal({ entry, onClose, onSaved }: Props) {
  // Seed with the entry's current values. We only support single-hour /
  // single-minute editing in v1 — the 7 orchestrators all use that form.
  const [hour, setHour] = useState(firstOrZero(entry.crontab.hour));
  const [minute, setMinute] = useState(firstOrZero(entry.crontab.minute));
  const [enabled, setEnabled] = useState(entry.is_enabled !== false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleSave = async () => {
    setBusy(true);
    setErr(null);
    try {
      await updatePipelineSchedule(entry.key, { hour, minute, enabled });
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleReset = async () => {
    if (!confirm(`Reset "${entry.label}" to default schedule?`)) return;
    setBusy(true);
    setErr(null);
    try {
      await resetPipelineSchedule(entry.key);
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
      <div className="bg-zinc-950 border border-zinc-800 rounded-lg w-full max-w-md text-zinc-100 shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
          <h3 className="text-sm font-medium">{entry.label}</h3>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="text-zinc-500 hover:text-zinc-200 disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <div className="text-[11px] text-zinc-500 font-mono break-all">
            {entry.key}
            <span className="text-zinc-600"> · </span>
            {entry.task_name}
          </div>

          <div className="flex items-end gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-zinc-400">Hour (ET)</label>
              <select
                value={hour}
                onChange={e => setHour(Number(e.target.value))}
                disabled={busy}
                className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm w-20"
              >
                {Array.from({ length: 24 }, (_, h) => (
                  <option key={h} value={h}>
                    {h.toString().padStart(2, '0')}
                  </option>
                ))}
              </select>
            </div>
            <div className="text-zinc-500 pb-1.5">:</div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-zinc-400">Minute</label>
              <select
                value={minute}
                onChange={e => setMinute(Number(e.target.value))}
                disabled={busy}
                className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm w-20"
              >
                {Array.from({ length: 60 }, (_, m) => (
                  <option key={m} value={m}>
                    {m.toString().padStart(2, '0')}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm select-none">
            <input
              type="checkbox"
              checked={enabled}
              onChange={e => setEnabled(e.target.checked)}
              disabled={busy}
            />
            Enabled
          </label>

          {err && (
            <div className="text-xs text-red-400 border border-red-800/50 bg-red-950/30 rounded p-2">
              {err}
            </div>
          )}

          <div className="text-[11px] text-zinc-500">
            Changes take effect within ~30 seconds (next beat sync).
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 p-4 border-t border-zinc-800">
          <button
            type="button"
            onClick={handleReset}
            disabled={busy || !entry.is_overridden}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-30 disabled:cursor-not-allowed"
            title={
              entry.is_overridden
                ? 'Reset to hardcoded default'
                : 'No override to reset'
            }
          >
            <RotateCcw className="w-3 h-3" />
            Reset to default
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="px-3 py-1.5 text-sm border border-zinc-700 rounded hover:bg-zinc-900/50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={busy}
              className="px-3 py-1.5 text-sm bg-purple-600 hover:bg-purple-700 rounded disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
