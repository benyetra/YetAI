/** Formatting helpers aligned with YetAI design prototype */

import { teamPrimaryColor } from '@/lib/team-colors';

export function teamAbbr(name: string): string {
  const known: Record<string, string> = {
    'Boston Celtics': 'BOS',
    'Indiana Pacers': 'IND',
    'Oklahoma City Thunder': 'OKC',
    'Minnesota Timberwolves': 'MIN',
    'New York Yankees': 'NYY',
    'Boston Red Sox': 'RED',
    'Los Angeles Dodgers': 'LAD',
    'San Francisco Giants': 'SFG',
    'Philadelphia 76ers': 'PHI',
    'New York Knicks': 'NYK',
    'Chicago Cubs': 'CHC',
    'New York Mets': 'NYM',
    'Real Madrid': 'RMA',
    'Manchester City': 'MAN',
  };
  if (known[name]) return known[name];
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1].slice(0, 2)).toUpperCase().slice(0, 3);
  }
  return name.slice(0, 3).toUpperCase();
}

export function teamColor(
  teamNameOrAbbr: string,
  opts: { name?: string; league?: string; sportKey?: string; abbr?: string } = {},
): string {
  const label = opts.name?.trim() || teamNameOrAbbr.trim();
  return teamPrimaryColor(label, {
    league: opts.league,
    sportKey: opts.sportKey,
    abbr: opts.abbr || teamNameOrAbbr,
  });
}

export function fmtOdds(n: number | string): string {
  const num = typeof n === 'string' ? parseFloat(n.replace(/[^0-9.+-]/g, '')) : n;
  if (Number.isNaN(num)) return String(n);
  return num > 0 ? `+${num}` : `${num}`;
}

export function fmtMoney(
  n: number,
  opts: { signed?: boolean; decimals?: number } = {}
): string {
  const sign = n < 0 ? '-' : opts.signed && n > 0 ? '+' : '';
  return (
    sign +
    '$' +
    Math.abs(n).toLocaleString(undefined, {
      minimumFractionDigits: opts.decimals ?? 2,
      maximumFractionDigits: opts.decimals ?? 2,
    })
  );
}

export function fmtMoneyShort(n: number): string {
  return '$' + n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function parseOddsValue(odds: string | number): number {
  if (typeof odds === 'number') return odds;
  const cleaned = odds.replace(/[^0-9.+-]/g, '');
  return parseFloat(cleaned) || -110;
}

export function calcPayout(odds: number, stake: number): number {
  if (odds > 0) return stake + stake * (odds / 100);
  return stake + stake * (100 / Math.abs(odds));
}
