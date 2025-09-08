"use client";

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { TrendingUp, Target, Users, MessageCircle, Clock, Send, BarChart3, Crown } from 'lucide-react';
import PerformanceDashboard from './PerformanceDashboard';
import { useAuth } from './Auth';
import BetModal from './BetModal';
import { oddsUtils } from '../lib/api';
import { 
  formatSportName, 
  formatLocalDateTime, 
  formatLocalDate, 
  formatLocalTime, 
  formatTimeFromNow, 
  formatOdds as formatOddsDisplay, 
  formatTotal,
  formatSpread,
  formatGameStatus,
  formatFriendlyDate 
} from '../lib/formatting';

// Types
type Message = {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  type?: string;
};

type Suggestion = {
  text: string;
  category: string;
};

type Game = {
  away_team_full?: string;
  home_team_full?: string;
  venue?: string;
  week?: number;
  date?: string;
  status?: string;
  away_team?: string;
  home_team?: string;
  commence_time?: string;
  moneyline?: any;
  spread?: any;
  total?: any;
};

type Prediction = {
  game_id: string;
  matchup: string;
  game_time: string;
  predictions: Array<{
    type: string;
    recommendation: string;
    confidence: number;
    reasoning: string;
    book: string;
  }>;
};

type FantasyProjection = {
  player_name: string;
  position: string;
  team: string;
  opponent: string;
  projected_points: number;
  floor: number;
  ceiling: number;
  snap_percentage: number;
  injury_status: string;
};

export default function BettingDashboard() {
  const router = useRouter();
  const [games, setGames] = useState<Game[]>([]);
  const [odds, setOdds] = useState<Game[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [fantasyProjections, setFantasyProjections] = useState<FantasyProjection[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<string>('predictions');
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  
  // Chat state
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentMessage, setCurrentMessage] = useState<string>('');
  const [chatLoading, setChatLoading] = useState<boolean>(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  
  // Bet modal state
  const [showBetModal, setShowBetModal] = useState(false);
  const [selectedGame, setSelectedGame] = useState<any>(null);

  // Auth integration
  const { user, token, isAuthenticated } = useAuth();

  const api = {
    baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
    get: async (endpoint: string): Promise<any> => {
      try {
        const headers: any = { 'Content-Type': 'application/json' };
        if (token) {
          headers['Authorization'] = `Bearer ${token}`;
        }
        const response = await fetch(`${api.baseURL}${endpoint}`, { headers });
        return await response.json();
      } catch (error) {
        console.error(`API Error: ${endpoint}`, error);
        return null;
      }
    },
    post: async (endpoint: string, data: any): Promise<any> => {
      try {
        const headers: any = { 'Content-Type': 'application/json' };
        if (token) {
          headers['Authorization'] = `Bearer ${token}`;
        }
        const response = await fetch(`${api.baseURL}${endpoint}`, {
          method: 'POST',
          headers,
          body: JSON.stringify(data)
        });
        return await response.json();
      } catch (error) {
        console.error(`API Error: ${endpoint}`, error);
        return null;
      }
    }
  };

  // Fetch all data
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      
      const [gamesData, oddsData, predictionsData, fantasyData] = await Promise.all([
        api.get('/api/games/nfl'),
        api.get('/api/odds/nfl'),
        api.get('/api/predictions/daily'),
        api.get('/api/fantasy/projections')
      ]);

      if (gamesData) setGames(gamesData.games || []);
      if (oddsData) setOdds(oddsData.odds || []);
      if (predictionsData) setPredictions(predictionsData.predictions || []);
      if (fantasyData) setFantasyProjections(fantasyData.projections || []);
      
      setLastUpdated(new Date().toLocaleTimeString());
      setLoading(false);
    };

    fetchData();
    loadChatSuggestions();
    
    // Refresh every 5 minutes
    const interval = setInterval(fetchData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);
  
  // Load chat suggestions
  const loadChatSuggestions = async () => {
    const suggestionsData = await api.get('/api/chat/suggestions');
    if (suggestionsData) {
      setSuggestions(suggestionsData.suggestions || []);
    }
  };
  
  // Send chat message
  const sendMessage = async (messageText = null) => {
    const messageToSend = messageText || currentMessage.trim();
    if (!messageToSend) return;
    
    const userMessage: Message = {
      role: 'user' as const,
      content: messageToSend,
      timestamp: new Date().toISOString()
    };
    
    setMessages(prev => [...prev, userMessage]);
    setCurrentMessage('');
    setChatLoading(true);
    
    try {
      const response = await api.post('/api/chat/message', {
        message: messageToSend,
        conversation_history: messages.slice(-10) // Last 10 messages
      });
      
      if (response && response.message) {
        const aiMessage = {
          role: 'assistant',
          content: response.message,
          timestamp: response.timestamp || new Date().toISOString(),
          type: response.type
        };
        setMessages(prev => [...prev, aiMessage]);
      }
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage = {
        role: 'assistant',
        content: "I'm sorry, I'm having trouble processing that request right now. Please try again.",
        timestamp: new Date().toISOString(),
        type: 'error'
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setChatLoading(false);
    }
  };

  // Handle place bet
  const handlePlaceBet = (game: any) => {
    // Check if this is a live odds game with bookmakers
    if (game.bookmakers && game.bookmakers.length > 0) {
      // Convert live odds data to simple format for BetModal
      const simpleGame = oddsUtils.toSimpleGame(game);
      setSelectedGame(simpleGame);
    } else {
      // Handle legacy game format
      const enhancedGame = {
        ...game,
        id: game.id || `game_${Math.random()}`,
        sport: game.sport || game.sport_key || 'NFL',
        commence_time: game.commence_time || game.date || new Date().toISOString(),
        home_odds: game.moneyline?.home || -110,
        away_odds: game.moneyline?.away || +100,
        total: parseFloat(formatTotal(game.total?.point || 45.5)),
        spread: parseFloat(formatSpread(game.spread?.home?.point || -3.5)),
        home_team: game.home_team || game.home_team_full || 'Home Team',
        away_team: game.away_team || game.away_team_full || 'Away Team'
      };
      setSelectedGame(enhancedGame);
    }
    setShowBetModal(true);
  };

  // Mock predictions for demo (since real predictions need aligned data)
  const mockPredictions = [
    {
      game_id: '1',
      matchup: 'Chiefs @ Bills',
      game_time: '2024-01-14T18:00:00Z',
      predictions: [
        {
          type: 'spread',
          recommendation: 'Bills -2.5',
          confidence: 78,
          reasoning: 'Bills at home in playoffs with strong defensive showing. Weather favors under but Bills should cover small spread.',
          book: 'DraftKings'
        }
      ]
    },
    {
      game_id: '2',
      matchup: 'Cowboys @ 49ers',
      game_time: '2024-01-14T20:30:00Z',
      predictions: [
        {
          type: 'moneyline',
          recommendation: 'Cowboys +185',
          confidence: 65,
          reasoning: 'Cowboys getting excellent value as road dogs. 49ers dealing with key injuries on defense.',
          book: 'FanDuel'
        },
        {
          type: 'total',
          recommendation: 'Under 47.5',
          confidence: 72,
          reasoning: 'Both teams strong defensively. Weather conditions and playoff pressure favor under.',
          book: 'BetMGM'
        }
      ]
    }
  ];

  const displayPredictions = predictions.length > 0 ? predictions : mockPredictions;

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading AI predictions...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">AI Sports Betting</h1>
              <p className="text-sm text-gray-500">
                Last updated: {lastUpdated} • {games.length} games • {odds.length} odds
                {isAuthenticated && user && (
                  <span className="ml-2">
                    • Welcome back, {user.first_name || user.username}
                    {user.subscription_tier !== 'free' && (
                      <Crown className="w-4 h-4 inline ml-1 text-yellow-500" />
                    )}
                  </span>
                )}
              </p>
            </div>
            <div className="flex items-center space-x-4">
              <div className="flex items-center text-green-600">
                <div className="w-2 h-2 bg-green-500 rounded-full mr-2"></div>
                <span className="text-sm font-medium">Live Data</span>
              </div>
              {isAuthenticated && user?.subscription_tier !== 'free' && (
                <div className="flex items-center text-blue-600">
                  <Crown className="w-4 h-4 mr-1" />
                  <span className="text-sm font-medium capitalize">{user.subscription_tier}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Navigation Tabs */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-8">
            {[
              { id: 'predictions', name: 'YetAI Bets', icon: Target },
              { id: 'fantasy', name: 'Fantasy', icon: Users },
              { id: 'performance', name: 'Performance', icon: BarChart3 },
              { id: 'chat', name: 'AI Assistant', icon: MessageCircle },
              { id: 'games', name: 'Games', icon: Clock },
              { id: 'odds', name: 'Live Odds', icon: TrendingUp },
              ...(isAuthenticated ? [{ id: 'personalized', name: 'My Picks', icon: Crown }] : [])
            ].map(({ id, name, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`${
                  activeTab === id
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm flex items-center`}
              >
                <Icon className="w-4 h-4 mr-2" />
                {name}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        
        {/* YetAI Bets Tab */}
        {activeTab === 'predictions' && (
          <div className="space-y-6">
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <div className="flex items-center">
                <Target className="w-5 h-5 text-blue-600 mr-2" />
                <p className="text-blue-800 text-sm">
                  <strong>YetAI Bets:</strong> Our expert AI provides daily best bets with tracked performance. Free users get 1 bet per day, Pro users get 3+ bets daily.
                </p>
              </div>
            </div>

            {/* Predictions Cards */}
            <div className="grid gap-6">
              {displayPredictions.map((game, idx) => (
                <div key={idx} className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                  <div className="mb-4">
                    <h3 className="text-lg font-semibold text-gray-900">{game.matchup}</h3>
                    <p className="text-sm text-gray-500">
                      {new Date(game.game_time).toLocaleString()}
                    </p>
                  </div>
                  
                  <div className="space-y-4">
                    {game.predictions.map((pred, predIdx) => (
                      <div key={predIdx} className="border border-gray-200 rounded-lg p-4">
                        <div className="flex justify-between items-start mb-2">
                          <div>
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 mb-2">
                              {pred.type}
                            </span>
                            <h4 className="text-lg font-medium text-gray-900">{pred.recommendation}</h4>
                          </div>
                          <div className="text-right">
                            <p className="text-sm text-gray-600">Confidence</p>
                            <p className={`text-lg font-bold ${
                              pred.confidence >= 80 ? 'text-green-600' :
                              pred.confidence >= 60 ? 'text-yellow-600' : 'text-red-600'
                            }`}>
                              {pred.confidence}%
                            </p>
                          </div>
                        </div>
                        <p className="text-sm text-gray-600 mb-2">{pred.reasoning}</p>
                        <div className="flex justify-between items-center text-xs text-gray-500">
                          <span>Best odds: {pred.book}</span>
                          <span>AI Recommendation</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Fantasy Tab */}
        {activeTab === 'fantasy' && (
          <div className="space-y-6">
            <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
              <div className="flex items-center">
                <Users className="w-5 h-5 text-purple-600 mr-2" />
                <p className="text-purple-800 text-sm">
                  <strong>Fantasy Football:</strong> AI-powered projections and start/sit advice for weekly lineup optimization.
                </p>
              </div>
            </div>

            {/* Position Filter Buttons */}
            <div className="flex flex-wrap gap-2 mb-6">
              {['All', 'QB', 'RB', 'WR', 'TE', 'K'].map((position) => (
                <button
                  key={position}
                  className="px-3 py-1 text-sm font-medium rounded-full bg-gray-100 text-gray-700 hover:bg-purple-100 hover:text-purple-700 transition-colors"
                >
                  {position}
                </button>
              ))}
            </div>

            {/* Fantasy Projections */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200">
              <div className="px-6 py-4 border-b border-gray-200">
                <h3 className="text-lg font-semibold text-gray-900">Weekly Projections</h3>
                <p className="text-sm text-gray-500">Current Week • {fantasyProjections.length} Players</p>
              </div>

              {fantasyProjections.length === 0 ? (
                <div className="p-8 text-center">
                  <p className="text-gray-500">Loading fantasy projections...</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Player</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Position</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Team</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Projection</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Range</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {fantasyProjections.slice(0, 20).map((player, idx) => (
                        <tr key={idx} className="hover:bg-gray-50">
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div>
                              <div className="text-sm font-medium text-gray-900">{player.player_name}</div>
                              <div className="text-sm text-gray-500">vs {player.opponent}</div>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                              player.position === 'QB' ? 'bg-red-100 text-red-800' :
                              player.position === 'RB' ? 'bg-green-100 text-green-800' :
                              player.position === 'WR' ? 'bg-blue-100 text-blue-800' :
                              player.position === 'TE' ? 'bg-yellow-100 text-yellow-800' :
                              'bg-gray-100 text-gray-800'
                            }`}>
                              {player.position}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{player.team}</td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="text-sm font-semibold text-gray-900">{player.projected_points} pts</div>
                            <div className="text-xs text-gray-500">{player.snap_percentage}% snaps</div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            {player.floor} - {player.ceiling}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                              player.injury_status === 'Healthy' ? 'bg-green-100 text-green-800' :
                              player.injury_status === 'Questionable' ? 'bg-yellow-100 text-yellow-800' :
                              'bg-red-100 text-red-800'
                            }`}>
                              {player.injury_status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Performance Tab */}
        {activeTab === 'performance' && <PerformanceDashboard />}

        {/* Chat Tab */}
        {activeTab === 'chat' && (
          <div className="space-y-6">
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <div className="flex items-center">
                <MessageCircle className="w-5 h-5 text-green-600 mr-2" />
                <p className="text-green-800 text-sm">
                  <strong>AI Assistant:</strong> Get personalized betting advice, fantasy recommendations, and real-time analysis.
                </p>
              </div>
            </div>

            {/* Chat Interface */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 h-96 flex flex-col">
              {/* Messages */}
              <div className="flex-1 p-4 overflow-y-auto space-y-4">
                {messages.length === 0 ? (
                  <div className="text-center text-gray-500 mt-8">
                    <MessageCircle className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                    <p>Ask me anything about NFL betting, fantasy football, or game analysis!</p>
                    <p className="text-sm mt-2">Try one of the suggestions below to get started.</p>
                  </div>
                ) : (
                  messages.map((message, idx) => (
                    <div key={idx} className={`flex ${
                      message.role === 'user' ? 'justify-end' : 'justify-start'
                    }`}>
                      <div className={`max-w-xs lg:max-w-md px-4 py-2 rounded-lg ${
                        message.role === 'user' 
                          ? 'bg-blue-500 text-white' 
                          : 'bg-gray-100 text-gray-900'
                      }`}>
                        <p className="text-sm">{message.content}</p>
                        <p className={`text-xs mt-1 ${
                          message.role === 'user' ? 'text-blue-100' : 'text-gray-500'
                        }`}>
                          {new Date(message.timestamp).toLocaleTimeString()}
                        </p>
                      </div>
                    </div>
                  ))
                )}
                
                {chatLoading && (
                  <div className="flex justify-start">
                    <div className="bg-gray-100 text-gray-900 max-w-xs lg:max-w-md px-4 py-2 rounded-lg">
                      <div className="flex items-center space-x-2">
                        <div className="animate-bounce w-2 h-2 bg-gray-500 rounded-full"></div>
                        <div className="animate-bounce w-2 h-2 bg-gray-500 rounded-full" style={{animationDelay: '0.1s'}}></div>
                        <div className="animate-bounce w-2 h-2 bg-gray-500 rounded-full" style={{animationDelay: '0.2s'}}></div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
              
              {/* Input */}
              <div className="border-t p-4">
                <div className="flex space-x-2">
                  <input
                    type="text"
                    value={currentMessage}
                    onChange={(e) => setCurrentMessage(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
                    placeholder="Ask about odds, fantasy advice, or game analysis..."
                    className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    disabled={chatLoading}
                  />
                  <button
                    onClick={() => sendMessage()}
                    disabled={chatLoading || !currentMessage.trim()}
                    className="bg-blue-500 text-white p-2 rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>

            {/* Quick Suggestions */}
            {suggestions.length > 0 && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
                <h3 className="text-sm font-medium text-gray-900 mb-3">Quick Questions</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {suggestions.map((suggestion, idx) => (
                    <button
                      key={idx}
                      onClick={() => sendMessage(suggestion.text)}
                      className="text-left p-3 text-sm bg-gray-50 hover:bg-blue-50 rounded-lg border border-gray-200 hover:border-blue-300 transition-colors"
                      disabled={chatLoading}
                    >
                      <span className="text-gray-700">{suggestion.text}</span>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ml-2 ${
                        suggestion.category === 'betting' ? 'bg-blue-100 text-blue-800' :
                        suggestion.category === 'fantasy' ? 'bg-purple-100 text-purple-800' :
                        'bg-gray-100 text-gray-800'
                      }`}>
                        {suggestion.category}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Games Tab */}
        {activeTab === 'games' && (
          <div className="space-y-4">
            <h2 className="text-xl font-semibold text-gray-900">Current NFL Games</h2>
            {games.length === 0 ? (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-8 text-center">
                <p className="text-gray-500">No games found. Check back during NFL season!</p>
              </div>
            ) : (
              <div className="grid gap-4">
                {games.map((game, idx) => (
                  <div key={idx} className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                    <div className="flex justify-between items-center">
                      <div>
                        <h3 className="text-lg font-semibold text-gray-900">
                          {game.away_team_full} @ {game.home_team_full}
                        </h3>
                        <p className="text-sm text-gray-500">
                          {game.venue} • Week {game.week}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-medium text-gray-900">
                          {game.date && formatLocalDateTime(game.date)}
                        </p>
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          game.status === 'STATUS_SCHEDULED' ? 'bg-blue-100 text-blue-800' :
                          game.status === 'STATUS_IN_PROGRESS' ? 'bg-green-100 text-green-800' :
                          'bg-gray-100 text-gray-800'
                        }`}>
                          {formatGameStatus(game.status || 'TBD')}
                        </span>
                      </div>
                    </div>
                    
                    {/* Place Bet Button */}
                    {isAuthenticated && (game.status === 'STATUS_SCHEDULED' || game.status?.toLowerCase() === 'upcoming' || game.status === 'SCHEDULED') && (
                      <button
                        onClick={() => handlePlaceBet(game)}
                        className="mt-3 w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 font-medium transition-colors"
                      >
                        Place Bet
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Odds Tab */}
        {activeTab === 'odds' && (
          <div className="space-y-4">
            <h2 className="text-xl font-semibold text-gray-900">Live Betting Odds</h2>
            {odds.length === 0 ? (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-8 text-center">
                <p className="text-gray-500">No live odds available. Check your Odds API key!</p>
              </div>
            ) : (
              <div className="grid gap-4">
                {odds.map((game, idx) => (
                  <div key={idx} className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                    <div className="mb-4">
                      <h3 className="text-lg font-semibold text-gray-900">
                        {game.away_team} @ {game.home_team}
                      </h3>
                      <p className="text-sm text-gray-500">
                        {game.commence_time && formatLocalDateTime(game.commence_time)}
                      </p>
                    </div>
                    
                    <div className="border-t pt-4 mt-4">
                      <h4 className="font-medium text-gray-900 mb-2">Betting Lines</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                        {/* Moneyline */}
                        {game.moneyline && Object.keys(game.moneyline).length > 0 && (
                          <div>
                            <p className="text-gray-600 font-medium mb-1">Moneyline</p>
                            <div className="space-y-1">
                              {game.moneyline.home && (
                                <div className="flex justify-between">
                                  <span>{game.home_team}</span>
                                  <span className="font-mono">{formatOddsDisplay(game.moneyline.home)}</span>
                                </div>
                              )}
                              {game.moneyline.away && (
                                <div className="flex justify-between">
                                  <span>{game.away_team}</span>
                                  <span className="font-mono">{formatOddsDisplay(game.moneyline.away)}</span>
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                        
                        {/* Spread */}
                        {game.spread && Object.keys(game.spread).length > 0 && (
                          <div>
                            <p className="text-gray-600 font-medium mb-1">Spread</p>
                            <div className="space-y-1">
                              {game.spread.home && (
                                <div className="flex justify-between">
                                  <span>{game.home_team} {game.spread.home.point > 0 ? '+' : ''}{formatSpread(game.spread.home.point)}</span>
                                  <span className="font-mono">{formatOddsDisplay(game.spread.home.price)}</span>
                                </div>
                              )}
                              {game.spread.away && (
                                <div className="flex justify-between">
                                  <span>{game.away_team} {game.spread.away.point > 0 ? '+' : ''}{formatSpread(game.spread.away.point)}</span>
                                  <span className="font-mono">{formatOddsDisplay(game.spread.away.price)}</span>
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                        
                        {/* Total */}
                        {game.total && Object.keys(game.total).length > 0 && (
                          <div>
                            <p className="text-gray-600 font-medium mb-1">Total</p>
                            <div className="space-y-1">
                              {Object.entries(game.total).map(([type, data]: [string, any]) => (
                                <div key={type} className="flex justify-between">
                                  <span>{type} {formatTotal(data.point)}</span>
                                  <span className="font-mono">{formatOddsDisplay(data.price)}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                        
                        {/* Show message if no odds available */}
                        {(!game.moneyline || Object.keys(game.moneyline).length === 0) &&
                         (!game.spread || Object.keys(game.spread).length === 0) &&
                         (!game.total || Object.keys(game.total).length === 0) && (
                          <div className="col-span-3">
                            <p className="text-gray-500 text-center">No odds available for this game</p>
                          </div>
                        )}
                      </div>
                    </div>
                    
                    {/* Place Bet Button */}
                    {isAuthenticated && (
                      <button
                        onClick={() => handlePlaceBet(game)}
                        className="mt-4 w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 font-medium transition-colors"
                      >
                        Place Bet
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Personalized Tab */}
        {activeTab === 'personalized' && isAuthenticated && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold text-gray-900">My Personalized Picks</h2>
              <div className="flex items-center text-blue-600">
                <Crown className="w-5 h-5 mr-2" />
                <span className="text-sm font-medium">
                  {user?.subscription_tier === 'free' ? 'Free Tier' : `${user?.subscription_tier} Member`}
                </span>
              </div>
            </div>

            {user?.subscription_tier === 'free' && (
              <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg p-6 border border-blue-200">
                <div className="flex items-start">
                  <Crown className="w-6 h-6 text-blue-600 mt-1 mr-3" />
                  <div>
                    <h3 className="text-lg font-semibold text-blue-900 mb-2">
                      Upgrade to Pro for Personalized Picks
                    </h3>
                    <p className="text-blue-700 mb-4">
                      Get AI-powered predictions based on your favorite teams, betting history, and risk preferences.
                    </p>
                    <button 
                      onClick={() => router.push('/upgrade')}
                      className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 font-medium"
                    >
                      Upgrade to Pro
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Favorite Teams Section */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Your Favorite Teams</h3>
              {user?.favorite_teams ? (
                <div className="flex flex-wrap gap-2">
                  {JSON.parse(user.favorite_teams).map((team: string) => (
                    <span key={team} className="bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm font-medium">
                      {team}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-gray-500">No favorite teams set. Update your preferences to see personalized picks.</p>
              )}
            </div>

            {/* Personalized Games */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Games Featuring Your Teams</h3>
              {user?.favorite_teams && games.length > 0 ? (
                <div className="space-y-4">
                  {games
                    .filter(game => {
                      const favoriteTeams = JSON.parse(user.favorite_teams || '[]');
                      return favoriteTeams.includes(game.home_team) || favoriteTeams.includes(game.away_team);
                    })
                    .map((game, idx) => (
                      <div key={idx} className="border border-gray-200 rounded-lg p-4">
                        <div className="flex items-center justify-between mb-2">
                          <h4 className="font-semibold text-gray-900">
                            {game.away_team_full} @ {game.home_team_full}
                          </h4>
                          <span className="text-xs text-gray-500">{formatGameStatus(game.status || 'TBD')}</span>
                        </div>
                        <div className="text-sm text-gray-600">
                          <p>{game.venue}</p>
                          <p>{game.date && formatLocalDateTime(game.date)}</p>
                        </div>
                        {user?.subscription_tier !== 'free' && (
                          <div className="mt-3 p-3 bg-green-50 rounded border-l-4 border-green-400">
                            <p className="text-sm text-green-800 font-medium">
                              🎯 AI Recommendation: Strong value on {game.home_team} spread based on your betting history
                            </p>
                          </div>
                        )}
                        
                        {/* Place Bet Button */}
                        {(game.status === 'STATUS_SCHEDULED' || game.status?.toLowerCase() === 'upcoming' || game.status === 'SCHEDULED') && (
                          <button
                            onClick={() => handlePlaceBet(game)}
                            className="mt-3 w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 font-medium transition-colors"
                          >
                            Place Bet
                          </button>
                        )}
                      </div>
                    ))}
                  {games.filter(game => {
                    const favoriteTeams = JSON.parse(user.favorite_teams || '[]');
                    return favoriteTeams.includes(game.home_team) || favoriteTeams.includes(game.away_team);
                  }).length === 0 && (
                    <p className="text-gray-500">None of your favorite teams are playing today.</p>
                  )}
                </div>
              ) : (
                <p className="text-gray-500">Set your favorite teams to see personalized game recommendations.</p>
              )}
            </div>

            {/* User Performance */}
            {user?.subscription_tier !== 'free' && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Your Betting Performance</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="text-center p-4 bg-green-50 rounded-lg">
                    <div className="text-2xl font-bold text-green-600">78.5%</div>
                    <div className="text-sm text-green-800">Win Rate</div>
                  </div>
                  <div className="text-center p-4 bg-blue-50 rounded-lg">
                    <div className="text-2xl font-bold text-blue-600">25</div>
                    <div className="text-sm text-blue-800">Total Bets</div>
                  </div>
                  <div className="text-center p-4 bg-purple-50 rounded-lg">
                    <div className="text-2xl font-bold text-purple-600">+$125.50</div>
                    <div className="text-sm text-purple-800">Profit/Loss</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-200 mt-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <p className="text-sm text-gray-500 text-center">
            For entertainment purposes only. Please bet responsibly. 
            Data provided by ESPN and The Odds API.
          </p>
        </div>
      </footer>

      {/* Bet Placement Modal */}
      <BetModal
        isOpen={showBetModal}
        onClose={() => {
          setShowBetModal(false);
          setSelectedGame(null);
        }}
        game={selectedGame}
      />
    </div>
  );
}