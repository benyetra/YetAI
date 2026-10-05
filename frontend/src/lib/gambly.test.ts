import {
  GAMBLY_MAX_PROMPT_CHARS,
  buildGamblyUrl,
  gamblyLegFromDiscoveryRow,
  gamblyLegFromPick,
  gamblyLegFromProjection,
  gamblyLegFromSlipItem,
  gamblyPrompt,
  gamblyUrlForLegs,
  isGamblyEnabled,
} from '@/lib/gambly';
import type { DiscoveryGroupConfig } from '@/lib/propDiscovery';

function params(url: string): URLSearchParams {
  const u = new URL(url);
  expect(u.origin + u.pathname).toBe('https://gambly.com/chat');
  return u.searchParams;
}

describe('isGamblyEnabled', () => {
  it('is on by default', () => {
    expect(isGamblyEnabled(undefined)).toBe(true);
    expect(isGamblyEnabled('')).toBe(true);
    expect(isGamblyEnabled('1')).toBe(true);
  });

  it('turns off for explicit off values', () => {
    for (const v of ['0', 'false', 'NO', ' off ']) expect(isGamblyEnabled(v)).toBe(false);
  });
});

describe('buildGamblyUrl', () => {
  it('uses the ask-gambly auto-submit entry point', () => {
    const p = params(buildGamblyUrl('Build me a betslip: Yankees moneyline'));
    expect(p.get('entry')).toBe('ask-gambly');
    expect(p.get('autoSubmit')).toBe('1');
    expect(p.get('prompt')).toBe('Build me a betslip: Yankees moneyline');
    expect(p.get('utm_source')).toBe('yetai');
  });

  it('caps very long prompts', () => {
    const p = params(buildGamblyUrl('x'.repeat(5000)));
    expect(p.get('prompt')!.length).toBe(GAMBLY_MAX_PROMPT_CHARS);
  });
});

describe('gamblyPrompt', () => {
  it('returns empty for no legs', () => {
    expect(gamblyPrompt([' ', ''])).toBe('');
    expect(gamblyUrlForLegs([])).toBeNull();
  });

  it('formats a single leg', () => {
    expect(gamblyPrompt(['Yankees moneyline'])).toBe('Build me a betslip: Yankees moneyline');
  });

  it('defaults multi-leg to a numbered parlay', () => {
    expect(gamblyPrompt(['A', 'B'])).toBe('Build me a 2-leg parlay:\n1. A\n2. B');
  });

  it('supports straight bets', () => {
    expect(gamblyPrompt(['A', 'B'], { parlay: false })).toBe(
      'Build me a betslip with these 2 straight bets:\n1. A\n2. B',
    );
  });
});

describe('gamblyLegFromSlipItem', () => {
  const rawGame = {
    home_team: 'Atlanta Falcons',
    away_team: 'Buffalo Bills',
    bookmakers: [],
  };

  it('uses full team names for moneyline', () => {
    expect(
      gamblyLegFromSlipItem({
        id: 'g1-ml-away',
        gameId: 'g1',
        key: 'ml-away',
        label: 'BUF ML',
        odds: -150,
        matchup: 'Buffalo Bills @ Atlanta Falcons',
        rawGame,
      }),
    ).toBe('Buffalo Bills moneyline (-150) — Buffalo Bills @ Atlanta Falcons');
  });

  it('falls back to the label without raw game data', () => {
    expect(
      gamblyLegFromSlipItem({
        id: 'x',
        gameId: 'g1',
        key: 'total-over',
        label: 'Over 47.5',
        odds: -110,
        matchup: 'BUF @ ATL',
      }),
    ).toBe('Over 47.5 total (-110) — BUF @ ATL');
  });
});

describe('gamblyLegFromPick', () => {
  it('includes matchup and odds for game picks', () => {
    expect(
      gamblyLegFromPick({
        id: '1',
        league: 'NFL',
        matchup: 'Bills @ Falcons',
        pick: 'Bills -3.5',
        bet_type: 'spread',
        odds: '-110',
        confidence: 0.6,
      }),
    ).toBe('Bills -3.5 spread (-110) — Bills @ Falcons');
  });

  it('labels props by league when there is no matchup', () => {
    expect(
      gamblyLegFromPick({
        id: '2',
        league: 'NBA',
        matchup: 'NBA player prop',
        pick: 'Jalen Brunson Over 26.5 points',
        bet_type: 'prop',
        odds: 115,
        confidence: 0.6,
      }),
    ).toBe('Jalen Brunson Over 26.5 points (+115) (NBA)');
  });
});

describe('gamblyLegFromProjection', () => {
  const matchup = 'Boston Red Sox @ New York Yankees';

  it('formats moneyline picks', () => {
    expect(gamblyLegFromProjection({ kind: 'ml', team: 'New York Yankees', odds: -135, matchup })).toBe(
      'New York Yankees moneyline (-135) — Boston Red Sox @ New York Yankees',
    );
  });

  it('formats spread picks with the market line', () => {
    expect(gamblyLegFromProjection({ kind: 'spread', team: 'Boston Celtics', line: '+4.5', matchup })).toBe(
      'Boston Celtics +4.5 spread — Boston Red Sox @ New York Yankees',
    );
  });

  it('formats total picks', () => {
    expect(gamblyLegFromProjection({ kind: 'total', team: 'Over', line: '8.5', matchup })).toBe(
      'Over 8.5 total — Boston Red Sox @ New York Yankees',
    );
  });
});

describe('gamblyLegFromDiscoveryRow', () => {
  const points: DiscoveryGroupConfig = {
    title: 'Points',
    responseKey: 'points',
    mode: 'positive_edge',
    nameKey: 'player_name',
    projectedKey: 'projected_points',
    lineKey: 'fanduel_line',
    pickKey: 'recommendation',
  };

  it('uses the model recommendation side', () => {
    expect(
      gamblyLegFromDiscoveryRow(
        { player_name: 'Jalen Brunson', projected_points: 29.1, fanduel_line: 26.5, recommendation: 'OVER' },
        points,
      ),
    ).toBe('Jalen Brunson Over 26.5 points');
  });

  it('infers the side from projection vs line when no recommendation', () => {
    expect(
      gamblyLegFromDiscoveryRow({ player_name: 'A', projected_points: 20, fanduel_line: 22.5 }, points),
    ).toBe('A Under 22.5 points');
  });

  it('returns null without a line', () => {
    expect(gamblyLegFromDiscoveryRow({ player_name: 'A', recommendation: 'OVER' }, points)).toBeNull();
  });

  it('maps PRA and hit-chance groups', () => {
    expect(
      gamblyLegFromDiscoveryRow(
        { player_name: 'B', projected_pra: 40, fanduel_line: 38.5, recommendation: 'OVER' },
        { ...points, title: 'PRA', projectedKey: 'projected_pra' },
      ),
    ).toBe('B Over 38.5 points + rebounds + assists');
    expect(
      gamblyLegFromDiscoveryRow(
        { batter_name: 'Aaron Judge', projected_hits: 1.2 },
        {
          title: 'Best hit chances',
          responseKey: 'projected_hits',
          mode: 'projected_value',
          valueKey: 'projected_hits',
          nameKey: 'batter_name',
        },
      ),
    ).toBe('Aaron Judge to record a hit');
  });
});
