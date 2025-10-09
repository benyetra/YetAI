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
  Calendar
} from 'lucide-react';
import { sportsAPI } from '../lib/api';
import {
  formatSportName,
  formatLocalDateTime,
  formatLocalTime,
  formatTimeFromNow,
  formatFriendlyDate
} from '../lib/formatting';

interface BroadcastInfo {
  network: string | null;
  is_national: boolean;
  is_prime_time: boolean;
  popularity_score: number;
}

interface PopularGame {
  id: string;
  home_team: string;
  away_team: string;
  start_time: string;
  sport: string;
  broadcast: BroadcastInfo;
  popularity_score: number;
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

  const getNetworkIcon = (network: string | null) => {
    if (!network) return <Tv className="w-4 h-4" />;

    const net = network.toUpperCase();
    if (net.includes('ESPN')) return <span className="text-red-600 font-bold text-xs">ESPN</span>;
    if (net.includes('NBC')) return <span className="text-blue-600 font-bold text-xs">NBC</span>;
    if (net.includes('CBS')) return <span className="text-blue-700 font-bold text-xs">CBS</span>;
    if (net.includes('FOX')) return <span className="text-blue-500 font-bold text-xs">FOX</span>;
    if (net.includes('ABC')) return <span className="text-gray-800 font-bold text-xs">ABC</span>;
    if (net.includes('TNT')) return <span className="text-orange-600 font-bold text-xs">TNT</span>;
    if (net.includes('PRIME') || net.includes('AMAZON')) return <span className="text-blue-900 font-bold text-xs">PRIME</span>;
    return <Tv className="w-4 h-4" />;
  };

  const getPopularityBadge = (score: number) => {
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
          <span>{formatFriendlyDate(game.start_time)}</span>
        </div>
        <div className="flex items-center space-x-2 text-sm font-medium text-gray-700">
          <Clock className="w-4 h-4" />
          <span>{formatLocalTime(game.start_time)}</span>
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
      {game.broadcast && (
        <div className="flex items-center justify-between text-sm text-gray-600 mb-3">
          <div className="flex items-center space-x-2">
            {getNetworkIcon(game.broadcast.network)}
            {game.broadcast.network && (
              <span className="text-sm font-medium">{game.broadcast.network}</span>
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

        {onPlaceBet && (
          <button
            onClick={() => onPlaceBet(game)}
            className="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 transition-colors"
          >
            View Odds
          </button>
        )}
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
    </div>
  );
}