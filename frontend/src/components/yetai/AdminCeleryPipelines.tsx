'use client';

import { useCallback, useEffect, useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { Activity, Loader2, Play, RefreshCw } from 'lucide-react';

type EnqueueTask = {
  task_name: string;
  label: string;
  sport: string;
  description: string;
};

type EnqueueResult = {
  task_name: string;
  task_id: string;
  at: string;
};

export default function AdminCeleryPipelines() {
  const [tasks, setTasks] = useState<EnqueueTask[]>([]);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [enqueueing, setEnqueueing] = useState<string | null>(null);
  const [pingStatus, setPingStatus] = useState<string | null>(null);
  const [checkingPing, setCheckingPing] = useState(false);
  const [lastEnqueue, setLastEnqueue] = useState<EnqueueResult | null>(null);
  const [verifyReport, setVerifyReport] = useState<Record<string, unknown> | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authHeaders = useCallback((): HeadersInit => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
  }, []);

  const loadCatalog = useCallback(async () => {
    setLoadingCatalog(true);
    setError(null);
    try {
      const res = await fetch(getApiUrl('/api/admin/celery/pipeline-catalog'), {
        headers: authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || res.statusText);
      }
      setTasks(data.enqueue_tasks ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load pipeline catalog');
    } finally {
      setLoadingCatalog(false);
    }
  }, [authHeaders]);

  useEffect(() => {
    loadCatalog();
  }, [loadCatalog]);

  const checkWorkerPing = async () => {
    setCheckingPing(true);
    setPingStatus(null);
    setError(null);
    try {
      const res = await fetch(getApiUrl('/api/admin/celery/health'), {
        headers: authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || res.statusText);
      }
      const ping = data.ping?.status ?? 'unknown';
      setPingStatus(ping === 'ok' ? 'Worker reachable (ping OK)' : `Ping: ${ping}`);
    } catch (e) {
      setPingStatus(null);
      setError(e instanceof Error ? e.message : 'Celery health check failed');
    } finally {
      setCheckingPing(false);
    }
  };

  const verifyProduction = async (enqueueAll: boolean) => {
    setVerifying(true);
    setError(null);
    setVerifyReport(null);
    try {
      const res = await fetch(getApiUrl('/api/admin/celery/verify-etl'), {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ enqueue_all: enqueueAll, wait_seconds: 0 }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || res.statusText);
      }
      setVerifyReport(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Verification failed');
    } finally {
      setVerifying(false);
    }
  };

  const enqueuePipeline = async (task: EnqueueTask) => {
    setEnqueueing(task.task_name);
    setError(null);
    try {
      const res = await fetch(getApiUrl('/api/admin/celery/enqueue-task'), {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ task_name: task.task_name }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || res.statusText);
      }
      setLastEnqueue({
        task_name: data.task_name,
        task_id: data.task_id,
        at: new Date().toISOString(),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Enqueue failed');
    } finally {
      setEnqueueing(null);
    }
  };

  return (
    <section className="card">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-xl font-semibold flex items-center gap-2">
            <Activity className="w-5 h-5" />
            ETL pipelines (Celery)
          </h2>
          <p className="text-sm muted mt-1 max-w-xl">
            Enqueue full sport pipelines on the Railway worker. Runs in the background — check worker logs for{' '}
            <code className="text-xs">partial_failure</code> and per-task errors.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={checkWorkerPing}
            disabled={checkingPing}
            className="chip"
          >
            {checkingPing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            Test worker
          </button>
          <button type="button" onClick={loadCatalog} disabled={loadingCatalog} className="chip">
            Reload
          </button>
          <button
            type="button"
            onClick={() => verifyProduction(false)}
            disabled={verifying}
            className="chip"
          >
            {verifying ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Verify data
          </button>
          <button
            type="button"
            onClick={() => verifyProduction(true)}
            disabled={verifying}
            className="btn btn-primary"
            style={{ fontSize: 13 }}
          >
            Enqueue all + verify
          </button>
        </div>
      </div>

      {pingStatus && (
        <p className="text-sm mb-3" style={{ color: 'var(--win)' }}>
          {pingStatus}
        </p>
      )}
      {error && <p className="text-sm mb-3 alert alert-error">{error}</p>}
      {verifyReport && (
        <div className="mb-4 p-3 rounded-lg border border-[var(--border)] text-xs mono overflow-auto max-h-64">
          <p className="text-sm font-medium mb-2" style={{ fontFamily: 'inherit' }}>
            Verification — overall:{' '}
            {(verifyReport.verification as { overall?: string })?.overall ?? 'unknown'}
          </p>
          <pre className="whitespace-pre-wrap break-all">
            {JSON.stringify(verifyReport.verification, null, 2)}
          </pre>
        </div>
      )}
      {lastEnqueue && (
        <div className="mb-4 p-3 rounded-lg border border-[var(--border)] bg-[color-mix(in_oklab,var(--accent)_8%,transparent)]">
          <p className="text-sm font-medium">Last enqueue</p>
          <p className="text-xs mono dim mt-1">{lastEnqueue.task_name}</p>
          <p className="text-xs mono mt-1">
            task_id: {lastEnqueue.task_id}
          </p>
          <p className="text-xs dim mt-1">{new Date(lastEnqueue.at).toLocaleString()}</p>
        </div>
      )}

      {loadingCatalog ? (
        <p className="dim text-sm flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading pipelines…
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {tasks.map((task) => (
            <article
              key={task.task_name}
              className="card card-tight flex flex-col gap-3"
              style={{ padding: 14 }}
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="badge">{task.sport.toUpperCase()}</span>
                  <h3 className="font-semibold text-sm">{task.label}</h3>
                </div>
                <p className="text-xs muted mt-2">{task.description}</p>
              </div>
              <button
                type="button"
                onClick={() => enqueuePipeline(task)}
                disabled={enqueueing !== null}
                className="btn btn-primary w-full flex items-center justify-center gap-2"
                style={{ fontSize: 13 }}
              >
                {enqueueing === task.task_name ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
                Enqueue pipeline
              </button>
            </article>
          ))}
        </div>
      )}

      <p className="text-xs dim mt-4">
        Do not use <code>celery call</code> over SSH — it blocks until the pipeline finishes (~10–30+ min) and
        fails if Redis is slow. Use this UI or{' '}
        <code>POST /api/admin/celery/enqueue-task</code> instead.
      </p>
    </section>
  );
}
