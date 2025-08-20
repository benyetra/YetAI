'use client';

import { useState, useEffect } from 'react';
import { apiClient, sportsAPI } from '@/lib/api';
import { useAuth } from './Auth';
import { useNotifications } from './NotificationProvider';
import { formatSpread, formatTotal, formatGameStatus, formatSportName, formatLocalDateTime, formatTimeFromNow } from '@/lib/formatting';
import { 
  Activity, Clock, TrendingUp, AlertCircle, 
  DollarSign, Trophy, Target, Zap, Calendar,
  BarChart3, Users, RefreshCw, Wifi, WifiOff
} from 'lucide-react';

interface LiveMarket {
  game_id: string;
  sport: string;
  home_team: string;
  away_team: string;
  game_status: string;
  home_score: number;
  away_score: number;
  time_remaining: string | null;
  commence_time: string | null;
  markets_available: string[];
  moneyline_home: number | null;
  moneyline_away: number | null;
  spread_line: number | null;
  spread_home_odds: number | null;
  spread_away_odds: number | null;
  total_line: number | null;
  total_over_odds: number | null;
  total_under_odds: number | null;
  moneyline_bookmaker: string | null;
  spread_bookmaker: string | null;
  total_bookmaker: string | null;
  is_suspended: boolean;
  suspension_reason: string | null;
  last_updated: string;
}

interface UpcomingGame {
  id: string;
  sport_key: string;
  sport_title: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  bookmakers: Array<{
    key: string;
    title: string;
    markets: Array<{
      key: string;
      outcomes: Array<{
        name: string;
        price: number;
        point?: number;
      }>;
    }>;
  }>;
}

interface LiveBettingDashboardProps {
  onBetPlaced?: () => void;
}

export default function LiveBettingDashboard({ onBetPlaced }: LiveBettingDashboardProps) {
  const { token } = useAuth();
  const { addNotification } = useNotifications();
  const [markets, setMarkets] = useState<LiveMarket[]>([]);
  const [upcomingGames, setUpcomingGames] = useState<UpcomingGame[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedSport, setSelectedSport] = useState('all');
  const [activeTab, setActiveTab] = useState<'live' | 'upcoming'>('live');
  const [placingBet, setPlacingBet] = useState<string | null>(null);
  const [betAmount, setBetAmount] = useState('10');
  const [refreshInterval, setRefreshInterval] = useState<NodeJS.Timeout | null>(null);

  useEffect(() => {
    loadData();
    
    // Set up auto-refresh every 30 seconds
    const interval = setInterval(loadData, 30000);
    setRefreshInterval(interval);
    
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [selectedSport]);

  const loadData = async () => {
    try {
      // Load both live markets and upcoming games
      await Promise.all([loadMarkets(), loadUpcomingGames()]);
    } catch (error) {
      console.error('Failed to load data:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadMarkets = async () => {
    try {
      // Default to baseball_mlb when 'all' is selected to avoid rate limiting
      const sportParam = selectedSport !== 'all' ? selectedSport : 'baseball_mlb';
      const response = await apiClient.get(
        `/api/live-bets/markets?sport=${sportParam}`,
        token
      );
      
      if (response.status === 'success') {
        setMarkets(response.markets || []);
      }
    } catch (error) {
      console.error('Failed to load live markets:', error);
    }
  };

  const loadUpcomingGames = async () => {
    try {
      // Load upcoming games from the odds API
      const response = selectedSport === 'all' || selectedSport === 'popular' 
        ? await sportsAPI.getPopularOdds()
        : await sportsAPI.getOdds(selectedSport);
      
      if (response.status === 'success') {
        const games = response.games || [];
        setUpcomingGames(games);
      } else {
        console.error('Upcoming games API error:', response);
        setUpcomingGames([]); // Clear games on error
      }
    } catch (error) {
      console.error('Failed to load upcoming games:', error);
    }
  };

  const placeUpcomingBet = async (
    game: UpcomingGame,
    betType: string,
    selection: string,
    odds: number
  ) => {
    if (!token) {
      addNotification({
        type: 'error',
        title: 'Authentication Required',
        message: 'Please log in to place bets',
        priority: 'high'
      });
      return;
    }

    const betKey = `${game.id}-${betType}-${selection}`;
    setPlacingBet(betKey);

    try {
      // Use regular bet placement API for upcoming games
      const response = await apiClient.post('/api/bets/place', {
        game_id: game.id,
        bet_type: betType,
        selection,
        odds,
        amount: parseFloat(betAmount),
        // Include game details for better bet history display
        home_team: game.home_team,
        away_team: game.away_team,
        sport: game.sport_title || game.sport_key,
        commence_time: game.commence_time
      }, token);

      if (response.status === 'success') {
        addNotification({
          type: 'success',
          title: 'Bet Placed!',
          message: `$${betAmount} ${betType} bet on ${game.away_team} @ ${game.home_team}`,
          priority: 'high'
        });
        
        if (onBetPlaced) onBetPlaced();
      } else {
        // Handle API error response
        addNotification({
          type: 'error',
          title: 'Bet Failed',
          message: response.detail || response.message || 'Failed to place bet',
          priority: 'high'
        });
      }
    } catch (error: any) {
      addNotification({
        type: 'error',
        title: 'Bet Failed',
        message: error.detail || 'Failed to place bet',
        priority: 'high'
      });
    } finally {
      setPlacingBet(null);
    }
  };

  const placeLiveBet = async (
    market: LiveMarket, 
    betType: string, 
    selection: string, 
    odds: number
  ) => {
    if (!token) {
      addNotification({
        type: 'error',
        title: 'Authentication Required',
        message: 'Please log in to place bets',
        priority: 'high'
      });
      return;
    }

    const betKey = `${market.game_id}-${betType}-${selection}`;
    setPlacingBet(betKey);

    try {
      const response = await apiClient.post('/api/live-bets/place', {
        game_id: market.game_id,
        bet_type: betType,
        selection,
        odds,
        amount: parseFloat(betAmount),
        accept_odds_change: true,
        min_odds: odds * 0.9 // Accept up to 10% worse odds
      }, token);

      if (response.status === 'success') {
        addNotification({
          type: 'success',
          title: 'Live Bet Placed!',
          message: `$${betAmount} on ${market.home_team} vs ${market.away_team}`,
          priority: 'high'
        });
        
        if (onBetPlaced) onBetPlaced();
      }
    } catch (error: any) {
      addNotification({
        type: 'error',
        title: 'Bet Failed',
        message: error.detail || 'Failed to place live bet',
        priority: 'high'
      });
    } finally {
      setPlacingBet(null);
    }
  };

  const formatOdds = (odds: number | null) => {
    if (!odds) return '--';
    return odds > 0 ? `+${odds}` : odds.toString();
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case '1st_quarter':
      case '2nd_quarter':
      case '3rd_quarter':
      case '4th_quarter':
      case '1st_half':
      case '2nd_half':
      case '1st_inning':
      case '2nd_inning':
      case '3rd_inning':
      case '4th_inning':
      case '5th_inning':
      case '6th_inning':
      case '7th_inning':
      case '8th_inning':
      case '9th_inning':
      case 'overtime':
        return 'text-green-600';
      case 'halftime':
        return 'text-yellow-600';
      case 'final':
        return 'text-gray-600';
      default:
        return 'text-blue-600';
    }
  };

  const formatGameTime = (market: LiveMarket) => {
    // If it's a live game with time remaining, show that
    if (market.time_remaining && ['1st_quarter', '2nd_quarter', '3rd_quarter', '4th_quarter', 'halftime', '1st_inning', '2nd_inning', '3rd_inning', '4th_inning', '5th_inning', '6th_inning', '7th_inning', '8th_inning', '9th_inning'].includes(market.game_status)) {
      return market.time_remaining;
    }
    
    // Otherwise show the game start time
    if (market.commence_time) {
      const startTime = new Date(market.commence_time);
      return startTime.toLocaleTimeString('en-US', { 
        hour: 'numeric', 
        minute: '2-digit',
        hour12: true 
      });
    }
    
    return null;
  };

  const getBestOdds = (game: UpcomingGame, marketType: string, selection?: string) => {
    const bookmakers = game.bookmakers || [];
    let bestOdds = null;
    let bestBookmaker = '';

    for (const bookmaker of bookmakers) {
      for (const market of bookmaker.markets) {
        if (market.key === marketType) {
          for (const outcome of market.outcomes) {
            if (marketType === 'h2h') {
              if ((selection === 'home' && outcome.name === game.home_team) ||
                  (selection === 'away' && outcome.name === game.away_team)) {
                if (!bestOdds || outcome.price > bestOdds) {
                  bestOdds = outcome.price;
                  bestBookmaker = bookmaker.title;
                }
              }
            } else if (marketType === 'spreads' || marketType === 'totals') {
              if (outcome.name === selection) {
                if (!bestOdds || outcome.price > bestOdds) {
                  bestOdds = outcome.price;
                  bestBookmaker = bookmaker.title;
                }
              }
            }
          }
        }
      }
    }
    
    return { odds: bestOdds, bookmaker: bestBookmaker };
  };

  const getSpreadLine = (game: UpcomingGame) => {
    const bookmakers = game.bookmakers || [];
    for (const bookmaker of bookmakers) {
      for (const market of bookmaker.markets) {
        if (market.key === 'spreads') {
          for (const outcome of market.outcomes) {
            if (outcome.name === game.home_team && outcome.point) {
              return outcome.point;
            }
          }
        }
      }
    }
    return null;
  };

  const getTotalLine = (game: UpcomingGame) => {
    const bookmakers = game.bookmakers || [];
    for (const bookmaker of bookmakers) {
      for (const market of bookmaker.markets) {
        if (market.key === 'totals') {
          for (const outcome of market.outcomes) {
            if (outcome.point) {
              return outcome.point;
            }
          }
        }
      }
    }
    return null;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-red-600"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Tab Navigation */}
      <div className="flex items-center justify-between">
        <div className="flex space-x-1 bg-gray-100 rounded-lg p-1">
          <button
            onClick={() => setActiveTab('live')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'live'
                ? 'bg-white text-red-600 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <div className="flex items-center space-x-2">
              <Activity className="w-4 h-4" />
              <span>Live Betting</span>
              {markets.length > 0 && (
                <span className="bg-red-100 text-red-600 text-xs px-2 py-0.5 rounded-full">
                  {markets.length}
                </span>
              )}
            </div>
          </button>
          <button
            onClick={() => setActiveTab('upcoming')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'upcoming'
                ? 'bg-white text-red-600 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <div className="flex items-center space-x-2">
              <Calendar className="w-4 h-4" />
              <span>Upcoming Games</span>
              {upcomingGames.length > 0 && (
                <span className="bg-blue-100 text-blue-600 text-xs px-2 py-0.5 rounded-full">
                  {upcomingGames.length}
                </span>
              )}
            </div>
          </button>
        </div>

        <div className="flex items-center space-x-2">
          <Clock className="w-4 h-4 text-gray-500" />
          <span className="text-sm text-gray-600">Auto-refreshing every 30s</span>
        </div>
      </div>

      {/* Bet Amount Selector */}
      <div className="flex items-center justify-between bg-gray-50 rounded-lg p-4">
        <div className="flex items-center space-x-4">
          <label className="text-sm font-medium text-gray-700">Bet Amount:</label>
          <div className="flex space-x-2">
            {['10', '25', '50', '100', '250'].map(amount => (
              <button
                key={amount}
                onClick={() => setBetAmount(amount)}
                className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${
                  betAmount === amount
                    ? 'bg-red-600 text-white'
                    : 'bg-white text-gray-700 hover:bg-gray-100'
                }`}
              >
                ${amount}
              </button>
            ))}
            <input
              type="number"
              value={betAmount}
              onChange={(e) => setBetAmount(e.target.value)}
              className="w-20 px-2 py-1 border border-gray-300 rounded-lg text-sm"
              min="1"
              max="10000"
            />
          </div>
        </div>
        <div className="flex items-center space-x-4">
          <select
            value={selectedSport}
            onChange={(e) => setSelectedSport(e.target.value)}
            className="px-3 py-1 border border-gray-300 rounded-lg text-sm"
          >
            <option value="all">All Sports</option>
            <option value="americanfootball_nfl">NFL</option>
            <option value="basketball_nba">NBA</option>
            <option value="baseball_mlb">MLB</option>
          </select>
        </div>
      </div>

      {/* Content based on active tab */}
      {activeTab === 'live' ? (
        markets.length === 0 ? (
          <div className="text-center py-12">
            <Activity className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">No Live Games</h3>
            <p className="text-gray-600">Check back when games are in progress</p>
          </div>
        ) : (
          <div className="space-y-4">
            {markets.map(market => (
          <div
            key={market.game_id}
            className={`bg-white rounded-lg border ${
              market.is_suspended ? 'border-yellow-400 bg-yellow-50' : 'border-gray-200'
            } overflow-hidden`}
          >
            {/* Game Header */}
            <div className="bg-gray-50 px-6 py-4 border-b border-gray-200">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <div>
                    <div className="flex items-center space-x-2">
                      <h3 className="font-semibold text-gray-900">
                        {market.home_team} vs {market.away_team}
                      </h3>
                      <span className={`text-sm font-medium ${getStatusColor(market.game_status)}`}>
                        {formatGameStatus(market.game_status)}
                      </span>
                    </div>
                    <div className="flex items-center space-x-4 mt-1">
                      <span className="text-sm text-gray-600">{market.sport}</span>
                      {formatGameTime(market) && (
                        <span className="text-sm text-gray-600">{formatGameTime(market)}</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-bold text-gray-900">
                    {market.home_score} - {market.away_score}
                  </div>
                  {market.is_suspended && (
                    <div className="flex items-center text-yellow-600 text-sm mt-1">
                      <AlertCircle className="w-4 h-4 mr-1" />
                      {market.suspension_reason || 'Temporarily suspended'}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Betting Markets */}
            {!market.is_suspended && (
              <div className="p-6">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  {/* Moneyline */}
                  {market.moneyline_home && market.moneyline_away && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-700 mb-3">Moneyline</h4>
                      <div className="space-y-2">
                        <button
                          onClick={() => placeLiveBet(market, 'moneyline', 'home', market.moneyline_home!)}
                          disabled={placingBet === `${market.game_id}-moneyline-home`}
                          className="w-full px-4 py-3 bg-white border border-gray-300 rounded-lg hover:bg-red-50 hover:border-red-500 transition-colors disabled:opacity-50"
                        >
                          <div className="flex justify-between items-center">
                            <span className="font-medium">{market.home_team}</span>
                            <div className="text-right">
                              <span className="font-bold text-red-600">
                                {formatOdds(market.moneyline_home)}
                              </span>
                              {market.moneyline_bookmaker && (
                                <div className="text-xs text-gray-500">{market.moneyline_bookmaker}</div>
                              )}
                            </div>
                          </div>
                        </button>
                        <button
                          onClick={() => placeLiveBet(market, 'moneyline', 'away', market.moneyline_away!)}
                          disabled={placingBet === `${market.game_id}-moneyline-away`}
                          className="w-full px-4 py-3 bg-white border border-gray-300 rounded-lg hover:bg-red-50 hover:border-red-500 transition-colors disabled:opacity-50"
                        >
                          <div className="flex justify-between items-center">
                            <span className="font-medium">{market.away_team}</span>
                            <div className="text-right">
                              <span className="font-bold text-red-600">
                                {formatOdds(market.moneyline_away)}
                              </span>
                              {market.moneyline_bookmaker && (
                                <div className="text-xs text-gray-500">{market.moneyline_bookmaker}</div>
                              )}
                            </div>
                          </div>
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Spread */}
                  {market.spread_line && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-700 mb-3">Spread</h4>
                      <div className="space-y-2">
                        <button
                          onClick={() => placeLiveBet(market, 'spread', 'home', market.spread_home_odds || -110)}
                          disabled={placingBet === `${market.game_id}-spread-home`}
                          className="w-full px-4 py-3 bg-white border border-gray-300 rounded-lg hover:bg-red-50 hover:border-red-500 transition-colors disabled:opacity-50"
                        >
                          <div className="flex justify-between items-center">
                            <span className="font-medium">
                              {market.home_team} {formatSpread(market.spread_line)}
                            </span>
                            <div className="text-right">
                              <span className="font-bold text-red-600">
                                {formatOdds(market.spread_home_odds || -110)}
                              </span>
                              {market.spread_bookmaker && (
                                <div className="text-xs text-gray-500">{market.spread_bookmaker}</div>
                              )}
                            </div>
                          </div>
                        </button>
                        <button
                          onClick={() => placeLiveBet(market, 'spread', 'away', market.spread_away_odds || -110)}
                          disabled={placingBet === `${market.game_id}-spread-away`}
                          className="w-full px-4 py-3 bg-white border border-gray-300 rounded-lg hover:bg-red-50 hover:border-red-500 transition-colors disabled:opacity-50"
                        >
                          <div className="flex justify-between items-center">
                            <span className="font-medium">
                              {market.away_team} {formatSpread(-market.spread_line)}
                            </span>
                            <div className="text-right">
                              <span className="font-bold text-red-600">
                                {formatOdds(market.spread_away_odds || -110)}
                              </span>
                              {market.spread_bookmaker && (
                                <div className="text-xs text-gray-500">{market.spread_bookmaker}</div>
                              )}
                            </div>
                          </div>
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Total */}
                  {market.total_line && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-700 mb-3">Total</h4>
                      <div className="space-y-2">
                        <button
                          onClick={() => placeLiveBet(market, 'total', 'over', market.total_over_odds || -110)}
                          disabled={placingBet === `${market.game_id}-total-over`}
                          className="w-full px-4 py-3 bg-white border border-gray-300 rounded-lg hover:bg-red-50 hover:border-red-500 transition-colors disabled:opacity-50"
                        >
                          <div className="flex justify-between items-center">
                            <span className="font-medium">
                              Over {formatTotal(market.total_line)}
                            </span>
                            <div className="text-right">
                              <span className="font-bold text-red-600">
                                {formatOdds(market.total_over_odds || -110)}
                              </span>
                              {market.total_bookmaker && (
                                <div className="text-xs text-gray-500">{market.total_bookmaker}</div>
                              )}
                            </div>
                          </div>
                        </button>
                        <button
                          onClick={() => placeLiveBet(market, 'total', 'under', market.total_under_odds || -110)}
                          disabled={placingBet === `${market.game_id}-total-under`}
                          className="w-full px-4 py-3 bg-white border border-gray-300 rounded-lg hover:bg-red-50 hover:border-red-500 transition-colors disabled:opacity-50"
                        >
                          <div className="flex justify-between items-center">
                            <span className="font-medium">
                              Under {formatTotal(market.total_line)}
                            </span>
                            <div className="text-right">
                              <span className="font-bold text-red-600">
                                {formatOdds(market.total_under_odds || -110)}
                              </span>
                              {market.total_bookmaker && (
                                <div className="text-xs text-gray-500">{market.total_bookmaker}</div>
                              )}
                            </div>
                          </div>
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
          </div>
        )
      ) : (
        // Upcoming Games Tab
        upcomingGames.length === 0 ? (
          <div className="text-center py-12">
            <Calendar className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">No Upcoming Games</h3>
            <p className="text-gray-600">No games available for the selected sport</p>
          </div>
        ) : (
          <div className="space-y-6">
            {upcomingGames.map(game => {
              const homeMoneyline = getBestOdds(game, 'h2h', 'home');
              const awayMoneyline = getBestOdds(game, 'h2h', 'away');
              const spreadLine = getSpreadLine(game);
              const totalLine = getTotalLine(game);
              
              return (
                <div key={game.id} className="bg-white rounded-lg border border-gray-200 overflow-hidden hover:shadow-md transition-shadow">
                  {/* Game Header */}
                  <div className="bg-gray-50 px-6 py-4 border-b border-gray-200">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-4">
                        <div>
                          <div className="flex items-center space-x-2">
                            <h3 className="font-semibold text-gray-900">
                              {game.away_team} @ {game.home_team}
                            </h3>
                            <span className="text-sm font-medium text-purple-600 bg-purple-100 px-2 py-1 rounded">
                              {formatSportName(game.sport_key)}
                            </span>
                          </div>
                          <div className="flex items-center space-x-4 mt-1">
                            <span className="text-sm text-gray-600">
                              {formatLocalDateTime(game.commence_time)}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-sm text-gray-600">
                          {game.bookmakers?.length || 0} bookmakers
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Betting Markets */}
                  <div className="p-6">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                      {/* Moneyline */}
                      <div>
                        <h4 className="text-sm font-medium text-gray-700 mb-3 flex items-center">
                          <Target className="w-4 h-4 mr-1" />
                          Moneyline
                        </h4>
                        <div className="space-y-2">
                          <button
                            onClick={() => awayMoneyline.odds && placeUpcomingBet(game, 'moneyline', 'away', awayMoneyline.odds)}
                            disabled={!awayMoneyline.odds || placingBet === `${game.id}-moneyline-away`}
                            className="w-full flex items-center justify-between p-3 bg-white border border-gray-300 rounded-lg hover:bg-purple-50 hover:border-purple-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            <span className="font-medium text-gray-900">{game.away_team}</span>
                            <div className="text-right">
                              <div className="font-bold text-purple-600">
                                {awayMoneyline.odds ? formatOdds(awayMoneyline.odds) : 'N/A'}
                              </div>
                              {awayMoneyline.bookmaker && (
                                <div className="text-xs text-gray-500">{awayMoneyline.bookmaker}</div>
                              )}
                            </div>
                          </button>
                          <button
                            onClick={() => homeMoneyline.odds && placeUpcomingBet(game, 'moneyline', 'home', homeMoneyline.odds)}
                            disabled={!homeMoneyline.odds || placingBet === `${game.id}-moneyline-home`}
                            className="w-full flex items-center justify-between p-3 bg-white border border-gray-300 rounded-lg hover:bg-purple-50 hover:border-purple-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            <span className="font-medium text-gray-900">{game.home_team}</span>
                            <div className="text-right">
                              <div className="font-bold text-purple-600">
                                {homeMoneyline.odds ? formatOdds(homeMoneyline.odds) : 'N/A'}
                              </div>
                              {homeMoneyline.bookmaker && (
                                <div className="text-xs text-gray-500">{homeMoneyline.bookmaker}</div>
                              )}
                            </div>
                          </button>
                        </div>
                      </div>

                      {/* Spread */}
                      {spreadLine !== null && (
                        <div>
                          <h4 className="text-sm font-medium text-gray-700 mb-3 flex items-center">
                            <BarChart3 className="w-4 h-4 mr-1" />
                            Spread
                          </h4>
                          <div className="space-y-2">
                            <button
                              onClick={() => placeUpcomingBet(game, 'spread', 'away', -110)}
                              disabled={placingBet === `${game.id}-spread-away`}
                              className="w-full flex items-center justify-between p-3 bg-white border border-gray-300 rounded-lg hover:bg-purple-50 hover:border-purple-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <span className="font-medium text-gray-900">
                                {game.away_team} {formatSpread(-spreadLine)}
                              </span>
                              <div className="font-bold text-purple-600">
                                {formatOdds(-110)}
                              </div>
                            </button>
                            <button
                              onClick={() => placeUpcomingBet(game, 'spread', 'home', -110)}
                              disabled={placingBet === `${game.id}-spread-home`}
                              className="w-full flex items-center justify-between p-3 bg-white border border-gray-300 rounded-lg hover:bg-purple-50 hover:border-purple-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <span className="font-medium text-gray-900">
                                {game.home_team} {formatSpread(spreadLine)}
                              </span>
                              <div className="font-bold text-purple-600">
                                {formatOdds(-110)}
                              </div>
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Total */}
                      {totalLine !== null && (
                        <div>
                          <h4 className="text-sm font-medium text-gray-700 mb-3 flex items-center">
                            <TrendingUp className="w-4 h-4 mr-1" />
                            Total
                          </h4>
                          <div className="space-y-2">
                            <button
                              onClick={() => placeUpcomingBet(game, 'total', 'over', -110)}
                              disabled={placingBet === `${game.id}-total-over`}
                              className="w-full flex items-center justify-between p-3 bg-white border border-gray-300 rounded-lg hover:bg-purple-50 hover:border-purple-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <span className="font-medium text-gray-900">
                                Over {formatTotal(totalLine)}
                              </span>
                              <div className="font-bold text-purple-600">
                                {formatOdds(-110)}
                              </div>
                            </button>
                            <button
                              onClick={() => placeUpcomingBet(game, 'total', 'under', -110)}
                              disabled={placingBet === `${game.id}-total-under`}
                              className="w-full flex items-center justify-between p-3 bg-white border border-gray-300 rounded-lg hover:bg-purple-50 hover:border-purple-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <span className="font-medium text-gray-900">
                                Under {formatTotal(totalLine)}
                              </span>
                              <div className="font-bold text-purple-600">
                                {formatOdds(-110)}
                              </div>
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )
      )}
    </div>
  );
}