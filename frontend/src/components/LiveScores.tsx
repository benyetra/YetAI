'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { 
  Trophy, 
  Clock, 
  RefreshCw, 
  AlertCircle, 
  CheckCircle,
  Activity,
  Calendar,
  Users,
  Target
} from 'lucide-react';
import { sportsAPI } from '../lib/api';
import { 
  formatSportName, 
  formatLocalDateTime, 
  formatLocalDate, 
  formatLocalTime, 
  formatTimeFromNow, 
  formatFriendlyDate 
} from '../lib/formatting';

interface Score {
  id: string;
  sport_key: string;
  sport_title: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  completed: boolean;
  home_score: number | null;
  away_score: number | null;
  last_update: string;
}

interface ScoresData {
  status: string;
  sport: string;
  days_from: number;
  count: number;
  scores: Score[];
  cached?: boolean;
  last_updated: string;
}

interface LiveScoresProps {
  sportKey: string;
  daysFrom?: number;
  autoRefresh?: boolean;
  refreshInterval?: number;
  maxScores?: number;
  showCompleted?: boolean;
  showLive?: boolean;
}

export function LiveScores({
  sportKey,
  daysFrom = 1,
  autoRefresh = true,
  refreshInterval = 600000, // 10 minutes
  maxScores = 20,
  showCompleted = true,
  showLive = true
}: LiveScoresProps) {
  const [scoresData, setScoresData] = useState<ScoresData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [filter, setFilter] = useState<'all' | 'completed' | 'live'>('all');

  const fetchScores = useCallback(async (showLoader: boolean = true) => {
    try {
      if (showLoader) setLoading(true);
      setError(null);

      const data = await sportsAPI.getScores(sportKey, daysFrom);
      setScoresData(data);
      setLastUpdate(new Date());
      
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch scores';
      setError(errorMessage);
    } finally {
      if (showLoader) setLoading(false);
    }
  }, [sportKey, daysFrom]);

  // Initial load
  useEffect(() => {
    fetchScores();
  }, [fetchScores]);

  // Auto refresh
  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      fetchScores(false); // Background refresh without loader
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, fetchScores]);

  const getFilteredScores = () => {
    if (!scoresData?.scores) return [];

    let filtered = scoresData.scores;

    switch (filter) {
      case 'completed':
        filtered = filtered.filter(score => score.completed);
        break;
      case 'live':
        filtered = filtered.filter(score => !score.completed && isGameLive(score));
        break;
      default:
        break;
    }

    // Sort by commence time (most recent first)
    return filtered
      .sort((a, b) => new Date(b.commence_time).getTime() - new Date(a.commence_time).getTime())
      .slice(0, maxScores);
  };

  const isGameLive = (score: Score) => {
    const now = new Date();
    const gameTime = new Date(score.commence_time);
    const hoursElapsed = (now.getTime() - gameTime.getTime()) / (1000 * 60 * 60);
    
    // Consider a game live if it started within the last 4 hours and isn't completed
    return hoursElapsed > 0 && hoursElapsed < 4 && !score.completed;
  };

  const getGameStatus = (score: Score) => {
    if (score.completed) {
      return 'Final';
    }
    
    const now = new Date();
    const gameTime = new Date(score.commence_time);
    
    if (now < gameTime) {
      return 'Scheduled';
    }
    
    if (isGameLive(score)) {
      return 'Live';
    }
    
    return 'In Progress';
  };

  const getWinner = (score: Score) => {
    if (!score.completed || score.home_score === null || score.away_score === null) {
      return null;
    }
    
    if (score.home_score > score.away_score) {
      return 'home';
    } else if (score.away_score > score.home_score) {
      return 'away';
    }
    
    return 'tie';
  };

  // formatDate function replaced with formatFriendlyDate from formatting utils

  if (loading && !scoresData) {
    return (
      <div className="bg-white rounded-lg shadow-lg p-6">
        <div className="flex items-center justify-center h-40">
          <div className="flex items-center space-x-2">
            <RefreshCw className="w-5 h-5 animate-spin text-[#A855F7]" />
            <span className="text-gray-600">Loading scores...</span>
          </div>
        </div>
      </div>
    );
  }

  const filteredScores = getFilteredScores();

  return (
    <div className="bg-white rounded-lg shadow-lg">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Trophy className="w-6 h-6 text-[#A855F7]" />
            <div>
              <h2 className="text-lg font-bold text-gray-900">
                {formatSportName(scoresData?.sport || sportKey)} Scores
              </h2>
              <p className="text-sm text-gray-600">
                {scoresData?.count || 0} games • Last {daysFrom} day{daysFrom !== 1 ? 's' : ''}
              </p>
            </div>
          </div>
          
          <div className="flex items-center space-x-2">
            {/* Cache indicator */}
            {scoresData?.cached && (
              <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-1 rounded">
                Cached
              </span>
            )}
            
            {/* Refresh button */}
            <button
              onClick={() => fetchScores(true)}
              disabled={loading}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Filter tabs */}
        <div className="mt-4 flex space-x-1 bg-gray-100 rounded-lg p-1">
          <button
            onClick={() => setFilter('all')}
            className={`px-3 py-2 text-sm font-medium rounded-md transition-colors ${
              filter === 'all'
                ? 'bg-white text-[#A855F7] shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            All Games
          </button>
          {showLive && (
            <button
              onClick={() => setFilter('live')}
              className={`px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                filter === 'live'
                  ? 'bg-white text-[#A855F7] shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Live
            </button>
          )}
          {showCompleted && (
            <button
              onClick={() => setFilter('completed')}
              className={`px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                filter === 'completed'
                  ? 'bg-white text-[#A855F7] shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Final
            </button>
          )}
        </div>
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
              onClick={() => fetchScores(true)}
              className="mt-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {/* No Data State */}
      {scoresData && filteredScores.length === 0 && !error && (
        <div className="p-6">
          <div className="text-center py-8">
            <Calendar className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">No Scores Available</h3>
            <p className="text-gray-600">
              No games found for the selected filter in the last {daysFrom} day{daysFrom !== 1 ? 's' : ''}.
            </p>
          </div>
        </div>
      )}

      {/* Scores List */}
      {filteredScores.length > 0 && (
        <div className="divide-y divide-gray-200">
          {filteredScores.map((score) => {
            const status = getGameStatus(score);
            const winner = getWinner(score);
            const isLive = status === 'Live';
            
            return (
              <div key={score.id} className="p-6 hover:bg-gray-50 transition-colors">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center space-x-2">
                    <span className="text-sm font-medium text-[#A855F7] bg-[#A855F7]/10 px-2 py-1 rounded">
                      {formatSportName(score.sport_key)}
                    </span>
                    <div className={`flex items-center space-x-1 text-sm px-2 py-1 rounded ${
                      isLive ? 'text-red-700 bg-red-100' :
                      status === 'Final' ? 'text-green-700 bg-green-100' :
                      'text-gray-700 bg-gray-100'
                    }`}>
                      {isLive ? (
                        <Activity className="w-3 h-3" />
                      ) : status === 'Final' ? (
                        <CheckCircle className="w-3 h-3" />
                      ) : (
                        <Clock className="w-3 h-3" />
                      )}
                      <span>{status}</span>
                    </div>
                  </div>
                  
                  <div className="text-right">
                    <div className="text-sm text-gray-600">
                      {formatFriendlyDate(score.commence_time)}
                    </div>
                    <div className="text-xs text-gray-500">
                      {formatLocalTime(score.commence_time)}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-4 items-center">
                  {/* Away Team */}
                  <div className={`text-right ${winner === 'away' ? 'font-bold text-[#A855F7]' : ''}`}>
                    <div className="flex items-center justify-end space-x-2">
                      <span className="text-lg font-semibold">{score.away_team}</span>
                      <Users className="w-4 h-4 text-gray-400" />
                    </div>
                    <div className="text-sm text-gray-600">Away</div>
                  </div>

                  {/* Score */}
                  <div className="text-center">
                    {score.home_score !== null && score.away_score !== null ? (
                      <div className="flex items-center justify-center space-x-2">
                        <span className={`text-2xl font-bold ${winner === 'away' ? 'text-[#A855F7]' : 'text-gray-900'}`}>
                          {score.away_score}
                        </span>
                        <span className="text-gray-400">-</span>
                        <span className={`text-2xl font-bold ${winner === 'home' ? 'text-[#A855F7]' : 'text-gray-900'}`}>
                          {score.home_score}
                        </span>
                      </div>
                    ) : (
                      <div className="text-gray-500">
                        {status === 'Scheduled' ? 'vs' : 'TBD'}
                      </div>
                    )}
                    
                    {winner === 'tie' && score.completed && (
                      <div className="text-xs text-orange-600 font-medium mt-1">Tie</div>
                    )}
                  </div>

                  {/* Home Team */}
                  <div className={`text-left ${winner === 'home' ? 'font-bold text-[#A855F7]' : ''}`}>
                    <div className="flex items-center space-x-2">
                      <Users className="w-4 h-4 text-gray-400" />
                      <span className="text-lg font-semibold">{score.home_team}</span>
                    </div>
                    <div className="text-sm text-gray-600">Home</div>
                  </div>
                </div>

                {/* Additional info */}
                <div className="mt-4 pt-3 border-t border-gray-100">
                  <div className="flex items-center justify-between text-xs text-gray-500">
                    <span>Game ID: {score.id}</span>
                    <span>
                      Updated {formatLocalDateTime(score.last_update)}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Show more link */}
      {scoresData && scoresData.scores.length > maxScores && (
        <div className="px-6 py-4 border-t border-gray-200 text-center">
          <span className="text-sm text-gray-600">
            Showing {Math.min(maxScores, filteredScores.length)} of {scoresData.scores.length} games
          </span>
        </div>
      )}

      {/* Last update info */}
      {lastUpdate && (
        <div className="px-6 py-3 border-t border-gray-200 bg-gray-50">
          <div className="flex items-center justify-center text-xs text-gray-500">
            <Activity className="w-3 h-3 mr-1" />
            <span>Last updated {formatLocalTime(lastUpdate.toISOString())}</span>
          </div>
        </div>
      )}
    </div>
  );
}