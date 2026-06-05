/** Team primary/secondary colors synced from ESPN (see sync_team_colors.py). */

import {
  TEAM_COLOR_REGISTRY,
  type TeamColorLeague,
  type TeamColorPair,
} from '@/lib/team-colors-registry.generated';
import { inferLogoLeague, normalizeTeamSlug } from '@/lib/team-logos';

export type { TeamColorLeague, TeamColorPair };

const DEFAULT_COLORS: TeamColorPair = {
  primary: '#444444',
  secondary: '#888888',
};

export function teamColors(
  teamNameOrAbbr: string,
  opts: { league?: string; sportKey?: string; abbr?: string } = {},
): TeamColorPair {
  const name = teamNameOrAbbr.trim();
  if (!name) return DEFAULT_COLORS;

  const colorLeague = inferLogoLeague(opts.league, opts.sportKey);
  if (!colorLeague) return DEFAULT_COLORS;

  const reg = TEAM_COLOR_REGISTRY[colorLeague as TeamColorLeague];
  if (!reg) return DEFAULT_COLORS;

  const slug = normalizeTeamSlug(name);
  if (slug && reg.byName[slug]) return reg.byName[slug];

  const upper = (opts.abbr || name).trim().toUpperCase();
  if (upper.length <= 4 && reg.byAbbr[upper]) return reg.byAbbr[upper];

  return DEFAULT_COLORS;
}

export function teamPrimaryColor(
  teamNameOrAbbr: string,
  opts: { league?: string; sportKey?: string; abbr?: string } = {},
): string {
  return teamColors(teamNameOrAbbr, opts).primary;
}

export function teamSecondaryColor(
  teamNameOrAbbr: string,
  opts: { league?: string; sportKey?: string; abbr?: string } = {},
): string {
  return teamColors(teamNameOrAbbr, opts).secondary;
}

/** CSS variables for team-themed surfaces (dark UI safe). */
export function teamColorStyle(
  teamNameOrAbbr: string,
  opts: { league?: string; sportKey?: string; abbr?: string } = {},
): Record<string, string> {
  const { primary, secondary } = teamColors(teamNameOrAbbr, opts);
  return {
    '--team-primary': primary,
    '--team-secondary': secondary,
  };
}
