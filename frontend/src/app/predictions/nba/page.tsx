'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import GameProjectionsSection from '@/components/yetai/GameProjectionsSection';
import SportPredictionsPage from '@/components/yetai/SportPredictionsPage';
import {
  buildBasketballPropColumns,
  propRowClassName,
} from '@/lib/propProjectionDisplay';

const PROP_GROUPS = [
  {
    title: 'Points',
    responseKey: 'points',
    columns: buildBasketballPropColumns({
      projectedKey: 'projected_points',
      projectedLabel: 'Proj Pts',
    }),
    rowClassName: propRowClassName,
  },
  {
    title: 'Assists',
    responseKey: 'assists',
    columns: buildBasketballPropColumns({
      projectedKey: 'projected_assists',
      projectedLabel: 'Proj Ast',
    }),
    rowClassName: propRowClassName,
  },
  {
    title: 'Rebounds',
    responseKey: 'rebounds',
    columns: buildBasketballPropColumns({
      projectedKey: 'projected_rebounds',
      projectedLabel: 'Proj Reb',
    }),
    rowClassName: propRowClassName,
  },
  {
    title: 'Three-Pointers',
    responseKey: 'three_point',
    columns: buildBasketballPropColumns({
      projectedKey: 'projected_three_pt_made',
      projectedLabel: 'Proj 3PM',
    }),
    rowClassName: propRowClassName,
  },
  {
    title: 'Steals',
    responseKey: 'steals',
    columns: buildBasketballPropColumns({
      projectedKey: 'projected_steals',
      projectedLabel: 'Proj Stl',
    }),
    rowClassName: propRowClassName,
  },
  {
    title: 'Blocks',
    responseKey: 'blocks',
    columns: buildBasketballPropColumns({
      projectedKey: 'projected_blocks',
      projectedLabel: 'Proj Blk',
    }),
    rowClassName: propRowClassName,
  },
  {
    title: 'PRA (Pts + Reb + Ast)',
    responseKey: 'pra',
    columns: buildBasketballPropColumns({
      projectedKey: 'projected_pra',
      projectedLabel: 'Proj PRA',
    }),
    rowClassName: propRowClassName,
  },
];

export default function NBAPredictionsPage() {
  return (
    <SportPredictionsPage
      sport="nba"
      leagueLabel="NBA"
      emoji="🏀"
      subtitle="Game totals O/U, spread/win-probability, plus points, assists, rebounds, threes, steals, blocks, and PRA."
      topSection={({ data, loading, isPastDate }) => (
        <GameProjectionsSection
          variant="nba"
          data={data}
          loading={loading}
          isPastDate={isPastDate}
        />
      )}
      accuracySummary={({ date }) => <AccuracySummary sport="nba" date={date} />}
      groups={PROP_GROUPS}
    />
  );
}
