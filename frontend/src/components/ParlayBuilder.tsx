'use client';

import React, { useState, useEffect } from 'react';
import { X, Plus, Calculator, Trash2, AlertCircle } from 'lucide-react';

interface ParlayLeg {
  gameId: string;
  betType: string;
  selection: string;
  odds: number;
  gameInfo?: string;
  teamNames?: string[];
  // Game details for backend
  home_team?: string;
  away_team?: string;
  sport?: string;
  commence_time?: string;
}

interface ParlayBuilderProps {
  isOpen: boolean;
  onClose: () => void;
  onParlayCreated?: () => void;
  availableGames?: any[];
}

export default function ParlayBuilder({ isOpen, onClose, onParlayCreated, availableGames = [] }: ParlayBuilderProps) {
  const [legs, setLegs] = useState<ParlayLeg[]>([]);
  const [amount, setAmount] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string>('');
  const [gameFilter, setGameFilter] = useState<string>('');
  const [sportFilter, setSportFilter] = useState<string>('all');

  // Sample games data (this would come from odds API)
  const sampleGames = [
    {
      id: 'nfl-1',
      sport: 'NFL',
      teams: ['Dallas Cowboys', 'Philadelphia Eagles'], // [away, home]
      gameTime: '2025-09-04 20:20:00',
      odds: {
        moneyline: [270, -280], // [away, home]
        spread: ['+7 (-110)', '-7 (-110)'], // [away, home]
        total: ['O 46.5 (-110)', 'U 46.5 (-110)']
      },
      raw_moneyline: [
        { name: 'Dallas Cowboys', price: 270 },
        { name: 'Philadelphia Eagles', price: -280 }
      ],
      raw_spread: [
        { name: 'Dallas Cowboys', price: -110, point: 7 },
        { name: 'Philadelphia Eagles', price: -110, point: -7 }
      ],
      raw_total: [
        { name: 'Over', price: -110, point: 46.5 },
        { name: 'Under', price: -110, point: 46.5 }
      ]
    },
    {
      id: 'nfl-2',
      sport: 'NFL',
      teams: ['Kansas City Chiefs', 'Los Angeles Chargers'], // [away, home]
      gameTime: '2025-09-05 20:00:00',
      odds: {
        moneyline: [-160, 150], // [away, home]
        spread: ['-3 (-120)', '+3 (-102)'], // [away, home]
        total: ['O 45.5 (-105)', 'U 45.5 (-115)']
      },
      raw_moneyline: [
        { name: 'Kansas City Chiefs', price: -160 },
        { name: 'Los Angeles Chargers', price: 150 }
      ],
      raw_spread: [
        { name: 'Kansas City Chiefs', price: -120, point: -3 },
        { name: 'Los Angeles Chargers', price: -102, point: 3 }
      ],
      raw_total: [
        { name: 'Over', price: -105, point: 45.5 },
        { name: 'Under', price: -115, point: 45.5 }
      ]
    }
  ];

  const games = availableGames.length > 0 ? availableGames : sampleGames;

  // Helper function to check if a bet selection should be disabled
  const isBetDisabled = (gameId: string, betType: string, selection: string) => {
    // Check for exact duplicate
    const isDuplicate = legs.some(leg => 
      leg.gameId === gameId && 
      leg.betType === betType && 
      leg.selection === selection
    );

    if (isDuplicate) return true;

    // Check for conflicting bets on the same game
    const game = games.find(g => g.id === gameId);
    const teams = game?.teams || [];
    const existingGameLegs = legs.filter(leg => leg.gameId === gameId);
    
    for (const existingGameLeg of existingGameLegs) {
      // Case 1: Same bet type on same game (mutually exclusive)
      if (betType === existingGameLeg.betType) {
        return true; // Disable any other selection of same bet type
      }
      
      // Case 2: Different bet types but same team (conflicting)
      if ((betType === 'moneyline' || betType === 'spread') && 
          (existingGameLeg.betType === 'moneyline' || existingGameLeg.betType === 'spread')) {
        
        // Extract team from current selection
        const currentTeam = teams.find(team => selection.includes(team));
        // Extract team from existing selection
        const existingTeam = teams.find(team => existingGameLeg.selection.includes(team));
        
        if (currentTeam && existingTeam && currentTeam === existingTeam) {
          return true; // Disable if same team already has a bet
        }
      }
    }

    return false;
  };

  // Filter games based on search and sport filters
  const filteredGames = games.filter(game => {
    if (sportFilter !== 'all' && game.sport !== sportFilter) {
      return false;
    }
    
    if (gameFilter) {
      const searchTerm = gameFilter.toLowerCase();
      return game.teams.some(team => team.toLowerCase().includes(searchTerm)) ||
             game.sport.toLowerCase().includes(searchTerm);
    }
    
    return true;
  });

  const addLeg = (gameId: string, betType: string, selection: string, odds: number, gameInfo: string) => {
    if (legs.length >= 10) {
      setError('Maximum 10 legs allowed in a parlay');
      return;
    }

    // Check for exact duplicate
    const isDuplicate = legs.some(leg => 
      leg.gameId === gameId && 
      leg.betType === betType && 
      leg.selection === selection
    );

    if (isDuplicate) {
      setError('This selection has already been added to your parlay');
      return;
    }

    // Check for conflicting bets on the same game
    const existingGameLegs = legs.filter(leg => leg.gameId === gameId);
    
    for (const existingGameLeg of existingGameLegs) {
      const game = games.find(g => g.id === gameId);
      const teams = game?.teams || [];
      
      // Case 1: Same bet type on same game (mutually exclusive)
      if (betType === existingGameLeg.betType) {
        setError(`Cannot select multiple ${betType} bets for the same game`);
        return;
      }
      
      // Case 2: Different bet types but same team (conflicting)
      if ((betType === 'moneyline' || betType === 'spread') && 
          (existingGameLeg.betType === 'moneyline' || existingGameLeg.betType === 'spread')) {
        
        // Extract team from current selection
        const currentTeam = teams.find(team => selection.includes(team));
        // Extract team from existing selection
        const existingTeam = teams.find(team => existingGameLeg.selection.includes(team));
        
        if (currentTeam && existingTeam && currentTeam === existingTeam) {
          // Remove the lower odds bet and replace with higher odds
          if (Math.abs(odds) < Math.abs(existingGameLeg.odds)) {
            // New bet has better odds, remove existing and add new
            setLegs(prevLegs => prevLegs.filter(leg => leg !== existingGameLeg));
            setError(`Replaced ${existingGameLeg.betType} with ${betType} for better odds`);
          } else {
            setError(`${existingGameLeg.betType} already selected with better odds for this team`);
            return;
          }
        }
      }
    }

    const game = games.find(g => g.id === gameId);
    const newLeg: ParlayLeg = {
      gameId,
      betType,
      selection,
      odds,
      gameInfo,
      teamNames: game?.teams || [],
      // Include team details for backend
      home_team: game?.teams?.[1], // Home team is typically second in the array
      away_team: game?.teams?.[0], // Away team is typically first  
      sport: game?.sport,
      commence_time: game?.gameTime
    };

    setLegs(prevLegs => [...prevLegs, newLeg]);
    // Clear error after 3 seconds if it was a replacement message
    if (error.includes('Replaced')) {
      setTimeout(() => setError(''), 3000);
    } else {
      setError('');
    }
  };

  const removeLeg = (index: number) => {
    setLegs(legs.filter((_, i) => i !== index));
  };

  const calculateParlayOdds = () => {
    if (legs.length === 0) return 0;
    
    let totalOdds = 1.0;
    for (const leg of legs) {
      const decimalOdds = leg.odds > 0 ? (leg.odds / 100) + 1 : (100 / Math.abs(leg.odds)) + 1;
      totalOdds *= decimalOdds;
    }
    
    // Convert back to American odds and round to whole number
    if (totalOdds >= 2) {
      return Math.round((totalOdds - 1) * 100);
    } else {
      return Math.round(-100 / (totalOdds - 1));
    }
  };

  const calculatePotentialWin = () => {
    if (!amount || legs.length === 0) return 0;
    
    const betAmount = parseFloat(amount);
    const parlayOdds = calculateParlayOdds();
    
    if (parlayOdds > 0) {
      return betAmount * (parlayOdds / 100);
    } else {
      return betAmount * (100 / Math.abs(parlayOdds));
    }
  };

  const handleSubmit = async () => {
    if (legs.length < 2) {
      setError('Parlay must have at least 2 legs');
      return;
    }

    if (!amount || parseFloat(amount) <= 0) {
      setError('Please enter a valid bet amount');
      return;
    }

    setIsSubmitting(true);
    setError('');

    try {
      const parlayData = {
        legs: legs.map(leg => ({
          game_id: leg.gameId,
          bet_type: leg.betType.toLowerCase(),
          selection: leg.selection,
          odds: leg.odds,
          home_team: leg.home_team,
          away_team: leg.away_team,
          sport: leg.sport,
          commence_time: leg.commence_time
        })),
        amount: parseFloat(amount)
      };

      const response = await fetch('http://localhost:8000/api/bets/parlay', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
        },
        body: JSON.stringify(parlayData)
      });

      const result = await response.json();

      if (result.status === 'success') {
        // Reset form
        setLegs([]);
        setAmount('');
        // Trigger refresh and close
        if (onParlayCreated) {
          onParlayCreated();
        }
        onClose();
      } else {
        setError(result.detail || 'Failed to place parlay');
      }
    } catch (error) {
      setError('Failed to place parlay. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg max-w-4xl w-full max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-gray-200 p-6 flex items-center justify-between">
          <h2 className="text-2xl font-bold text-gray-900">Build Parlay</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        <div className="p-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Available Games */}
            <div>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">Available Games</h3>
                <span className="text-sm text-gray-500">{filteredGames.length} games</span>
              </div>
              
              {/* Search and Filter Controls */}
              <div className="space-y-3 mb-4">
                <input
                  type="text"
                  placeholder="Search teams, games..."
                  value={gameFilter}
                  onChange={(e) => setGameFilter(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <select
                  value={sportFilter}
                  onChange={(e) => setSportFilter(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                >
                  <option value="all">All Sports</option>
                  <option value="NFL">NFL</option>
                  <option value="NBA">NBA</option>
                  <option value="MLB">MLB</option>
                  <option value="NHL">NHL</option>
                </select>
              </div>

              <div className="space-y-4 max-h-96 overflow-y-auto">
                {filteredGames.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    <div className="text-4xl mb-2">🔍</div>
                    <p className="font-medium">No games found</p>
                    <p className="text-sm">Try adjusting your search or filters</p>
                  </div>
                ) : (
                  filteredGames.map((game) => (
                  <div key={game.id} className="border border-gray-200 rounded-lg p-4">
                    <div className="flex justify-between items-center mb-3">
                      <div>
                        <h4 className="font-medium">{game.teams[0]} vs {game.teams[1]}</h4>
                        <p className="text-sm text-gray-500">{game.sport} • {new Date(game.gameTime).toLocaleString()}</p>
                      </div>
                    </div>

                    <div className="space-y-2">
                      {/* Moneyline */}
                      <div>
                        <h5 className="text-sm font-medium text-gray-700 mb-1">Moneyline</h5>
                        <div className="flex gap-2">
                          <button
                            onClick={() => {
                              const awayOdds = Array.isArray(game.odds.moneyline) ? game.odds.moneyline[0] : 
                                (game.raw_moneyline?.find(o => o.name === game.teams[0])?.price || 0);
                              addLeg(
                                game.id,
                                'moneyline',
                                game.teams[0],
                                awayOdds,
                                `${game.teams[0]} vs ${game.teams[1]} - Moneyline`
                              );
                            }}
                            disabled={isBetDisabled(game.id, 'moneyline', game.teams[0])}
                            className={`flex-1 px-3 py-2 text-sm border rounded transition-colors ${
                              isBetDisabled(game.id, 'moneyline', game.teams[0])
                                ? 'border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed'
                                : 'border-gray-300 hover:bg-gray-50'
                            }`}
                          >
                            {(() => {
                              const awayOdds = Array.isArray(game.odds.moneyline) ? game.odds.moneyline[0] : 
                                (game.raw_moneyline?.find(o => o.name === game.teams[0])?.price || 0);
                              return `${game.teams[0]} ${awayOdds > 0 ? '+' : ''}${awayOdds}`;
                            })()}
                          </button>
                          <button
                            onClick={() => {
                              const homeOdds = Array.isArray(game.odds.moneyline) ? game.odds.moneyline[1] : 
                                (game.raw_moneyline?.find(o => o.name === game.teams[1])?.price || 0);
                              addLeg(
                                game.id,
                                'moneyline',
                                game.teams[1],
                                homeOdds,
                                `${game.teams[0]} vs ${game.teams[1]} - Moneyline`
                              );
                            }}
                            disabled={isBetDisabled(game.id, 'moneyline', game.teams[1])}
                            className={`flex-1 px-3 py-2 text-sm border rounded transition-colors ${
                              isBetDisabled(game.id, 'moneyline', game.teams[1])
                                ? 'border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed'
                                : 'border-gray-300 hover:bg-gray-50'
                            }`}
                          >
                            {(() => {
                              const homeOdds = Array.isArray(game.odds.moneyline) ? game.odds.moneyline[1] : 
                                (game.raw_moneyline?.find(o => o.name === game.teams[1])?.price || 0);
                              return `${game.teams[1]} ${homeOdds > 0 ? '+' : ''}${homeOdds}`;
                            })()}
                          </button>
                        </div>
                      </div>

                      {/* Spread */}
                      <div>
                        <h5 className="text-sm font-medium text-gray-700 mb-1">Spread</h5>
                        <div className="flex gap-2">
                          <button
                            onClick={() => {
                              const awaySpreadData = game.raw_spread?.find(o => o.name === game.teams[0]);
                              const awaySpread = Array.isArray(game.odds.spread) ? game.odds.spread[0] : 
                                `${awaySpreadData?.point >= 0 ? '+' : ''}${awaySpreadData?.point || 0} (${awaySpreadData?.price || -110})`;
                              const awayOdds = awaySpreadData?.price || -110;
                              addLeg(
                                game.id,
                                'spread',
                                `${game.teams[0]} ${awaySpread.split(' ')[0]}`,
                                awayOdds,
                                `${game.teams[0]} vs ${game.teams[1]} - Spread`
                              );
                            }}
                            disabled={isBetDisabled(game.id, 'spread', `${game.teams[0]}`)}
                            className={`flex-1 px-3 py-2 text-sm border rounded transition-colors ${
                              isBetDisabled(game.id, 'spread', `${game.teams[0]}`)
                                ? 'border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed'
                                : 'border-gray-300 hover:bg-gray-50'
                            }`}
                          >
                            {(() => {
                              const awaySpreadData = game.raw_spread?.find(o => o.name === game.teams[0]);
                              const spreadLine = `${awaySpreadData?.point >= 0 ? '+' : ''}${awaySpreadData?.point || 0}`;
                              return `${game.teams[0]} ${spreadLine}`;
                            })()}
                          </button>
                          <button
                            onClick={() => {
                              const homeSpreadData = game.raw_spread?.find(o => o.name === game.teams[1]);
                              const homeSpread = Array.isArray(game.odds.spread) ? game.odds.spread[1] : 
                                `${homeSpreadData?.point >= 0 ? '+' : ''}${homeSpreadData?.point || 0} (${homeSpreadData?.price || -110})`;
                              const homeOdds = homeSpreadData?.price || -110;
                              addLeg(
                                game.id,
                                'spread',
                                `${game.teams[1]} ${homeSpread.split(' ')[0]}`,
                                homeOdds,
                                `${game.teams[0]} vs ${game.teams[1]} - Spread`
                              );
                            }}
                            disabled={isBetDisabled(game.id, 'spread', `${game.teams[1]}`)}
                            className={`flex-1 px-3 py-2 text-sm border rounded transition-colors ${
                              isBetDisabled(game.id, 'spread', `${game.teams[1]}`)
                                ? 'border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed'
                                : 'border-gray-300 hover:bg-gray-50'
                            }`}
                          >
                            {(() => {
                              const homeSpreadData = game.raw_spread?.find(o => o.name === game.teams[1]);
                              const spreadLine = `${homeSpreadData?.point >= 0 ? '+' : ''}${homeSpreadData?.point || 0}`;
                              return `${game.teams[1]} ${spreadLine}`;
                            })()}
                          </button>
                        </div>
                      </div>

                      {/* Total */}
                      <div>
                        <h5 className="text-sm font-medium text-gray-700 mb-1">Total</h5>
                        <div className="flex gap-2">
                          <button
                            onClick={() => {
                              const overData = game.raw_total?.find(o => o.name === 'Over');
                              const overSelection = Array.isArray(game.odds.total) ? game.odds.total[0] : 
                                `O ${overData?.point || 0} (${overData?.price || -110})`;
                              const overOdds = overData?.price || -110;
                              addLeg(
                                game.id,
                                'total',
                                overSelection,
                                overOdds,
                                `${game.teams[0]} vs ${game.teams[1]} - Total`
                              );
                            }}
                            disabled={isBetDisabled(game.id, 'total', 'Over')}
                            className={`flex-1 px-3 py-2 text-sm border rounded transition-colors ${
                              isBetDisabled(game.id, 'total', 'Over')
                                ? 'border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed'
                                : 'border-gray-300 hover:bg-gray-50'
                            }`}
                          >
                            {(() => {
                              const overData = game.raw_total?.find(o => o.name === 'Over');
                              return `O ${overData?.point || 0} (${overData?.price || -110})`;
                            })()}
                          </button>
                          <button
                            onClick={() => {
                              const underData = game.raw_total?.find(o => o.name === 'Under');
                              const underSelection = Array.isArray(game.odds.total) ? game.odds.total[1] : 
                                `U ${underData?.point || 0} (${underData?.price || -115})`;
                              const underOdds = underData?.price || -115;
                              addLeg(
                                game.id,
                                'total',
                                underSelection,
                                underOdds,
                                `${game.teams[0]} vs ${game.teams[1]} - Total`
                              );
                            }}
                            disabled={isBetDisabled(game.id, 'total', 'Under')}
                            className={`flex-1 px-3 py-2 text-sm border rounded transition-colors ${
                              isBetDisabled(game.id, 'total', 'Under')
                                ? 'border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed'
                                : 'border-gray-300 hover:bg-gray-50'
                            }`}
                          >
                            {(() => {
                              const underData = game.raw_total?.find(o => o.name === 'Under');
                              return `U ${underData?.point || 0} (${underData?.price || -115})`;
                            })()}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                  ))
                )}
              </div>
            </div>

            {/* Parlay Ticket */}
            <div>
              <h3 className="text-lg font-semibold mb-4">Parlay Ticket</h3>
              
              {legs.length === 0 ? (
                <div className="border border-gray-200 rounded-lg p-8 text-center text-gray-500">
                  <Calculator className="w-12 h-12 mx-auto mb-2" />
                  <p>Add selections to build your parlay</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Legs */}
                  <div className="space-y-2">
                    {legs.map((leg, index) => (
                      <div key={index} className="flex items-center justify-between p-3 border border-gray-200 rounded-lg">
                        <div className="flex-1">
                          <p className="font-medium text-sm">{leg.selection}</p>
                          <p className="text-xs text-gray-500">{leg.gameInfo}</p>
                          <p className="text-xs text-gray-600">{leg.odds > 0 ? '+' : ''}{leg.odds}</p>
                        </div>
                        <button
                          onClick={() => removeLeg(index)}
                          className="text-red-500 hover:text-red-700"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                  </div>

                  {/* Parlay Details */}
                  <div className="border-t pt-4">
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-sm font-medium">Legs:</span>
                      <span className="text-sm">{legs.length}</span>
                    </div>
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-sm font-medium">Parlay Odds:</span>
                      <span className="text-sm font-mono">
                        {legs.length > 0 ? (
                          calculateParlayOdds() > 0 ? `+${calculateParlayOdds()}` : calculateParlayOdds()
                        ) : '--'}
                      </span>
                    </div>
                    
                    <div className="mb-4">
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Bet Amount
                      </label>
                      <input
                        type="number"
                        value={amount}
                        onChange={(e) => setAmount(e.target.value)}
                        placeholder="$0.00"
                        min="1"
                        max="10000"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      />
                    </div>

                    {amount && legs.length > 0 && (
                      <div className="flex justify-between items-center mb-4 p-3 bg-green-50 rounded-lg">
                        <span className="text-sm font-medium text-green-800">Potential Win:</span>
                        <span className="text-lg font-bold text-green-800">
                          ${calculatePotentialWin().toFixed(2)}
                        </span>
                      </div>
                    )}

                    {error && (
                      <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center">
                        <AlertCircle className="w-4 h-4 text-red-500 mr-2" />
                        <span className="text-red-800 text-sm">{error}</span>
                      </div>
                    )}

                    <button
                      onClick={handleSubmit}
                      disabled={legs.length < 2 || !amount || isSubmitting}
                      className="w-full bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
                      style={{ color: 'white', backgroundColor: '#2563eb' }}
                    >
                      {isSubmitting ? 'Placing Parlay...' : `Place Parlay (${legs.length} legs)`}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}