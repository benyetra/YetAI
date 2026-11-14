/** Sports and markets the grader can settle; keep in sync with the backend. */
export const SPORT_OPTIONS = [
  'NFL', 'NBA', 'WNBA', 'MLB', 'NHL', 'NCAA Football', 'NCAA Basketball', 'Soccer',
] as const;

export const BET_TYPE_OPTIONS = [
  'Spread', 'Moneyline', 'Total (Over/Under)', 'Puck Line', 'Run Line', 'Player Props',
] as const;
