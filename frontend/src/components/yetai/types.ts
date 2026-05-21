export interface SlipItem {
  id: string;
  gameId: string;
  key: string;
  label: string;
  odds: number;
  matchup: string;
  sportKey?: string;
  rawGame?: unknown;
}

export interface BetSlipPlaceContext {
  slip: SlipItem[];
  mode: 'single' | 'parlay';
  stake: number;
}

export interface DesignPick {
  id: string;
  league: string;
  matchup: string;
  pick: string;
  odds: number | string;
  confidence: number;
  units?: number;
  edge?: string;
  reasoning?: string;
  game_time?: string;
  sport?: string;
  bet_type?: string;
  status?: string;
  is_premium?: boolean;
}

export interface DesignGameTeam {
  abbr: string;
  name: string;
  rec?: string;
  score?: number;
}

export interface DesignGame {
  id: string;
  league: string;
  tag: string;
  time: string;
  home: DesignGameTeam;
  away: DesignGameTeam;
  ml: { home: number; away: number };
  spread: {
    home: number | string;
    homeOdds: number;
    away: number | string;
    awayOdds: number;
  };
  total: { line: number; over: number; under: number };
  sport_key?: string;
  raw?: unknown;
}

export interface ActivityBet {
  id: string;
  pick: string;
  odds: number | string;
  matchup: string;
  date: string;
  source: string;
  status: 'won' | 'lost' | 'pending' | 'pushed';
  stake?: number;
  payout?: number;
}
