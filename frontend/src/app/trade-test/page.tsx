'use client';

import TradeAnalyzer from '@/components/TradeAnalyzer';

// Mock data for testing
const mockLeagues = [
  { id: 1, name: "Test Fantasy League", platform: "sleeper" }
];

const mockStandingsTeams = [
  {
    team_id: 1,
    platform_team_id: "1",
    name: "Team Alpha",
    owner_name: "Owner 1",
    is_user_team: true,
    wins: 8,
    losses: 4,
    ties: 0,
    win_percentage: 0.667,
    points_for: 1450.5,
    points_against: 1320.2,
    points_per_game: 120.9,
    points_against_per_game: 110.0,
    point_differential: 130.3,
    waiver_position: 5,
    rank: 2
  },
  {
    team_id: 2,
    platform_team_id: "2", 
    name: "Team Beta",
    owner_name: "Owner 2",
    is_user_team: false,
    wins: 7,
    losses: 5,
    ties: 0,
    win_percentage: 0.583,
    points_for: 1380.2,
    points_against: 1350.8,
    points_per_game: 115.0,
    points_against_per_game: 112.6,
    point_differential: 29.4,
    waiver_position: 8,
    rank: 4
  }
];

export default function TradeTestPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container mx-auto py-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">Trade Analyzer Test</h1>
        <TradeAnalyzer 
          leagues={mockLeagues}
          initialLeagueId={1}
          teams={mockStandingsTeams}
        />
      </div>
    </div>
  );
}