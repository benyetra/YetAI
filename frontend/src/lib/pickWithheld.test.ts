import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { comparePredictionRows } from '@/components/PredictionsTable';
import { ANYTIME_TD_COLUMNS } from '@/lib/anytimeTdDisplay';
import { NFL_QB_COLUMNS, isTopPlay } from '@/lib/propProjectionDisplay';
import { PICK_WITHHELD_NOTE, isPickWithheld } from '@/lib/pickWithheld';
import { spreadRecommendation } from '@/components/yetai/MlbGameProjectionsGrid';
import { spreadMarketEdge } from '@/lib/spreadTotalsProjectionDisplay';
import { mergeSpreadTotalsGameProjections } from '@/lib/mergeSpreadTotalsGameProjections';

const html = (node: unknown) => renderToStaticMarkup(createElement('div', null, node as never));
const pickCol = (cols: typeof ANYTIME_TD_COLUMNS) => cols.find((c) => c.key === 'recommendation')!;

describe('withheld rows', () => {
  it('detects pick_withheld', () => {
    expect(isPickWithheld({ pick_withheld: 'losing_record' })).toBe(true);
    expect(isPickWithheld({ pick_withheld: null })).toBe(false);
    expect(isPickWithheld({})).toBe(false);
  });

  it('ATD and prop pick columns show the note, not a pick', () => {
    const row = { recommendation: null, pick_withheld: 'record_unavailable', projected: 1 };
    for (const cols of [ANYTIME_TD_COLUMNS, NFL_QB_COLUMNS]) {
      const out = html(pickCol(cols).format!(null, row));
      expect(out).toContain(PICK_WITHHELD_NOTE);
    }
    expect(html(pickCol(ANYTIME_TD_COLUMNS).format!('OVER', { recommendation: 'OVER' }))).toContain('OVER');
  });

  it('a withheld row is never a top play', () => {
    expect(isTopPlay({ value_tier: 'strong', pick_withheld: 'losing_record' })).toBe(false);
    expect(isTopPlay({ value_tier: 'strong' })).toBe(true);
  });
});

describe('spread side is never derived', () => {
  it('no stored recommendation -> no side even with a big margin gap', () => {
    expect(spreadRecommendation({ run_line: 12, market_spread: -1 })).toBeNull();
    expect(spreadRecommendation({ spread_recommendation: 'AWAY' })).toBe('AWAY');
    expect(spreadMarketEdge({ run_line: 12, market_spread: -1 })).toBeNull();
  });

  it('merge drops side, edge and rating for a withheld spread', () => {
    const [row] = mergeSpreadTotalsGameProjections(
      [{ id: 1, home_team_name: 'H', away_team_name: 'A', projected_margin: 12, market_spread_home: -1,
         recommendation: 'HOME', edge: 8, pick_withheld: 'unproven_record' }],
      [],
    );
    expect(row.spread_recommendation).toBeNull();
    expect(row.spread_edge).toBeNull();
    expect(row.value_rating).toBe('No Edge');
    expect(row.spread_pick_withheld).toBe('unproven_record');
  });
});

describe('null edge sorts last', () => {
  it('both directions', () => {
    const rows = [{ edge: null }, { edge: 1 }, { edge: 3 }];
    for (const dir of ['asc', 'desc'] as const) {
      const sorted = [...rows].sort((a, b) => comparePredictionRows(a, b, 'edge', dir));
      expect(sorted[2].edge).toBeNull();
    }
  });
});
