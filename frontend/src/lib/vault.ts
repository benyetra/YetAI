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
  champion_asterisk?: boolean;
  champion_marker?: string | null;
  champion_note?: string | null;
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
  dynasty_timeline: Array<{
    season: number;
    champion: VaultManager | null;
    champion_asterisk?: boolean;
    champion_marker?: string | null;
    champion_note?: string | null;
  }>;
  title_footnotes?: Array<{ season: number; marker: string; note: string }>;
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

/**
 * Class list for display names so long handles shrink / ellipsize
 * instead of breaking mid-word (e.g. "thetylerwong").
 */
export function vaultNameFitClass(name: string | null | undefined): string {
  const n = (name || '').trim();
  if (!n) return 'vault-name';
  const tokens = n.split(/\s+/).filter(Boolean);
  const longest = tokens.reduce((max, token) => Math.max(max, token.length), 0);
  const multiWord = tokens.length > 1;

  if (!multiWord && longest >= 16) return 'vault-name is-micro';
  if (!multiWord && longest >= 12) return 'vault-name is-tight';
  if (!multiWord && longest >= 9) return 'vault-name is-compact';
  if (multiWord && (n.length >= 24 || longest >= 14)) return 'vault-name is-tight';
  if (multiWord && (n.length >= 18 || longest >= 11)) return 'vault-name is-compact';
  return 'vault-name';
}

function ctxNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function scoresClose(a: number | null, b: number | null, tol = 1e-6): boolean {
  if (a == null || b == null) return false;
  return Math.abs(a - b) <= tol;
}

export type VaultRecordMatchupParties = {
  managerA: VaultManager;
  managerB: VaultManager;
  scoreA: number | null;
  scoreB: number | null;
};

/** Resolve both managers for a matchup-derived record (closest, combined, etc.). */
export function resolveRecordMatchup(
  snap: VaultSnapshot,
  record: VaultRecord,
): VaultRecordMatchupParties | null {
  const ctx = record.context || {};
  const managerA = managerById(snap, ctxNumber(ctx.manager_a_id));
  const managerB = managerById(snap, ctxNumber(ctx.manager_b_id));
  if (managerA && managerB) {
    return {
      managerA,
      managerB,
      scoreA: ctxNumber(ctx.team_a_score),
      scoreB: ctxNumber(ctx.team_b_score),
    };
  }

  const season = ctxNumber(ctx.season) ?? record.season;
  const week = ctxNumber(ctx.week);
  if (season == null || week == null) return null;
  const seasonRow = snap.seasons.find((s) => s.season === season);
  if (!seasonRow) return null;

  const scoreA = ctxNumber(ctx.team_a_score);
  const scoreB = ctxNumber(ctx.team_b_score);
  const focalTeamId = ctxNumber(ctx.team_id) ?? record.team_id;
  const match =
    seasonRow.matchups.find(
      (m) =>
        m.week === week &&
        scoresClose(m.team_a_score, scoreA) &&
        scoresClose(m.team_b_score, scoreB),
    ) ??
    seasonRow.matchups.find(
      (m) =>
        m.week === week &&
        focalTeamId != null &&
        (m.team_a_id === focalTeamId || m.team_b_id === focalTeamId),
    );
  if (!match?.team_a_id || !match?.team_b_id) return null;

  const teamA = seasonRow.teams.find((t) => t.id === match.team_a_id);
  const teamB = seasonRow.teams.find((t) => t.id === match.team_b_id);
  const resolvedA = managerById(snap, teamA?.manager_id);
  const resolvedB = managerById(snap, teamB?.manager_id);
  if (!resolvedA || !resolvedB) return null;
  return {
    managerA: resolvedA,
    managerB: resolvedB,
    scoreA: match.team_a_score,
    scoreB: match.team_b_score,
  };
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

/** Short explainers for record-book rows (shown via VaultHelp). */
export const RECORD_HELP: Record<string, string> = {
  highest_single_week_score: 'Most fantasy points scored by one team in a single week.',
  lowest_single_week_score: 'Fewest fantasy points scored by one team in a single week.',
  biggest_blowout: 'Largest point margin between winner and loser in one matchup.',
  closest_game: 'Smallest point margin in a decided matchup.',
  most_points_in_loss: 'Highest score that still lost — tough-luck high-scoring defeat.',
  fewest_points_in_win: 'Lowest score that still won — a grind-it-out victory.',
  highest_combined_score: 'Most total points scored by both teams in one matchup.',
  highest_scoring_season_pf: 'Most points for across a full season.',
  highest_scoring_season_ppg: 'Highest average points per game in a season.',
  best_regular_season_record: 'Best win-loss mark before the playoffs.',
  worst_regular_season_record: 'Worst win-loss mark before the playoffs.',
  longest_win_streak: 'Most consecutive wins, including playoffs when available.',
  longest_losing_streak: 'Most consecutive losses, including playoffs when available.',
  titles: 'Most championships across finished seasons.',
  career_titles: 'Championships won across a manager’s full vault history.',
  career_wins: 'Regular-season and playoff wins tallied across seasons.',
  best_all_play_season:
    'Best record if every team played every other team each week — schedule-neutral strength.',
  luckiest_season:
    'Largest positive gap between actual wins and expected wins from all-play (schedule luck).',
  unluckiest_season:
    'Largest negative gap between actual wins and expected wins from all-play (schedule misfortune).',
};

/** Column / section explainers for standings, managers, and matrix pages. */
export const COLUMN_HELP = {
  all_play:
    'Wins and losses if every team faced every other team each week — removes schedule strength.',
  luck: 'Actual wins minus expected wins from all-play. Positive means the schedule helped.',
  pf: 'Points for — total fantasy points scored.',
  titles: 'Championships in finished seasons recorded in this vault.',
  record: 'Career win-loss(-tie) across seasons this manager appears in.',
  seasons_span: 'First and last season this manager appears in the vault.',
  h2h_matrix:
    'Each cell is the row manager’s all-time record against the column manager (W-L or W-L-T).',
  moves_total: 'Counted roster transactions for the season (waivers, free agents, trades, etc.).',
  moves_breakdown: 'Transaction counts by type when the platform provides them.',
  draft_overall: 'Overall pick number on the draft board (1.01 style ordering).',
} as const;

export const PAGE_HELP = {
  trophies: 'Championships, runners-up, and the league’s last-place honor for every finished year.',
  records: 'Career and single-season peaks — including all-play strength and schedule luck.',
  managers: 'Every owner in the archive with career record and title count.',
  seasons: 'Jump into a year for standings, scoreboard, and that season’s draft board.',
  h2h: 'All-time rivalry matrix. Use the numbered roster key for column names, then read across a row.',
  moves: 'Season-by-season waiver, free-agent, and trade activity from the league history.',
  draft: 'Pick-by-pick board for this season — overall order, round, team, and player.',
} as const;
