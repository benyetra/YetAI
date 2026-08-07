'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState, useTransition } from 'react';
import { vaultNameFitClass, vaultPath } from '../../lib/vault';

export type LotteryEntry = {
  pick?: number;
  team_id: number;
  team_name?: string | null;
  manager_id: number;
  manager_slug?: string | null;
  display_name: string;
  final_rank?: number | null;
  playoff_finish?: number | null;
  combinations?: number | null;
  chance_pct?: number | null;
  group: string;
  via?: string;
};

export type LotteryPayload = {
  upcoming_season: number;
  source_season: number;
  status: 'ready' | 'drawn';
  lottery_picks: number;
  drawn_at?: string | null;
  already_drawn?: boolean;
  seed_snapshot: {
    odds_note?: string;
    lottery_field: LotteryEntry[];
    playoff_block: LotteryEntry[];
  };
  drawn_order: LotteryEntry[] | null;
};

function ManagerLink({
  slug,
  managerSlug,
  name,
}: {
  slug: string;
  managerSlug?: string | null;
  name: string;
}) {
  if (!managerSlug) {
    return (
      <span className={vaultNameFitClass(name)} title={name}>
        {name}
      </span>
    );
  }
  return (
    <Link
      href={vaultPath(slug, `/managers/${managerSlug}`)}
      className={vaultNameFitClass(name)}
      title={name}
    >
      {name}
    </Link>
  );
}

export function DraftLotteryClient({
  slug,
  initial,
  apiBase,
}: {
  slug: string;
  initial: LotteryPayload;
  apiBase: string;
}) {
  const router = useRouter();
  const [payload, setPayload] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const drawn = payload.status === 'drawn' && payload.drawn_order;

  const onRun = () => {
    if (drawn || pending) return;
    const confirmed = window.confirm(
      `Run the ${payload.upcoming_season} draft lottery now?\n\nThis can only run once — the order will be locked forever.`,
    );
    if (!confirmed) return;
    setError(null);
    startTransition(async () => {
      try {
        const url = `${apiBase}/api/vault/${encodeURIComponent(slug)}/lottery/run`;
        const res = await fetch(url, { method: 'POST' });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `Lottery failed (${res.status})`);
        }
        const next = (await res.json()) as LotteryPayload;
        setPayload(next);
        router.refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Lottery failed');
      }
    });
  };

  return (
    <div className="vault-lottery">
      <p className="vault-muted vault-lottery-note">
        {payload.seed_snapshot.odds_note}
      </p>

      {!drawn ? (
        <div className="vault-lottery-actions">
          <button
            type="button"
            className="vault-lottery-run"
            onClick={onRun}
            disabled={pending}
          >
            {pending ? 'Drawing…' : `Run ${payload.upcoming_season} lottery`}
          </button>
          <p className="vault-muted">
            One shot only. Classic NBA ping-pong odds for picks 1–
            {payload.lottery_picks}; playoff teams fill the back of the board.
          </p>
        </div>
      ) : (
        <p className="vault-lottery-locked">
          Locked {payload.drawn_at ? `· drawn ${payload.drawn_at.slice(0, 10)}` : null}
          {payload.already_drawn ? ' · already drawn' : null}
        </p>
      )}

      {error ? <p className="vault-lottery-error">{error}</p> : null}

      {drawn ? (
        <section className="vault-section" aria-labelledby="drawn-order-heading">
          <div className="vault-section-heading">
            <h2 id="drawn-order-heading">{payload.upcoming_season} draft order</h2>
            <p className="vault-muted">Final board after the lottery draw.</p>
          </div>
          <ol className="vault-lottery-order">
            {payload.drawn_order!.map((row) => (
              <li
                key={`${row.pick}-${row.manager_id}`}
                className={`vault-lottery-pick is-${row.group}${
                  row.via === 'lottery' ? ' is-lottery-win' : ''
                }`}
              >
                <span className="vault-lottery-pick-num vault-num">#{row.pick}</span>
                <span className="vault-lottery-pick-body">
                  <ManagerLink
                    slug={slug}
                    managerSlug={row.manager_slug}
                    name={row.display_name}
                  />
                  <span className="vault-muted">
                    {row.team_name || '—'}
                    {row.via === 'lottery'
                      ? ' · lottery'
                      : row.via === 'lottery_fallback'
                        ? ' · lottery order'
                        : ' · playoff reverse'}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section className="vault-section" aria-labelledby="odds-heading">
        <div className="vault-section-heading">
          <h2 id="odds-heading">Lottery odds</h2>
          <p className="vault-muted">
            Non-playoff teams from {payload.source_season}, worst → best. Combinations
            out of 1,000 (classic NBA table).
          </p>
        </div>
        <table className="vault-table">
          <thead>
            <tr>
              <th className="vault-col-num">Seed</th>
              <th>Manager</th>
              <th>Team</th>
              <th className="vault-col-num">Balls</th>
              <th className="vault-col-num">#1 odds</th>
            </tr>
          </thead>
          <tbody>
            {payload.seed_snapshot.lottery_field.map((row, i) => (
              <tr key={row.manager_id}>
                <td className="vault-num">{i + 1}</td>
                <td>
                  <ManagerLink
                    slug={slug}
                    managerSlug={row.manager_slug}
                    name={row.display_name}
                  />
                </td>
                <td>{row.team_name || '—'}</td>
                <td className="vault-num">{row.combinations ?? '—'}</td>
                <td className="vault-num">
                  {row.chance_pct != null ? `${row.chance_pct}%` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="vault-section" aria-labelledby="playoff-heading">
        <div className="vault-section-heading">
          <h2 id="playoff-heading">Playoff reverse order</h2>
          <p className="vault-muted">
            These six (or fewer) draft after the lottery field — earliest exit first,
            champion last.
          </p>
        </div>
        <ol className="vault-lottery-playoff-list">
          {payload.seed_snapshot.playoff_block.map((row, i) => (
            <li key={row.manager_id}>
              <span className="vault-muted">{i + 1}.</span>{' '}
              <ManagerLink
                slug={slug}
                managerSlug={row.manager_slug}
                name={row.display_name}
              />
              <span className="vault-muted">
                {' '}
                · {row.team_name || '—'}
                {row.playoff_finish != null
                  ? ` · finished #${row.playoff_finish}`
                  : row.final_rank != null
                    ? ` · RS #${row.final_rank}`
                    : ''}
              </span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
