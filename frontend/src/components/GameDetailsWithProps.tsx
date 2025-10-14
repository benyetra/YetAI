'use client';

import React, { useState } from 'react';
import { Trophy, TrendingUp, Users } from 'lucide-react';
import PlayerPropsCard from './PlayerPropsCard';
import PlayerPropBetModal from './PlayerPropBetModal';
import BetModal from './BetModal';

interface Game {
  id: string;
  sport: string;
  sport_key: string;
  home_team: string;
  away_team: string;
  commence_time: string;
  home_odds?: number;
  away_odds?: number;
  spread?: number;
  total?: number;
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

interface GameDetailsWithPropsProps {
  game: Game;
}

export default function GameDetailsWithProps({ game }: GameDetailsWithPropsProps) {
  const [activeTab, setActiveTab] = useState<'game' | 'props'>('game');
  const [showGameBetModal, setShowGameBetModal] = useState(false);
  const [showPropBetModal, setShowPropBetModal] = useState(false);
  const [selectedProp, setSelectedProp] = useState<PropBet | null>(null);

  const handlePropSelection = (propBet: PropBet) => {
    setSelectedProp(propBet);
    setShowPropBetModal(true);
  };

  const handleGameBet = () => {
    setShowGameBetModal(true);
  };

  // Check if sport supports player props
  const supportsPlayerProps = [
    'americanfootball_nfl',
    'basketball_nba',
    'icehockey_nhl',
    'baseball_mlb'
  ].includes(game.sport_key);

  return (
    <div className="max-w-6xl mx-auto p-4 space-y-6">
      {/* Game Header */}
      <div className="bg-gradient-to-r from-purple-900 to-blue-900 rounded-2xl p-6 text-white">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
            <Trophy className="w-6 h-6" />
            <span className="text-sm font-medium opacity-80">
              {game.sport.toUpperCase()}
            </span>
          </div>
          <span className="text-sm opacity-80">
            {new Date(game.commence_time).toLocaleDateString('en-US', {
              weekday: 'short',
              month: 'short',
              day: 'numeric',
              hour: 'numeric',
              minute: '2-digit'
            })}
          </span>
        </div>

        <div className="text-center">
          <h1 className="text-3xl font-bold mb-2">
            {game.away_team} @ {game.home_team}
          </h1>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-gray-800 rounded-lg p-1 flex gap-2">
        <button
          onClick={() => setActiveTab('game')}
          className={`flex-1 py-3 px-4 rounded-lg font-medium transition-all ${
            activeTab === 'game'
              ? 'bg-gradient-to-r from-purple-600 to-blue-600 text-white shadow-lg'
              : 'text-gray-400 hover:text-white hover:bg-gray-700'
          }`}
        >
          <div className="flex items-center justify-center space-x-2">
            <TrendingUp className="w-4 h-4" />
            <span>Game Lines</span>
          </div>
        </button>
        {supportsPlayerProps && (
          <button
            onClick={() => setActiveTab('props')}
            className={`flex-1 py-3 px-4 rounded-lg font-medium transition-all ${
              activeTab === 'props'
                ? 'bg-gradient-to-r from-purple-600 to-blue-600 text-white shadow-lg'
                : 'text-gray-400 hover:text-white hover:bg-gray-700'
            }`}
          >
            <div className="flex items-center justify-center space-x-2">
              <Users className="w-4 h-4" />
              <span>Player Props</span>
            </div>
          </button>
        )}
      </div>

      {/* Content */}
      {activeTab === 'game' && (
        <div className="bg-gray-800 rounded-lg p-6 space-y-4">
          <h2 className="text-xl font-bold text-white mb-4">Betting Lines</h2>

          {/* Moneyline */}
          {game.home_odds && game.away_odds && (
            <div className="bg-gray-700/30 rounded-lg p-4 border border-gray-700">
              <h3 className="text-sm font-medium text-gray-400 mb-3">Moneyline</h3>
              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={handleGameBet}
                  className="bg-gray-600/50 hover:bg-gray-600 p-4 rounded-lg transition-colors"
                >
                  <div className="text-white font-medium">{game.away_team}</div>
                  <div className="text-xl font-bold text-white mt-1">
                    {game.away_odds > 0 ? `+${game.away_odds}` : game.away_odds}
                  </div>
                </button>
                <button
                  onClick={handleGameBet}
                  className="bg-gray-600/50 hover:bg-gray-600 p-4 rounded-lg transition-colors"
                >
                  <div className="text-white font-medium">{game.home_team}</div>
                  <div className="text-xl font-bold text-white mt-1">
                    {game.home_odds > 0 ? `+${game.home_odds}` : game.home_odds}
                  </div>
                </button>
              </div>
            </div>
          )}

          {/* Spread */}
          {game.spread && (
            <div className="bg-gray-700/30 rounded-lg p-4 border border-gray-700">
              <h3 className="text-sm font-medium text-gray-400 mb-3">Spread</h3>
              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={handleGameBet}
                  className="bg-gray-600/50 hover:bg-gray-600 p-4 rounded-lg transition-colors"
                >
                  <div className="text-white font-medium">{game.away_team}</div>
                  <div className="text-xl font-bold text-white mt-1">
                    {game.spread > 0 ? `+${game.spread}` : game.spread}
                  </div>
                </button>
                <button
                  onClick={handleGameBet}
                  className="bg-gray-600/50 hover:bg-gray-600 p-4 rounded-lg transition-colors"
                >
                  <div className="text-white font-medium">{game.home_team}</div>
                  <div className="text-xl font-bold text-white mt-1">
                    {-game.spread > 0 ? `+${-game.spread}` : -game.spread}
                  </div>
                </button>
              </div>
            </div>
          )}

          {/* Total */}
          {game.total && (
            <div className="bg-gray-700/30 rounded-lg p-4 border border-gray-700">
              <h3 className="text-sm font-medium text-gray-400 mb-3">Total</h3>
              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={handleGameBet}
                  className="bg-gray-600/50 hover:bg-gray-600 p-4 rounded-lg transition-colors"
                >
                  <div className="text-white font-medium">Over</div>
                  <div className="text-xl font-bold text-white mt-1">{game.total}</div>
                </button>
                <button
                  onClick={handleGameBet}
                  className="bg-gray-600/50 hover:bg-gray-600 p-4 rounded-lg transition-colors"
                >
                  <div className="text-white font-medium">Under</div>
                  <div className="text-xl font-bold text-white mt-1">{game.total}</div>
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'props' && supportsPlayerProps && (
        <PlayerPropsCard
          sportKey={game.sport_key}
          eventId={game.id}
          gameInfo={{
            home_team: game.home_team,
            away_team: game.away_team,
            commence_time: game.commence_time
          }}
          onPlaceBet={handlePropSelection}
        />
      )}

      {/* Modals */}
      <BetModal
        isOpen={showGameBetModal}
        onClose={() => setShowGameBetModal(false)}
        game={game}
      />

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
