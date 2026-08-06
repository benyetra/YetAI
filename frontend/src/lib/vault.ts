/**
 * League Vault client — fetches public snapshot from the API.
 */

import { cache } from 'react';

export type VaultManager = {
  id: number;
  slug: string;
  display_name: string;
  canonical_name: string;
  aliases: string[];
  first_season: number | null;
  last_season: number | null;
  is_active: boolean;
};

export type VaultTeam = {
  id: number;
  manager_id: number;
  team_name: string | null;
  avatar_url: string | null;
  wins: number | null;
  losses: number | null;
  ties: number | null;
  points_for: number | null;
  points_against: number | null;
  final_rank: number | null;
  playoff_seed: number | null;
  all_play_wins: number | null;
  all_play_losses: number | null;
  luck_differential: number | null;
  moves: number | null;
};

export type VaultSeason = {
  season: number;
  team_count: number | null;
  playoff_teams: number | null;
  regular_season_weeks: number | null;
  champion: VaultManager | null;
  runner_up: VaultManager | null;
  last_place: VaultManager | null;
  teams: VaultTeam[];
  matchups: Array<{
    week: number;
    is_playoff: boolean;
    team_a_id: number | null;
    team_b_id: number | null;
    team_a_score: number | null;
    team_b_score: number | null;
    winner_team_id: number | null;
    margin: number | null;
  }>;
  drafts: Array<{
    draft_type: string | null;
    status?: string | null;
    rounds: number | null;
    picks_made?: number;
    picks: Array<{
      round: number;
      pick_no: number;
      draft_slot: number | null;
      team_id: number | null;
      player_id: string | null;
      player_name?: string | null;
      player_position?: string | null;
      player_nfl_team?: string | null;
      platform_roster_id?: string | null;
      is_keeper: boolean | null;
      auction_amount: number | null;
    }>;
  }>;
  transaction_count: number;
  transaction_summary?: Record<string, number>;
  transactions_recent?: Array<{
    week: number | null;
    type: string | null;
    status: string | null;
    team_names: string[];
  }>;
};

export type VaultRecord = {
  record_key: string;
  scope: string | null;
  season: number | null;
  manager_id: number | null;
  team_id: number | null;
  value: number;
  context: Record<string, unknown>;
};

export type VaultSnapshot = {
  slug: string;
  display_name: string;
  tagline: string | null;
  first_season: number | null;
  latest_season: number | null;
  last_place_label: string;
  generated_at: string;
  reigning_champion: (VaultManager & { season: number }) | null;
  managers: VaultManager[];
  manager_careers: Record<
    string,
    { wins: number; losses: number; ties: number; points_for: number; titles: number }
  >;
  seasons: VaultSeason[];
  records: VaultRecord[];
  h2h: Record<string, Record<string, { wins: number; losses: number; ties: number }>>;
  dynasty_timeline: Array<{ season: number; champion: VaultManager | null }>;
};

function vaultApiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.replace(/\/$/, '');
  }
  if (process.env.VERCEL_ENV === 'production' || process.env.NODE_ENV === 'production') {
    return 'https://api.yetai.app';
  }
  return 'http://localhost:8000';
}

export const fetchVaultSnapshot = cache(async function fetchVaultSnapshot(
  slug: string,
): Promise<VaultSnapshot | null> {
  const url = `${vaultApiBase()}/api/vault/${encodeURIComponent(slug)}`;
  const res = await fetch(url, {
    next: { revalidate: 300 },
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Vault fetch failed: ${res.status}`);
  }
  return (await res.json()) as VaultSnapshot;
});

export function vaultPath(slug: string, path = ''): string {
  const suffix = path.startsWith('/') ? path : path ? `/${path}` : '';
  return `/vault/${slug}${suffix}`;
}

export function managerById(
  snap: VaultSnapshot,
  id: number | null | undefined,
): VaultManager | undefined {
  if (id == null) return undefined;
  return snap.managers.find((m) => m.id === id);
}

export function formatRecord(value: number, key: string): string {
  if (key.includes('ppg') || key.includes('luck')) return value.toFixed(2);
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2);
}

/** Compact header label for H2H matrix columns. */
export function h2hShortName(name: string): string {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) {
    const w = parts[0];
    return w.length <= 4 ? w : w.slice(0, 4);
  }
  const initials = parts.map((p) => p[0]).join('').toUpperCase();
  return initials.slice(0, 3);
}

export function formatDraftPlayer(pick: {
  player_name?: string | null;
  player_position?: string | null;
  player_nfl_team?: string | null;
  player_id?: string | null;
}): string {
  if (pick.player_name) {
    const bits = [pick.player_name];
    const meta = [pick.player_position, pick.player_nfl_team].filter(Boolean).join(' · ');
    if (meta) bits.push(meta);
    return bits.join(' — ');
  }
  if (!pick.player_id || isPlaceholderPlayerId(pick.player_id)) return '—';
  return pick.player_id;
}

export function isPlaceholderPlayerId(id: string | null | undefined): boolean {
  if (id == null || id === '') return true;
  const s = String(id).trim().toLowerCase();
  if (s === '-1' || s === '0' || s === 'none' || s === 'null') return true;
  const n = Number(s);
  return Number.isFinite(n) && n < 0;
}

/** Overall pick number — prefer pick_no (monotonic). draft_slot is often the slot. */
export function draftOverallPick(pick: {
  pick_no: number;
  draft_slot: number | null;
}): number {
  return pick.pick_no ?? pick.draft_slot ?? 0;
}

export function isDraftPending(
  draft:
    | {
        status?: string | null;
        picks_made?: number;
        picks: Array<{ player_id?: string | null; player_name?: string | null }>;
      }
    | null
    | undefined,
): boolean {
  if (!draft) return true;
  if (draft.status === 'pending' || draft.status === 'empty') return true;
  if (typeof draft.picks_made === 'number') return draft.picks_made === 0;
  if (!draft.picks.length) return true;
  return !draft.picks.some(
    (p) => p.player_name || (p.player_id && !isPlaceholderPlayerId(p.player_id)),
  );
}

/** Latest season that has a completed (or in-progress) draft board. */
export function latestDraftSeason(snap: VaultSnapshot): number | null {
  for (const season of [...snap.seasons].reverse()) {
    const draft = season.drafts[0];
    if (!draft) continue;
    if (!isDraftPending(draft) && draft.picks.length > 0) return season.season;
  }
  return null;
}

export const RECORD_LABELS: Record<string, string> = {
  highest_single_week_score: 'Highest single-week score',
  lowest_single_week_score: 'Lowest single-week score',
  biggest_blowout: 'Biggest blowout',
  closest_game: 'Closest game',
  most_points_in_loss: 'Most points in a loss',
  fewest_points_in_win: 'Fewest points in a win',
  highest_combined_score: 'Highest combined score',
  highest_scoring_season_pf: 'Highest scoring season (PF)',
  highest_scoring_season_ppg: 'Highest scoring season (PPG)',
  best_regular_season_record: 'Best regular-season record',
  worst_regular_season_record: 'Worst regular-season record',
  longest_win_streak: 'Longest win streak',
  longest_losing_streak: 'Longest losing streak',
  titles: 'Most titles',
  career_titles: 'Career titles',
  career_wins: 'Career wins',
  best_all_play_season: 'Best all-play season',
  luckiest_season: 'Luckiest season',
  unluckiest_season: 'Unluckiest season',
};
