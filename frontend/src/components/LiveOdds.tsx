'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Clock,
  RefreshCw,
  AlertCircle,
  Wifi,
  WifiOff,
  Activity,
  Calendar,
  Users,
  Target,
  BarChart3,
  User
} from 'lucide-react';
import { sportsAPI, circuitBreakerAPI } from '../lib/api';
import {
  formatSportName,
  formatLocalDateTime,
  formatLocalDate,
  formatLocalTime,
  formatTimeFromNow,
  formatOdds as formatOddsDisplay,
  formatTotal,
  formatFriendlyDate
} from '../lib/formatting';
import PlayerPropsCard from './PlayerPropsCard';
import PlayerPropBetModal from './PlayerPropBetModal';

interface Bookmaker {
  key: string;
  title: string;
  last_update: string;
  markets: Array<{
    key: string;
    outcomes: Array<{
      name: string;
      price: number;
      point?: number;
    }>;
  }>;
}

interface Game {
  id: string;
  sport_key: string;
  sport_title: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  bookmakers: Bookmaker[];
}

interface OddsData {
  status: string;
  sport?: string;
  count: number;
  games: Game[];
  cached?: boolean;
  last_updated: string;
  message?: string;
}

interface LiveOddsProps {
  sportKey?: string;
  showPopular?: boolean;
  autoRefresh?: boolean;
  refreshInterval?: number;
  maxGames?: number;
  onPlaceBet?: (game: Game) => void;
}

export function LiveOdds({ 
  sportKey, 
  showPopular = false, 
  autoRefresh = true, 
  refreshInterval = 300000, // 5 minutes
  maxGames = 10,
  onPlaceBet
}: LiveOddsProps) {
  const [oddsData, setOddsData] = useState<OddsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [isConnected, setIsConnected] = useState(true);
  const [circuitBreakerState, setCircuitBreakerState] = useState<any>(null);
  const [selectedGameForProps, setSelectedGameForProps] = useState<Game | null>(null);
  const [showPropsModal, setShowPropsModal] = useState(false);
  const [selectedProp, setSelectedProp] = useState<any>(null);
  const [showPropBetModal, setShowPropBetModal] = useState(false);

  const fetchOdds = useCallback(async (showLoader: boolean = true) => {
    try {
      if (showLoader) setLoading(true);
      setError(null);

      let data: OddsData;
      
      if (showPopular) {
        data = await sportsAPI.getPopularOdds();
      } else if (sportKey) {
        data = await sportsAPI.getOdds(sportKey);
      } else {
        data = await sportsAPI.getLiveGames();
      }

      setOddsData(data);
      setLastUpdate(new Date());
      setIsConnected(true);
      
      // Update circuit breaker state
      setCircuitBreakerState(circuitBreakerAPI.getState());
      
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch odds';
      setError(errorMessage);
      setIsConnected(false);
      
      // Check if circuit breaker is open
      const cbState = circuitBreakerAPI.getState();
      setCircuitBreakerState(cbState);
      
      if (cbState.state === 'open') {
        setError('Service temporarily unavailable. Please try again later.');
      }
    } finally {
      if (showLoader) setLoading(false);
    }
  }, [sportKey, showPopular]);

  // Initial load
  useEffect(() => {
    fetchOdds();
  }, [fetchOdds]);

  // Auto refresh
  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      fetchOdds(false); // Background refresh without loader
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, fetchOdds]);

  // Use imported formatting functions instead of local ones

  const getBestOdds = (bookmakers: Bookmaker[], market: string, outcome: string) => {
    let bestOdds = null;
    let bestBookmaker = '';
    
    for (const bookmaker of bookmakers) {
      const marketData = bookmaker.markets.find(m => m.key === market);
      if (marketData) {
        const outcomeData = marketData.outcomes.find(o => o.name === outcome);
        if (outcomeData && (bestOdds === null || outcomeData.price > bestOdds)) {
          bestOdds = outcomeData.price;
          bestBookmaker = bookmaker.title;
        }
      }
    }
    
    return { odds: bestOdds, bookmaker: bestBookmaker };
  };

  const getSpreadInfo = (bookmakers: Bookmaker[], team: string) => {
    for (const bookmaker of bookmakers) {
      const spreadMarket = bookmaker.markets.find(m => m.key === 'spreads');
      if (spreadMarket) {
        const outcome = spreadMarket.outcomes.find(o => o.name === team);
        if (outcome && outcome.point !== undefined) {
          return { point: outcome.point, odds: outcome.price };
        }
      }
    }
    return null;
  };

  const getTotalInfo = (bookmakers: Bookmaker[]) => {
    for (const bookmaker of bookmakers) {
      const totalMarket = bookmaker.markets.find(m => m.key === 'totals');
      if (totalMarket && totalMarket.outcomes.length >= 2) {
        const over = totalMarket.outcomes.find(o => o.name === 'Over');
        const under = totalMarket.outcomes.find(o => o.name === 'Under');
        if (over && under && over.point !== undefined) {
          return {
            total: over.point,
            overOdds: over.price,
            underOdds: under.price
          };
        }
      }
    }
    return null;
  };

  if (loading && !oddsData) {
    return (
      <div className="bg-white rounded-lg shadow-lg p-6">
        <div className="flex items-center justify-center h-40">
          <div className="flex items-center space-x-2">
            <RefreshCw className="w-5 h-5 animate-spin text-[#A855F7]" />
            <span className="text-gray-600">Loading live odds...</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow-lg">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Activity className="w-6 h-6 text-[#A855F7]" />
            <div>
              <h2 className="text-lg font-bold text-gray-900">
                {showPopular ? 'Popular Sports Odds' : 
                 sportKey ? `${formatSportName(oddsData?.sport || sportKey)} Odds` : 'Live Games'}
              </h2>
              <p className="text-sm text-gray-600">
                {oddsData?.count || 0} games • Updated {lastUpdate ? lastUpdate.toLocaleTimeString() : 'never'}
              </p>
            </div>
          </div>
          
          <div className="flex items-center space-x-2">
            {/* Connection status */}
            <div className="flex items-center space-x-1">
              {isConnected ? (
                <Wifi className="w-4 h-4 text-green-500" />
              ) : (
                <WifiOff className="w-4 h-4 text-red-500" />
              )}
              <span className={`text-xs ${isConnected ? 'text-green-600' : 'text-red-600'}`}>
                {isConnected ? 'Live' : 'Offline'}
              </span>
            </div>
            
            {/* Cache indicator */}
            {oddsData?.cached && (
              <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-1 rounded">
                Cached
              </span>
            )}
            
            {/* Refresh button */}
            <button
              onClick={() => fetchOdds(true)}
              disabled={loading}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors border border-gray-200 bg-white text-gray-700 shadow-sm"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
        
        {/* Circuit breaker status */}
        {circuitBreakerState && circuitBreakerState.state !== 'closed' && (
          <div className="mt-2 p-2 bg-orange-50 border border-orange-200 rounded text-sm">
            <div className="flex items-center space-x-1">
              <AlertCircle className="w-4 h-4 text-orange-600" />
              <span className="text-orange-800">
                Service quality reduced ({circuitBreakerState.state}) - 
                {circuitBreakerState.failures} failures
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Error State */}
      {error && (
        <div className="p-6">
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex items-center space-x-2">
              <AlertCircle className="w-5 h-5 text-red-600" />
              <span className="text-red-800">{error}</span>
            </div>
            <button
              onClick={() => fetchOdds(true)}
              className="mt-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {/* No Data State */}
      {oddsData && oddsData.count === 0 && !error && (
        <div className="p-6">
          <div className="text-center py-8">
            <Calendar className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">No Games Available</h3>
            <p className="text-gray-600">
              {oddsData.message || 'No live games or odds currently available for this sport.'}
            </p>
          </div>
        </div>
      )}

      {/* Games List */}
      {oddsData && oddsData.games && oddsData.games.length > 0 && (
        <div className="divide-y divide-gray-200">
          {oddsData.games.slice(0, maxGames).map((game) => {
            const homeMoneyline = getBestOdds(game.bookmakers, 'h2h', game.home_team);
            const awayMoneyline = getBestOdds(game.bookmakers, 'h2h', game.away_team);
            const homeSpread = getSpreadInfo(game.bookmakers, game.home_team);
            const awaySpread = getSpreadInfo(game.bookmakers, game.away_team);
            const totalInfo = getTotalInfo(game.bookmakers);
            
            return (
              <div key={game.id} className="p-6 hover:bg-gray-50 transition-colors">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center space-x-2">
                    <span className="text-sm font-medium text-[#A855F7] bg-[#A855F7]/10 px-2 py-1 rounded">
                      {formatSportName(game.sport_key)}
                    </span>
                    <div className="flex items-center space-x-1 text-sm text-gray-600">
                      <Clock className="w-3 h-3" />
                      <span>{formatTimeFromNow(game.commence_time)}</span>
                    </div>
                  </div>
                  
                  <div className="text-right">
                    <div className="text-sm text-gray-600">
                      {formatLocalDate(game.commence_time)}
                    </div>
                    <div className="text-xs text-gray-500">
                      {formatLocalTime(game.commence_time)}
                    </div>
                  </div>
                </div>

                {/* Teams and Odds */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  {/* Teams */}
                  <div className="lg:col-span-1">
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-2">
                          <Users className="w-4 h-4 text-gray-400" />
                          <span className="font-semibold text-gray-900">{game.away_team}</span>
                        </div>
                        <span className="text-sm text-gray-600">Away</span>
                      </div>
                      
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-2">
                          <Users className="w-4 h-4 text-gray-400" />
                          <span className="font-semibold text-gray-900">{game.home_team}</span>
                        </div>
                        <span className="text-sm text-gray-600">Home</span>
                      </div>
                    </div>
                  </div>

                  {/* Moneyline */}
                  <div className="lg:col-span-1">
                    <h4 className="text-sm font-semibold text-gray-700 mb-3 flex items-center">
                      <Target className="w-4 h-4 mr-1" />
                      Moneyline
                    </h4>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between p-2 bg-gray-50 rounded">
                        <span className="text-sm text-gray-700">{game.away_team}</span>
                        <div className="text-right">
                          <div className="font-semibold text-gray-900">
                            {awayMoneyline.odds ? formatOddsDisplay(awayMoneyline.odds) : 'N/A'}
                          </div>
                          {awayMoneyline.bookmaker && (
                            <div className="text-xs text-gray-500">{awayMoneyline.bookmaker}</div>
                          )}
                        </div>
                      </div>
                      
                      <div className="flex items-center justify-between p-2 bg-gray-50 rounded">
                        <span className="text-sm text-gray-700">{game.home_team}</span>
                        <div className="text-right">
                          <div className="font-semibold text-gray-900">
                            {homeMoneyline.odds ? formatOddsDisplay(homeMoneyline.odds) : 'N/A'}
                          </div>
                          {homeMoneyline.bookmaker && (
                            <div className="text-xs text-gray-500">{homeMoneyline.bookmaker}</div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Spread & Total */}
                  <div className="lg:col-span-1">
                    <h4 className="text-sm font-semibold text-gray-700 mb-3 flex items-center">
                      <BarChart3 className="w-4 h-4 mr-1" />
                      Spread & Total
                    </h4>
                    <div className="space-y-2">
                      {/* Spread */}
                      {(homeSpread || awaySpread) && (
                        <div className="p-2 bg-gray-50 rounded">
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-gray-700">Spread</span>
                            <div className="text-right">
                              {homeSpread && (
                                <div className="font-semibold text-gray-900">
                                  {homeSpread.point > 0 ? '+' : ''}{homeSpread.point} ({formatOddsDisplay(homeSpread.odds)})
                                </div>
                              )}
                              {awaySpread && (
                                <div className="font-semibold text-gray-900">
                                  {awaySpread.point > 0 ? '+' : ''}{awaySpread.point} ({formatOddsDisplay(awaySpread.odds)})
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                      
                      {/* Total */}
                      {totalInfo && (
                        <div className="p-2 bg-gray-50 rounded">
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-gray-700">O/U {formatTotal(totalInfo.total)}</span>
                            <div className="text-right">
                              <div className="font-semibold text-gray-900">
                                O {formatOddsDisplay(totalInfo.overOdds)} / U {formatOddsDisplay(totalInfo.underOdds)}
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Bookmaker count */}
                <div className="mt-4 pt-3 border-t border-gray-100">
                  <div className="flex items-center justify-between text-xs text-gray-500">
                    <span>
                      {game.bookmakers.length} bookmaker{game.bookmakers.length !== 1 ? 's' : ''} available
                    </span>
                    <span>
                      Best odds shown • Updated {formatLocalTime(game.bookmakers[0]?.last_update || game.commence_time)}
                    </span>
                  </div>
                </div>
                
                {/* Action Buttons */}
                {onPlaceBet && (
                  <div className="mt-4 flex justify-center gap-2">
                    <button
                      onClick={() => onPlaceBet(game)}
                      className="bg-[#A855F7] hover:bg-[#9333EA] text-white px-6 py-2 rounded-lg font-medium transition-colors flex items-center space-x-2"
                    >
                      <Target className="w-4 h-4" />
                      <span>Place Bet</span>
                    </button>

                    {/* Player Props Button */}
                    {['americanfootball_nfl', 'basketball_nba', 'icehockey_nhl', 'baseball_mlb'].includes(game.sport_key) && (
                      <button
                        onClick={() => {
                          setSelectedGameForProps(game);
                          setShowPropsModal(true);
                        }}
                        className="bg-purple-600 hover:bg-purple-700 text-white px-6 py-2 rounded-lg font-medium transition-colors flex items-center space-x-2"
                      >
                        <User className="w-4 h-4" />
                        <span>Player Props</span>
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Show more games link */}
      {oddsData && oddsData.games && oddsData.games.length > maxGames && (
        <div className="px-6 py-4 border-t border-gray-200 text-center">
          <span className="text-sm text-gray-600">
            Showing {maxGames} of {oddsData.games.length} games
          </span>
        </div>
      )}

      {/* Player Props Modal */}
      {showPropsModal && selectedGameForProps && (
        <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center p-4 z-50">
          <div className="bg-gray-900 rounded-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden shadow-2xl">
            {/* Modal Header */}
            <div className="p-6 border-b border-gray-700 flex items-center justify-between bg-gradient-to-r from-purple-900/50 to-blue-900/50">
              <div>
                <h2 className="text-2xl font-bold text-white flex items-center space-x-2">
                  <User className="w-6 h-6 text-purple-400" />
                  <span>Player Props</span>
                </h2>
                <p className="text-sm text-gray-400 mt-1">
                  {selectedGameForProps.away_team} @ {selectedGameForProps.home_team}
                </p>
              </div>
              <button
                onClick={() => {
                  setShowPropsModal(false);
                  setSelectedGameForProps(null);
                }}
                className="p-2 hover:bg-gray-700 rounded-lg transition-all hover:rotate-90 group"
                aria-label="Close player props"
              >
                <span className="text-gray-400 text-3xl font-light group-hover:text-white transition-colors">×</span>
              </button>
            </div>

            {/* Player Props Content */}
            <div className="p-6 overflow-y-auto max-h-[calc(90vh-120px)]">
              <PlayerPropsCard
                sportKey={selectedGameForProps.sport_key}
                eventId={selectedGameForProps.id}
                gameInfo={{
                  home_team: selectedGameForProps.home_team,
                  away_team: selectedGameForProps.away_team,
                  commence_time: selectedGameForProps.commence_time
                }}
                onPlaceBet={(prop) => {
                  setSelectedProp(prop);
                  setShowPropBetModal(true);
                  setShowPropsModal(false);
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Player Prop Bet Modal */}
      <PlayerPropBetModal
        isOpen={showPropBetModal}
        onClose={() => {
          setShowPropBetModal(false);
          setSelectedProp(null);
        }}
        propBet={selectedProp}
      />
    </div>
  );
}