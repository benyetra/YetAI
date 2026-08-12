'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import GameProjectionsSection from '@/components/yetai/GameProjectionsSection';
import SportPredictionsPage from '@/components/yetai/SportPredictionsPage';
import { WNBA_DISCOVERY_GROUPS } from '@/lib/propDiscoveryConfigs';
import {
  propRowClassName,
  WNBA_PROP_COLUMNS,
} from '@/lib/propProjectionDisplay';

const PROP_GROUPS = [
  {
    title: 'Points',
    responseKey: 'points',
    columns: WNBA_PROP_COLUMNS.points,
    rowClassName: propRowClassName,
  },
  {
    title: 'Assists',
    responseKey: 'assists',
    columns: WNBA_PROP_COLUMNS.assists,
    rowClassName: propRowClassName,
  },
  {
    title: 'Rebounds',
    responseKey: 'rebounds',
    columns: WNBA_PROP_COLUMNS.rebounds,
    rowClassName: propRowClassName,
  },
  {
    title: '3-Pointers',
    responseKey: 'three_point',
    columns: WNBA_PROP_COLUMNS.three_point,
    rowClassName: propRowClassName,
  },
  {
    title: 'PRA',
    responseKey: 'pra',
    columns: WNBA_PROP_COLUMNS.pra,
    rowClassName: propRowClassName,
  },
];

export default function WNBAPredictionsPage() {
  return (
    <SportPredictionsPage
      sport="wnba"
      leagueLabel="WNBA"
      emoji="🏀"
      subtitle="Game slate, spread/win-probability, totals O/U, and player props (points, assists, rebounds, 3PM, PRA)."
      topSection={({ data, loading, isPastDate }) => (
        <GameProjectionsSection
          variant="wnba"
          data={data}
          loading={loading}
          isPastDate={isPastDate}
        />
      )}
      accuracySummary={({ date }) => <AccuracySummary sport="wnba" date={date} />}
      groups={PROP_GROUPS}
      discoveryGroups={WNBA_DISCOVERY_GROUPS}
    />
  );
}
