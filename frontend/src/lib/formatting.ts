/**
 * Formatting utilities for the sports betting application
 */

// Sport name mappings from API keys to display names
export const SPORT_DISPLAY_NAMES: Record<string, string> = {
  'americanfootball_nfl': 'NFL',
  'americanfootball_ncaaf': 'NCAAF',
  'basketball_nba': 'NBA',
  'basketball_ncaab': 'NCAAB',
  'basketball_wnba': 'WNBA',
  'baseball_mlb': 'MLB',
  'icehockey_nhl': 'NHL',
  'soccer_epl': 'Premier League',
  'soccer_mls': 'MLS',
  'soccer_uefa_champs_league': 'Champions League',
  'soccer_fifa_world_cup': 'World Cup',
  'golf_pga': 'PGA',
  'tennis_atp': 'ATP',
  'tennis_wta': 'WTA',
  'mma_mixed_martial_arts': 'MMA',
  'boxing_heavyweight': 'Boxing'
};

/**
 * Convert sport API key to display name
 */
export function formatSportName(sportKey: string): string {
  return SPORT_DISPLAY_NAMES[sportKey] || sportKey.replace(/_/g, ' ').toUpperCase();
}

/**
 * Format a date/time string to local timezone
 */
export function formatLocalDateTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleString();
}

/**
 * Format a date to local date only
 */
export function formatLocalDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString();
}

/**
 * Format a time to local time only
 */
export function formatLocalTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleTimeString();
}

/**
 * Format time relative to now (e.g., "2h", "Live", "Yesterday")
 */
export function formatTimeFromNow(dateString: string): string {
  const time = new Date(dateString);
  const now = new Date();
  const diffMinutes = Math.floor((time.getTime() - now.getTime()) / (1000 * 60));
  
  if (diffMinutes < -1440) {
    // More than a day ago
    const diffDays = Math.floor(-diffMinutes / 1440);
    if (diffDays === 1) return 'Yesterday';
    if (diffDays <= 7) return time.toLocaleDateString('en-US', { weekday: 'long' });
    return time.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } else if (diffMinutes < -60) {
    // Hours ago
    return `${Math.floor(-diffMinutes / 60)}h ago`;
  } else if (diffMinutes < 0) {
    // Minutes ago or live
    return diffMinutes > -5 ? 'Live' : `${-diffMinutes}m ago`;
  } else if (diffMinutes < 60) {
    // Minutes from now
    return `${diffMinutes}m`;
  } else if (diffMinutes < 1440) {
    // Hours from now
    return `${Math.floor(diffMinutes / 60)}h`;
  } else {
    // Days from now
    const diffDays = Math.floor(diffMinutes / 1440);
    if (diffDays === 1) return 'Tomorrow';
    return time.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  }
}

/**
 * Format odds number for display
 */
export function formatOdds(odds: number): string {
  if (odds > 0) {
    return `+${odds}`;
  }
  return odds.toString();
}

/**
 * Format over/under total to clean decimal
 */
export function formatTotal(total: number): string {
  // Round to nearest 0.5
  const rounded = Math.round(total * 2) / 2;
  return rounded % 1 === 0 ? rounded.toString() : rounded.toFixed(1);
}

/**
 * Format spread point to clean decimal (should be whole numbers or .5)
 */
export function formatSpread(spread: number): string {
  // Round to nearest 0.5
  const rounded = Math.round(spread * 2) / 2;
  const formatted = rounded % 1 === 0 ? rounded.toString() : rounded.toFixed(1);
  
  // Add explicit + sign for positive spreads
  if (rounded > 0) {
    return `+${formatted}`;
  }
  return formatted;
}

/**
 * Format game status for display
 */
export function formatGameStatus(status: string): string {
  // Handle null/undefined status
  if (!status) {
    return 'Unknown';
  }

  const statusMap: Record<string, string> = {
    'STATUS_SCHEDULED': 'Scheduled',
    'STATUS_LIVE': 'Live',
    'STATUS_FINAL': 'Final',
    'STATUS_POSTPONED': 'Postponed',
    'STATUS_CANCELLED': 'Cancelled',
    'STATUS_HALFTIME': 'Halftime',
    'STATUS_OVERTIME': 'Overtime',
    // Baseball innings
    '1st_inning': '1st Inning',
    '2nd_inning': '2nd Inning', 
    '3rd_inning': '3rd Inning',
    '4th_inning': '4th Inning',
    '5th_inning': '5th Inning',
    '6th_inning': '6th Inning',
    '7th_inning': '7th Inning',
    '8th_inning': '8th Inning',
    '9th_inning': '9th Inning',
    // Football quarters
    '1st_quarter': '1st Quarter',
    '2nd_quarter': '2nd Quarter',
    '3rd_quarter': '3rd Quarter',
    '4th_quarter': '4th Quarter',
    // Basketball quarters
    '1st_period': '1st Period',
    '2nd_period': '2nd Period',
    '3rd_period': '3rd Period',
    '4th_period': '4th Period'
  };
  
  // Check exact matches first
  if (statusMap[status]) {
    return statusMap[status];
  }
  
  // Handle underscore patterns like "2nd_inning" -> "2nd Inning"
  if (status.includes('_')) {
    const parts = status.split('_');
    return parts.map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ');
  }
  
  // Fallback for STATUS_ prefixed statuses
  return status.replace('STATUS_', '').toLowerCase();
}

/**
 * Format friendly date with day name
 */
export function formatFriendlyDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffDays = Math.floor((date.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
  
  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Tomorrow';
  if (diffDays === -1) return 'Yesterday';
  if (diffDays > -7 && diffDays < 0) {
    return date.toLocaleDateString('en-US', { weekday: 'long' });
  }
  
  return date.toLocaleDateString('en-US', { 
    weekday: 'short', 
    month: 'short', 
    day: 'numeric',
    year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
  });
}