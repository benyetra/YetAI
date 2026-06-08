/**
 * Normalize Sleeper league rules API payloads for fantasy UI + Trade Analyzer.
 */

export interface LeagueRules {
  league_id: string;
  league_name: string;
  platform: string;
  season: number;
  /** Roster size label, e.g. "12-Team League" */
  league_type: string;
  /** redraft | keeper | dynasty */
  format_type?: 'redraft' | 'keeper' | 'dynasty';
  format_label?: string;
  is_dynasty?: boolean;
  is_keeper?: boolean;
  is_redraft?: boolean;
  team_count: number;
  scoring_type?: string;
  roster_settings: {
    total_spots: number;
    starting_spots: number;
    bench_spots: number;
    positions: Record<string, number>;
    position_requirements: string[];
  };
  scoring_settings: {
    type: string;
    passing: {
      touchdowns: number;
      yards_per_point: number;
      interceptions: number;
    };
    rushing: {
      touchdowns: number;
      yards_per_point: number;
      fumbles: number;
    };
    receiving: {
      touchdowns: number;
      yards_per_point: number;
      receptions: number;
    };
    special_scoring: string[];
    raw_settings: Record<string, unknown>;
  };
  features: {
    trades_enabled: boolean;
    waivers_enabled: boolean;
    waiver_type?: string;
    waiver_budget?: number;
    playoffs: {
      teams: number;
      weeks: number;
    };
  };
  ai_context: {
    prioritize_volume: boolean;
    rb_premium: boolean;
    flex_strategy: boolean;
    superflex: boolean;
    dynasty: boolean;
    position_scarcity: Record<string, number>;
  };
}

function countStartingPositions(rosterPositions: string[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const pos of rosterPositions) {
    if (pos === 'BN' || pos === 'IR') {
      continue;
    }
    counts[pos] = (counts[pos] || 0) + 1;
  }
  return counts;
}

function inferScoringType(receptions: number): string {
  if (receptions >= 1) {
    return 'ppr';
  }
  if (receptions >= 0.5) {
    return 'half_ppr';
  }
  return 'standard';
}

function buildAiContext(
  rosterPositions: string[],
  scoringType: string,
  formatFlags: {
    is_dynasty?: boolean;
    is_keeper?: boolean;
  }
): LeagueRules['ai_context'] {
  const hasFlex = rosterPositions.includes('FLEX');
  const hasSuperflex = rosterPositions.some(
    (pos) => pos === 'SUPER_FLEX' || pos === 'SUPERFLEX'
  );

  return {
    prioritize_volume: scoringType === 'ppr' || scoringType === 'half_ppr',
    rb_premium: scoringType === 'standard' && !formatFlags.is_dynasty,
    flex_strategy: hasFlex,
    superflex: hasSuperflex,
    dynasty: Boolean(formatFlags.is_dynasty),
    position_scarcity: {},
  };
}

function inferFormatFromSettings(settings: Record<string, unknown> | undefined): {
  format_type: 'redraft' | 'keeper' | 'dynasty';
  is_dynasty: boolean;
  is_keeper: boolean;
  is_redraft: boolean;
  format_label: string;
} {
  const rawType = Number(settings?.type ?? 0);
  let format_type: 'redraft' | 'keeper' | 'dynasty' = 'redraft';
  if (rawType === 2) {
    format_type = 'dynasty';
  } else if (rawType === 1) {
    format_type = 'keeper';
  }
  return {
    format_type,
    is_dynasty: format_type === 'dynasty',
    is_keeper: format_type === 'keeper',
    is_redraft: format_type === 'redraft',
    format_label: format_type.charAt(0).toUpperCase() + format_type.slice(1),
  };
}

/** Dev-only mock rules when NEXT_PUBLIC_FANTASY_MOCK_RULES=1 */
export function getMockLeagueRules(leagueId: string): LeagueRules {
  return {
    league_id: leagueId,
    league_name: 'Mock Dev League',
    platform: 'sleeper',
    season: new Date().getFullYear(),
    league_type: '12-Team League',
    team_count: 12,
    scoring_type: 'ppr',
    roster_settings: {
      total_spots: 16,
      starting_spots: 9,
      bench_spots: 7,
      positions: { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, K: 1, DEF: 1 },
      position_requirements: ['1 QB', '2 RB', '2 WR', '1 TE', '1 FLEX'],
    },
    scoring_settings: {
      type: 'ppr',
      passing: { touchdowns: 4, yards_per_point: 0.04, interceptions: -2 },
      rushing: { touchdowns: 6, yards_per_point: 0.1, fumbles: -2 },
      receiving: { touchdowns: 6, yards_per_point: 0.1, receptions: 1 },
      special_scoring: [],
      raw_settings: {},
    },
    features: {
      trades_enabled: true,
      waivers_enabled: true,
      waiver_type: 'FAAB',
      waiver_budget: 100,
      playoffs: { teams: 6, weeks: 3 },
    },
    format_type: 'redraft',
    format_label: 'Redraft',
    is_dynasty: false,
    is_keeper: false,
    is_redraft: true,
    ai_context: {
      prioritize_volume: true,
      rb_premium: false,
      flex_strategy: true,
      superflex: false,
      dynasty: false,
      position_scarcity: {},
    },
  };
}

export function normalizeLeagueRules(
  leagueId: string,
  apiRules: Record<string, any>
): LeagueRules {
  const rosterPositions: string[] = apiRules.roster_positions || [];
  const rosterConfig = apiRules.roster_config || {};
  const scoringSettings = apiRules.scoring_settings || {};
  const receiving = scoringSettings.receiving || {};
  const receptions = Number(receiving.receptions ?? 0);
  const scoringType =
    apiRules.scoring_type?.toLowerCase?.() || inferScoringType(receptions);
  const normalizedScoringType =
    scoringType === 'ppr' || scoringType === 'half_ppr' || scoringType === 'standard'
      ? scoringType
      : inferScoringType(receptions);

  const positions = countStartingPositions(rosterPositions);
  const playoffSettings = apiRules.playoff_settings || {};
  const waiverSettings = apiRules.waiver_settings || {};
  const leagueFeatures = apiRules.league_features || {};
  const inferredFormat =
    apiRules.format_type != null
      ? {
          format_type: apiRules.format_type as 'redraft' | 'keeper' | 'dynasty',
          is_dynasty: Boolean(apiRules.is_dynasty),
          is_keeper: Boolean(apiRules.is_keeper),
          is_redraft: Boolean(apiRules.is_redraft ?? !apiRules.is_dynasty),
          format_label:
            apiRules.format_label ||
            String(apiRules.format_type).charAt(0).toUpperCase() +
              String(apiRules.format_type).slice(1),
        }
      : inferFormatFromSettings(apiRules.settings);

  return {
    league_id: leagueId,
    league_name: apiRules.league_name || 'Unknown League',
    platform: (apiRules.platform || 'sleeper').toLowerCase(),
    season: Number(apiRules.season) || new Date().getFullYear(),
    league_type: apiRules.league_type || `${apiRules.total_rosters || 12}-Team League`,
    format_type: inferredFormat.format_type,
    format_label: inferredFormat.format_label,
    is_dynasty: inferredFormat.is_dynasty,
    is_keeper: inferredFormat.is_keeper,
    is_redraft: inferredFormat.is_redraft,
    team_count: Number(apiRules.total_rosters || apiRules.teams_count || 12),
    scoring_type: normalizedScoringType,
    roster_settings: {
      total_spots: Number(rosterConfig.total_spots || rosterPositions.length || 0),
      starting_spots: Number(
        rosterConfig.starting_spots ||
          rosterPositions.filter((p: string) => p !== 'BN' && p !== 'IR').length
      ),
      bench_spots: Number(
        rosterConfig.bench_spots ||
          rosterPositions.filter((p: string) => p === 'BN' || p === 'IR').length
      ),
      positions,
      position_requirements: apiRules.position_requirements || [],
    },
    scoring_settings: {
      type: normalizedScoringType,
      passing: {
        touchdowns: Number(scoringSettings.passing?.touchdowns ?? 4),
        yards_per_point: Number(scoringSettings.passing?.yards_per_point ?? 0.04),
        interceptions: Number(scoringSettings.passing?.interceptions ?? -2),
      },
      rushing: {
        touchdowns: Number(scoringSettings.rushing?.touchdowns ?? 6),
        yards_per_point: Number(scoringSettings.rushing?.yards_per_point ?? 0.1),
        fumbles: Number(scoringSettings.rushing?.fumbles ?? -2),
      },
      receiving: {
        touchdowns: Number(receiving.touchdowns ?? 6),
        yards_per_point: Number(receiving.yards_per_point ?? 0.1),
        receptions,
      },
      special_scoring: scoringSettings.special_scoring || [],
      raw_settings: scoringSettings,
    },
    features: {
      trades_enabled: leagueFeatures.trade_deadline == null || true,
      waivers_enabled: true,
      waiver_type: waiverSettings.waiver_type || leagueFeatures.waiver_type,
      waiver_budget: waiverSettings.waiver_budget,
      playoffs: {
        teams: Number(playoffSettings.playoff_teams ?? 4),
        weeks: Number(playoffSettings.playoff_rounds ?? 2),
      },
    },
    ai_context: buildAiContext(rosterPositions, normalizedScoringType, {
      is_dynasty: inferredFormat.is_dynasty,
      is_keeper: inferredFormat.is_keeper,
    }),
  };
}
