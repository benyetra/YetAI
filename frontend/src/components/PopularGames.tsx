'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  TrendingUp,
  Tv,
  Clock,
  RefreshCw,
  AlertCircle,
  Activity,
  Star,
  Users,
  Calendar,
  User
} from 'lucide-react';
import { sportsAPI } from '../lib/api';
import {
  formatSportName,
  formatLocalDateTime,
  formatLocalTime,
  formatTimeFromNow,
  formatFriendlyDate
} from '../lib/formatting';
import PlayerPropsCard from './PlayerPropsCard';
import PlayerPropBetModal from './PlayerPropBetModal';

interface BroadcastInfo {
  networks?: string[];  // Array of network names (new format from ESPN API)
  network?: string | null;  // Legacy single network field
  is_national: boolean;
  streaming?: string[];  // Streaming services
  is_prime_time?: boolean;
  popularity_score?: number;
}

interface PopularGame {
  id: string;
  home_team: string;
  away_team: string;
  start_time?: string;  // Legacy field
  commence_time: string;  // New field from API
  sport: string;
  sport_key: string;
  sport_title: string;
  broadcast?: BroadcastInfo;
  popularity_score?: number;
  bookmakers?: any[];
}

interface PopularGamesData {
  status: string;
  popular_games: {
    nfl: PopularGame[];
    nba: PopularGame[];
    mlb: PopularGame[];
    nhl: PopularGame[];
  };
  total_count: number;
  message?: string;
}

interface PopularGamesProps {
  autoRefresh?: boolean;
  refreshInterval?: number;
  maxGamesPerSport?: number;
  onPlaceBet?: (game: PopularGame) => void;
}

export function PopularGames({
  autoRefresh = true,
  refreshInterval = 600000, // 10 minutes
  maxGamesPerSport = 3,
  onPlaceBet
}: PopularGamesProps) {
  const [gamesData, setGamesData] = useState<PopularGamesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [selectedGameForProps, setSelectedGameForProps] = useState<PopularGame | null>(null);
  const [showPropsModal, setShowPropsModal] = useState(false);
  const [selectedProp, setSelectedProp] = useState<any>(null);
  const [showPropBetModal, setShowPropBetModal] = useState(false);

  const fetchPopularGames = useCallback(async (showLoader: boolean = true) => {
    try {
      if (showLoader) setLoading(true);
      setError(null);

      const data = await sportsAPI.getPopularGames();

      if (data.status === 'success') {
        setGamesData(data);
        setLastUpdate(new Date());
      } else {
        setError(data.message || 'Failed to fetch popular games');
      }
    } catch (error) {
      console.error('Error fetching popular games:', error);
      setError('Network error occurred');
    } finally {
      if (showLoader) setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchPopularGames();
  }, [fetchPopularGames]);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      fetchPopularGames(false); // Don't show loader for auto-refresh
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, fetchPopularGames]);

  const handlePlaceBet = async (game: PopularGame) => {
    // If custom handler provided, use it
    if (onPlaceBet) {
      onPlaceBet(game);
      return;
    }

    // Otherwise, generate FanDuel link
    try {
      setLoadingLink(game.id);

      const response = await sportsAPI.getSportsbookLink({
        sportsbook: 'fanduel',
        sport_key: game.sport_key,
        home_team: game.home_team,
        away_team: game.away_team,
        bet_type: 'h2h',
      });

      if (response.status === 'success' && response.link) {
        // Open FanDuel in new tab
        window.open(response.link, '_blank');
      } else {
        console.error('Failed to generate sportsbook link:', response);
      }
    } catch (error) {
      console.error('Error opening sportsbook link:', error);
    } finally {
      setLoadingLink(null);
    }
  };

  const getNetworkIcon = (network: string | null) => {
    if (!network) return <Tv className="w-4 h-4" />;

    const net = network.toUpperCase();
    if (net.includes('ESPN')) return <span className="text-red-600 font-bold text-xs">ESPN</span>;
    if (net.includes('NBC')) return <span className="text-blue-600 font-bold text-xs">NBC</span>;
    if (net.includes('CBS')) return <span className="text-blue-700 font-bold text-xs">CBS</span>;
    if (net.includes('FOX') || net.includes('FS1')) return <span className="text-blue-500 font-bold text-xs">{net.includes('FS1') ? 'FS1' : 'FOX'}</span>;
    if (net.includes('ABC')) return <span className="text-gray-800 font-bold text-xs">ABC</span>;
    if (net.includes('TNT')) return <span className="text-orange-600 font-bold text-xs">TNT</span>;
    if (net.includes('TBS')) return <span className="text-blue-600 font-bold text-xs">TBS</span>;
    if (net.includes('HBO MAX') || net.includes('MAX')) return <span className="text-purple-600 font-bold text-xs">MAX</span>;
    if (net.includes('TRUTV')) return <span className="text-green-600 font-bold text-xs">truTV</span>;
    if (net.includes('PRIME') || net.includes('AMAZON')) return <span className="text-blue-900 font-bold text-xs">PRIME</span>;
    return <span className="text-gray-600 font-medium text-xs">{network}</span>;
  };

  const getPopularityBadge = (score?: number) => {
    if (!score) return null;  // Don't show badge if no score
    if (score >= 80) return <span className="bg-red-100 text-red-800 text-xs px-2 py-1 rounded-full font-medium">🔥 Prime Time</span>;
    if (score >= 60) return <span className="bg-orange-100 text-orange-800 text-xs px-2 py-1 rounded-full font-medium">📺 National TV</span>;
    if (score >= 40) return <span className="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full font-medium">⭐ Featured</span>;
    return <span className="bg-gray-100 text-gray-800 text-xs px-2 py-1 rounded-full font-medium">📻 Popular</span>;
  };

  const GameCard = ({ game }: { game: PopularGame }) => (
    <div className="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow">
      {/* Date and Time Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center space-x-2 text-sm text-gray-500">
          <Calendar className="w-4 h-4" />
          <span>{formatFriendlyDate(game.commence_time || game.start_time)}</span>
        </div>
        <div className="flex items-center space-x-2 text-sm font-medium text-gray-700">
          <Clock className="w-4 h-4" />
          <span>{formatLocalTime(game.commence_time || game.start_time)}</span>
        </div>
      </div>

      {/* Teams and Popularity Badge */}
      <div className="flex justify-between items-start mb-3">
        <div className="flex items-center space-x-2">
          <div className="text-lg font-semibold text-gray-900">
            {game.away_team} @ {game.home_team}
          </div>
        </div>
        {getPopularityBadge(game.popularity_score)}
      </div>

      {/* Network Info */}
      {game.broadcast && (game.broadcast.networks?.length || game.broadcast.network) && (
        <div className="flex items-center justify-between text-sm text-gray-600 mb-3">
          <div className="flex items-center flex-wrap gap-2">
            <Tv className="w-4 h-4" />
            {/* Show networks array (new format) */}
            {game.broadcast.networks && game.broadcast.networks.length > 0 ? (
              game.broadcast.networks.map((network, idx) => (
                <span key={idx}>
                  {getNetworkIcon(network)}
                  {idx < game.broadcast.networks!.length - 1 && (
                    <span className="mx-1 text-gray-400">•</span>
                  )}
                </span>
              ))
            ) : (
              /* Fallback to legacy single network field */
              game.broadcast.network && (
                <>
                  {getNetworkIcon(game.broadcast.network)}
                  <span className="text-sm font-medium">{game.broadcast.network}</span>
                </>
              )
            )}
          </div>
        </div>
      )}

      {/* Badges and Actions */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3 text-xs text-gray-500">
          {game.broadcast?.is_national && (
            <span className="bg-green-100 text-green-800 px-2 py-1 rounded">National</span>
          )}
          {game.broadcast?.is_prime_time && (
            <span className="bg-purple-100 text-purple-800 px-2 py-1 rounded">Prime Time</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {onPlaceBet && (
            <button
              onClick={() => onPlaceBet(game)}
              className="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 transition-colors"
            >
              View Odds
            </button>
          )}

          {/* Player Props Button - only for supported sports */}
          {['americanfootball_nfl', 'basketball_nba', 'icehockey_nhl', 'baseball_mlb'].includes(game.sport_key) && (
            <button
              onClick={() => {
                setSelectedGameForProps(game);
                setShowPropsModal(true);
              }}
              className="text-xs bg-purple-600 text-white px-3 py-1 rounded hover:bg-purple-700 transition-colors flex items-center gap-1"
            >
              <User className="w-3 h-3" />
              Props
            </button>
          )}
        </div>
      </div>
    </div>
  );

  const SportSection = ({ sportKey, games, sportTitle }: {
    sportKey: string;
    games: PopularGame[];
    sportTitle: string;
  }) => {
    const displayGames = games.slice(0, maxGamesPerSport);

    if (displayGames.length === 0) return null;

    return (
      <div className="mb-6">
        <div className="flex items-center space-x-2 mb-3">
          <Activity className="w-5 h-5 text-[#A855F7]" />
          <h3 className="text-lg font-semibold text-gray-900">{sportTitle}</h3>
          <span className="bg-gray-100 text-gray-600 text-xs px-2 py-1 rounded-full">
            {displayGames.length} game{displayGames.length !== 1 ? 's' : ''}
          </span>
        </div>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {displayGames.map((game) => (
            <GameCard key={game.id} game={game} />
          ))}
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-[#A855F7]" />
          <span className="ml-2 text-gray-600">Loading popular games...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <AlertCircle className="w-5 h-5 text-red-500" />
            <span className="text-red-700">{error}</span>
          </div>
          <button
            onClick={() => fetchPopularGames()}
            className="text-red-600 hover:text-red-800 text-sm font-medium"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!gamesData || gamesData.total_count === 0) {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="text-center text-gray-500">
          <Tv className="w-12 h-12 mx-auto mb-3 text-gray-400" />
          <p className="text-lg font-medium">No Popular Games Found</p>
          <p className="text-sm">No nationally televised games are scheduled right now.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center space-x-3">
          <TrendingUp className="w-6 h-6 text-[#A855F7]" />
          <div>
            <h2 className="text-xl font-bold text-gray-900">Popular Games</h2>
            <p className="text-sm text-gray-600">
              {gamesData.total_count} nationally televised games • Updated {lastUpdate ? lastUpdate.toLocaleTimeString() : 'never'}
            </p>
          </div>
        </div>

        <button
          onClick={() => fetchPopularGames()}
          className="p-2 text-gray-400 hover:text-gray-600 transition-colors"
          title="Refresh popular games"
        >
          <RefreshCw className="w-5 h-5" />
        </button>
      </div>

      <div className="space-y-6">
        <SportSection
          sportKey="nfl"
          games={gamesData.popular_games.nfl}
          sportTitle="NFL"
        />
        <SportSection
          sportKey="nba"
          games={gamesData.popular_games.nba}
          sportTitle="NBA"
        />
        <SportSection
          sportKey="mlb"
          games={gamesData.popular_games.mlb}
          sportTitle="MLB"
        />
        <SportSection
          sportKey="nhl"
          games={gamesData.popular_games.nhl}
          sportTitle="NHL"
        />
      </div>

      {gamesData.message && (
        <div className="mt-4 text-xs text-gray-500 text-center">
          {gamesData.message}
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
                className="p-3 bg-white hover:bg-red-600 rounded-lg transition-all hover:rotate-90 group shadow-lg"
                aria-label="Close player props"
              >
                <span className="text-gray-900 text-2xl font-bold group-hover:text-white transition-colors leading-none">×</span>
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