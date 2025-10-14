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
    player_rush_yds: 'Rushing Yards',
    player_reception_yds: 'Receiving Yards',
    player_receptions: 'Receptions',
    player_points: 'Points',
    player_rebounds: 'Rebounds',
    player_assists: 'Assists',
    player_threes: '3-Pointers Made',
    player_blocks: 'Blocks',
    player_steals: 'Steals',
    player_pitcher_strikeouts: 'Pitcher Strikeouts',
    player_hits: 'Hits',
    player_home_runs: 'Home Runs',
    player_rbis: 'RBIs'
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
    <div className="bg-gray-800 rounded-lg overflow-hidden">
      <div className="p-4 bg-gradient-to-r from-purple-900/50 to-blue-900/50 border-b border-gray-700">
        <div className="flex items-center space-x-2">
          <User className="w-5 h-5 text-purple-400" />
          <h3 className="text-lg font-semibold text-white">Player Props</h3>
          <span className="text-xs text-gray-400 ml-auto">FanDuel</span>
        </div>
      </div>

      <div className="divide-y divide-gray-700">
        {markets.map((market) => (
          <div key={market.market_key} className="bg-gray-800/50">
            {/* Market Header */}
            <button
              onClick={() => toggleMarket(market.market_key)}
              className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-700/30 transition-colors"
            >
              <div className="flex items-center space-x-2">
                <span className="font-medium text-white">
                  {getMarketDisplayName(market.market_key)}
                </span>
                <span className="text-xs text-gray-400">
                  ({market.players.length} players)
                </span>
              </div>
              {expandedMarkets.has(market.market_key) ? (
                <ChevronUp className="w-4 h-4 text-gray-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-gray-400" />
              )}
            </button>

            {/* Player Props */}
            {expandedMarkets.has(market.market_key) && (
              <div className="px-4 pb-4 space-y-2">
                {market.players.map((player) => (
                  <div
                    key={player.player_name}
                    className="bg-gray-700/30 rounded-lg p-3 border border-gray-700 hover:border-gray-600 transition-colors"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-white text-sm">
                        {player.player_name}
                      </span>
                      <span className="text-xs text-gray-400">
                        Line: {player.line}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      {/* Over Button */}
                      <button
                        onClick={() => handlePropSelection(market, player, 'over')}
                        disabled={player.over === null}
                        className={`
                          px-3 py-2 rounded-lg text-sm font-medium transition-all
                          ${player.over === null
                            ? 'bg-gray-600/30 text-gray-500 cursor-not-allowed'
                            : selectedProp?.market === market.market_key &&
                              selectedProp?.player === player.player_name &&
                              selectedProp?.selection === 'over'
                            ? 'bg-green-600 text-white ring-2 ring-green-400'
                            : 'bg-gray-600/50 text-white hover:bg-gray-600 hover:ring-2 hover:ring-green-500/50'
                          }
                        `}
                      >
                        <div className="flex items-center justify-between">
                          <span className="flex items-center space-x-1">
                            <TrendingUp className="w-3 h-3" />
                            <span>Over</span>
                          </span>
                          <span className={player.over && player.over > 0 ? 'text-green-400' : ''}>
                            {formatOdds(player.over)}
                          </span>
                        </div>
                      </button>

                      {/* Under Button */}
                      <button
                        onClick={() => handlePropSelection(market, player, 'under')}
                        disabled={player.under === null}
                        className={`
                          px-3 py-2 rounded-lg text-sm font-medium transition-all
                          ${player.under === null
                            ? 'bg-gray-600/30 text-gray-500 cursor-not-allowed'
                            : selectedProp?.market === market.market_key &&
                              selectedProp?.player === player.player_name &&
                              selectedProp?.selection === 'under'
                            ? 'bg-red-600 text-white ring-2 ring-red-400'
                            : 'bg-gray-600/50 text-white hover:bg-gray-600 hover:ring-2 hover:ring-red-500/50'
                          }
                        `}
                      >
                        <div className="flex items-center justify-between">
                          <span className="flex items-center space-x-1">
                            <TrendingDown className="w-3 h-3" />
                            <span>Under</span>
                          </span>
                          <span className={player.under && player.under > 0 ? 'text-green-400' : ''}>
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

      <div className="p-3 bg-gray-900/50 text-xs text-gray-400 text-center border-t border-gray-700">
        Odds from FanDuel • Updated{' '}
        {new Date(markets[0]?.last_update).toLocaleTimeString()}
      </div>
    </div>
  );
}
