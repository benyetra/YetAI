'use client';

import { useState } from 'react';
import { approvePick, rejectPick, editPick, type PendingPick } from '@/lib/api/yetai-picks';
import { CheckCircle, XCircle, Edit2 } from 'lucide-react';

const TIER_COLORS: Record<string, string> = {
  free: 'bg-gray-100 text-gray-700',
  pro: 'bg-yellow-100 text-yellow-800',
  elite: 'bg-purple-100 text-purple-800',
};

export function PendingPickCard({
  pick,
  onChanged,
}: {
  pick: PendingPick;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const handle = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      onChanged();
    } catch (err) {
      console.error('Pick action failed:', err);
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleEditReasoning = () => {
    const next = prompt('New reasoning:', pick.reasoning ?? '');
    if (next !== null) {
      handle(() => editPick(pick.id, { reasoning: next }));
    }
  };

  const tierClass = TIER_COLORS[pick.tier_requirement] ?? TIER_COLORS.free;
  const scoreDisplay =
    pick.confidence_score != null ? pick.confidence_score.toFixed(1) : '—';

  return (
    <div className="rounded-lg border border-[var(--border)] p-4 bg-white shadow-sm">
      {/* Header row */}
      <div className="flex justify-between items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-xs uppercase text-gray-500 mb-1">
            {pick.sport && <span>{pick.sport}</span>}
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded-full font-medium ${tierClass}`}
            >
              {pick.tier_requirement}
            </span>
            {pick.source === 'auto' && (
              <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                auto
              </span>
            )}
          </div>
          <div className="font-semibold text-base leading-snug">
            {pick.title || pick.selection || '(untitled)'}
          </div>
          {pick.selection && pick.title && (
            <div className="text-sm text-gray-600 mt-0.5">
              {pick.selection}
              {pick.odds != null ? ` · Odds: ${pick.odds}` : ''}
            </div>
          )}
          {!pick.title && pick.odds != null && (
            <div className="text-sm text-gray-600 mt-0.5">Odds: {pick.odds}</div>
          )}
        </div>

        {/* Confidence score */}
        <div className="text-right shrink-0">
          <div className="text-3xl font-mono font-bold tabular-nums leading-none">
            {scoreDisplay}
          </div>
          <div className="text-xs text-gray-500 mt-0.5">confidence</div>
        </div>
      </div>

      {/* Reasoning */}
      {pick.reasoning && (
        <p className="mt-3 text-sm text-gray-700 leading-relaxed">{pick.reasoning}</p>
      )}

      {/* Score breakdown */}
      {pick.score_breakdown && Object.keys(pick.score_breakdown).length > 0 && (
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer text-gray-500 select-none hover:text-gray-700">
            Score breakdown
          </summary>
          <pre className="bg-gray-50 border border-[var(--border)] p-2 mt-1 rounded overflow-x-auto">
            {JSON.stringify(pick.score_breakdown, null, 2)}
          </pre>
        </details>
      )}

      {/* Actions */}
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          disabled={busy}
          onClick={() => handle(() => approvePick(pick.id))}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <CheckCircle className="w-4 h-4" />
          Approve
        </button>

        <button
          disabled={busy}
          onClick={() => handle(() => rejectPick(pick.id))}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <XCircle className="w-4 h-4" />
          Reject
        </button>

        <button
          disabled={busy}
          onClick={handleEditReasoning}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gray-200 text-gray-800 text-sm rounded hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <Edit2 className="w-4 h-4" />
          Edit reasoning
        </button>
      </div>
    </div>
  );
}
