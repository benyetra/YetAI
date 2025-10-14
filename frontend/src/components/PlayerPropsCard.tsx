'use client';

import React, { useState, useEffect } from 'react';
import { User, TrendingUp, TrendingDown, ChevronDown, ChevronUp, Loader } from 'lucide-react';
import { sportsAPI } from '@/lib/api';
import { useAuth } from './Auth';

// Types
interface PlayerProp {
  player_name: string;
  line: number;
  over: number | null;
  under: number | null;
}

interface PropMarket {
  market_key: string;
  last_update: string;
  players: PlayerProp[];
}

interface PlayerPropsData {
  event_id: string;
  sport_key: string;
  sport_title: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  markets: Record<string, PropMarket>;
}

interface PlayerPropsCardProps {
  sportKey: string;
  eventId: string;
  gameInfo: {
    home_team: string;
    away_team: string;
    commence_time: string;
  };
  onPlaceBet?: (propBet: PropBet) => void;
}

interface PropBet {
  player_name: string;
  market_key: string;
  market_display: string;
  line: number;
  selection: 'over' | 'under';
  odds: number;
  game_id: string;
  sport: string;
  home_team: string;
  away_team: string;
  commence_time: string;
}

// Market display names mapping
const getMarketDisplayName = (marketKey: string): string => {
  const replacements: Record<string, string> = {
    player_pass_tds: 'Passing Touchdowns',
    player_pass_yds: 'Passing Yards',
    player_pass_completions: 'Pass Completions',
    player_pass_attempts: 'Pass Attempts',
    player_pass_interceptions: 'Interceptions Thrown',
    player_pass_longest_completion: 'Longest Completion',
    player_rush_yds: 'Rushing Yards',
    player_rush_attempts: 'Rush Attempts',
    player_rush_longest: 'Longest Rush',
    player_reception_yds: 'Receiving Yards',
    player_receptions: 'Receptions',
    player_reception_longest: 'Longest Reception',
    player_anytime_td: 'Anytime Touchdown',
    player_1st_td: 'First Touchdown',
    player_last_td: 'Last Touchdown',
    player_points: 'Points',
    player_rebounds: 'Rebounds',
    player_assists: 'Assists',
    player_threes: '3-Pointers Made',
    player_blocks: 'Blocks',
    player_steals: 'Steals',
    player_turnovers: 'Turnovers',
    player_double_double: 'Double-Double',
    player_triple_double: 'Triple-Double',
    player_points_rebounds_assists: 'Points + Rebounds + Assists',
    player_points_rebounds: 'Points + Rebounds',
    player_points_assists: 'Points + Assists',
    player_rebounds_assists: 'Rebounds + Assists',
    player_pitcher_strikeouts: 'Pitcher Strikeouts',
    player_hits: 'Hits',
    player_home_runs: 'Home Runs',
    player_rbis: 'RBIs',
    player_runs_scored: 'Runs Scored',
    player_hits_runs_rbis: 'Hits + Runs + RBIs',
    player_singles: 'Singles',
    player_doubles: 'Doubles',
    player_triples: 'Triples',
    player_total_bases: 'Total Bases',
    player_stolen_bases: 'Stolen Bases',
    player_walks: 'Walks',
    player_strikeouts: 'Strikeouts',
    player_earned_runs: 'Earned Runs',
    player_hits_allowed: 'Hits Allowed',
    player_walks_allowed: 'Walks Allowed',
    player_shots_on_goal: 'Shots on Goal',
    player_blocked_shots: 'Blocked Shots',
    player_power_play_points: 'Power Play Points',
    player_goal: 'To Score a Goal',
    player_assists_hockey: 'Assists',
  };

  return replacements[marketKey] || marketKey.replace('player_', '').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
};

export default function PlayerPropsCard({
  sportKey,
  eventId,
  gameInfo,
  onPlaceBet
}: PlayerPropsCardProps) {
  const { token } = useAuth();
  const [propsData, setPropsData] = useState<PlayerPropsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedMarkets, setExpandedMarkets] = useState<Set<string>>(new Set());
  const [selectedProp, setSelectedProp] = useState<{ market: string; player: string; selection: 'over' | 'under' } | null>(null);

  useEffect(() => {
    fetchPlayerProps();
  }, [sportKey, eventId]);

  const fetchPlayerProps = async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch most popular markets based on sport
      const popularMarkets = getPopularMarkets(sportKey);

      const response = await sportsAPI.getPlayerProps(sportKey, eventId, popularMarkets, token);

      if (response.status === 'success' && response.data) {
        setPropsData(response.data);

        // Auto-expand first market
        const firstMarket = Object.keys(response.data.markets)[0];
        if (firstMarket) {
          setExpandedMarkets(new Set([firstMarket]));
        }
      } else {
        setError(response.message || 'No player props available for this game');
      }
    } catch (err) {
      console.error('Error fetching player props:', err);
      setError('Failed to load player props');
    } finally {
      setLoading(false);
    }
  };

  const getPopularMarkets = (sport: string): string[] => {
    const markets: Record<string, string[]> = {
      americanfootball_nfl: ['player_pass_tds', 'player_pass_yds', 'player_rush_yds', 'player_receptions', 'player_reception_yds'],
      basketball_nba: ['player_points', 'player_rebounds', 'player_assists', 'player_threes'],
      icehockey_nhl: ['player_points', 'player_assists', 'player_shots_on_goal', 'player_anytime_goal_scorer'],
      baseball_mlb: ['player_hits', 'player_home_runs', 'player_rbis', 'player_pitcher_strikeouts']
    };

    return markets[sport] || [];
  };

  const toggleMarket = (marketKey: string) => {
    setExpandedMarkets(prev => {
      const next = new Set(prev);
      if (next.has(marketKey)) {
        next.delete(marketKey);
      } else {
        next.add(marketKey);
      }
      return next;
    });
  };

  const handlePropSelection = (
    market: PropMarket,
    player: PlayerProp,
    selection: 'over' | 'under'
  ) => {
    const odds = selection === 'over' ? player.over : player.under;

    if (odds === null) return;

    const propBet: PropBet = {
      player_name: player.player_name,
      market_key: market.market_key,
      market_display: getMarketDisplayName(market.market_key),
      line: player.line,
      selection,
      odds,
      game_id: eventId,
      sport: sportKey,
      home_team: gameInfo.home_team,
      away_team: gameInfo.away_team,
      commence_time: gameInfo.commence_time
    };

    setSelectedProp({ market: market.market_key, player: player.player_name, selection });

    if (onPlaceBet) {
      onPlaceBet(propBet);
    }
  };

  const formatOdds = (odds: number | null): string => {
    if (odds === null) return '-';
    return odds > 0 ? `+${odds}` : `${odds}`;
  };

  if (loading) {
    return (
      <div className="bg-gray-800 rounded-lg p-6">
        <div className="flex items-center justify-center space-x-2">
          <Loader className="animate-spin w-5 h-5 text-purple-400" />
          <span className="text-gray-300">Loading player props...</span>
        </div>
      </div>
    );
  }

  if (error || !propsData) {
    return (
      <div className="bg-gray-800 rounded-lg p-6">
        <div className="text-center text-gray-400">
          <User className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p>{error || 'Player props not available'}</p>
          <button
            onClick={fetchPlayerProps}
            className="mt-3 text-purple-400 hover:text-purple-300 text-sm underline"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  const markets = Object.values(propsData.markets);

  if (markets.length === 0) {
    return (
      <div className="bg-gray-800 rounded-lg p-6">
        <div className="text-center text-gray-400">
          <User className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p>No player props available for this game</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded-lg overflow-hidden shadow-xl">
      <div className="p-4 bg-gradient-to-r from-purple-600 to-blue-600 border-b border-purple-500/30">
        <div className="flex items-center space-x-2">
          <User className="w-5 h-5 text-white" />
          <h3 className="text-lg font-semibold text-white">Player Props</h3>
          <span className="text-xs text-purple-200 ml-auto">FanDuel</span>
        </div>
      </div>

      <div className="divide-y divide-gray-800">
        {markets.map((market) => (
          <div key={market.market_key} className="bg-gray-900">
            {/* Market Header - Improved styling */}
            <button
              onClick={() => toggleMarket(market.market_key)}
              className="w-full px-4 py-4 flex items-center justify-between hover:bg-gray-800/70 transition-all group"
            >
              <div className="flex items-center gap-3 flex-1">
                <div className="w-1 h-8 bg-gradient-to-b from-purple-500 to-blue-500 rounded-full flex-shrink-0" />
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <h4 className="font-bold text-white text-lg group-hover:text-purple-300 transition-colors whitespace-nowrap">
                    {getMarketDisplayName(market.market_key)}
                  </h4>
                  <span className="text-xs text-gray-400 bg-gray-800 px-2.5 py-1 rounded-full font-medium flex-shrink-0">
                    {market.players.length}
                  </span>
                </div>
              </div>
              {expandedMarkets.has(market.market_key) ? (
                <ChevronUp className="w-5 h-5 text-purple-400 group-hover:text-purple-300 flex-shrink-0 ml-2" />
              ) : (
                <ChevronDown className="w-5 h-5 text-gray-500 group-hover:text-purple-400 flex-shrink-0 ml-2" />
              )}
            </button>

            {/* Player Props - Improved card styling */}
            {expandedMarkets.has(market.market_key) && (
              <div className="px-4 pb-4 pt-2 space-y-3 bg-gray-800/30">
                {market.players.map((player) => (
                  <div
                    key={player.player_name}
                    className="bg-gray-800 rounded-lg p-3 border border-gray-700 hover:border-purple-500/50 transition-all shadow-md"
                  >
                    <div className="flex items-center justify-between mb-3">
                      <span className="font-semibold text-white text-sm">
                        {player.player_name}
                      </span>
                      <span className="text-xs text-purple-400 font-medium bg-purple-500/10 px-2 py-1 rounded">
                        Line: {player.line}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      {/* Over Button - Enhanced styling */}
                      <button
                        onClick={() => handlePropSelection(market, player, 'over')}
                        disabled={player.over === null}
                        className={`
                          px-4 py-2.5 rounded-lg text-sm font-semibold transition-all
                          ${player.over === null
                            ? 'bg-gray-700/50 text-gray-600 cursor-not-allowed'
                            : selectedProp?.market === market.market_key &&
                              selectedProp?.player === player.player_name &&
                              selectedProp?.selection === 'over'
                            ? 'bg-gradient-to-r from-green-600 to-green-500 text-white ring-2 ring-green-400 shadow-lg shadow-green-500/50'
                            : 'bg-gray-700 text-white hover:bg-gradient-to-r hover:from-green-600 hover:to-green-500 hover:ring-2 hover:ring-green-500/50 hover:shadow-lg hover:shadow-green-500/30'
                          }
                        `}
                      >
                        <div className="flex items-center justify-between">
                          <span className="flex items-center space-x-1.5">
                            <TrendingUp className="w-4 h-4" />
                            <span>Over</span>
                          </span>
                          <span className="font-bold">
                            {formatOdds(player.over)}
                          </span>
                        </div>
                      </button>

                      {/* Under Button - Enhanced styling */}
                      <button
                        onClick={() => handlePropSelection(market, player, 'under')}
                        disabled={player.under === null}
                        className={`
                          px-4 py-2.5 rounded-lg text-sm font-semibold transition-all
                          ${player.under === null
                            ? 'bg-gray-700/50 text-gray-600 cursor-not-allowed'
                            : selectedProp?.market === market.market_key &&
                              selectedProp?.player === player.player_name &&
                              selectedProp?.selection === 'under'
                            ? 'bg-gradient-to-r from-red-600 to-red-500 text-white ring-2 ring-red-400 shadow-lg shadow-red-500/50'
                            : 'bg-gray-700 text-white hover:bg-gradient-to-r hover:from-red-600 hover:to-red-500 hover:ring-2 hover:ring-red-500/50 hover:shadow-lg hover:shadow-red-500/30'
                          }
                        `}
                      >
                        <div className="flex items-center justify-between">
                          <span className="flex items-center space-x-1.5">
                            <TrendingDown className="w-4 h-4" />
                            <span>Under</span>
                          </span>
                          <span className="font-bold">
                            {formatOdds(player.under)}
                          </span>
                        </div>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="p-3 bg-gray-900 text-xs text-gray-500 text-center border-t border-gray-800">
        Odds from FanDuel • Updated{' '}
        {new Date(markets[0]?.last_update).toLocaleTimeString()}
      </div>
    </div>
  );
}
