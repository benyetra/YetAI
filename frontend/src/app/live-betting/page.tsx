'use client';

import React, { useState } from 'react';
import { LiveOdds } from '@/components/LiveOdds';
import BetModal from '@/components/BetModal';
import { oddsUtils } from '@/lib/api';
import { useAuth } from '@/components/Auth';
import { Activity, Target, Crown } from 'lucide-react';

interface Game {
  id: string;
  sport_key: string;
  sport_title: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  bookmakers: Array<{
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
  }>;
}

export default function LiveBettingPage() {
  const { user, isAuthenticated } = useAuth();
  const [showBetModal, setShowBetModal] = useState(false);
  const [selectedGame, setSelectedGame] = useState<any>(null);

  // Handle place bet from live odds
  const handlePlaceBet = (game: Game) => {
    if (!isAuthenticated) {
      alert('Please log in to place bets');
      return;
    }

    // Convert live odds data to simple format for BetModal
    const simpleGame = oddsUtils.toSimpleGame(game);
    setSelectedGame(simpleGame);
    setShowBetModal(true);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div>
              <div className="flex items-center space-x-3">
                <Activity className="w-8 h-8 text-[#A855F7]" />
                <div>
                  <h1 className="text-2xl font-bold text-gray-900">
                    Live Sports Betting
                  </h1>
                  <p className="text-sm text-gray-600">
                    Real-time odds from multiple bookmakers
                  </p>
                </div>
              </div>
            </div>
            
            {isAuthenticated ? (
              <div className="flex items-center space-x-3">
                <div className="text-right">
                  <p className="text-sm font-medium text-gray-900">
                    Welcome, {user?.first_name || user?.email}
                  </p>
                  <p className="text-xs text-gray-600 flex items-center">
                    {user?.subscription_tier !== 'free' && (
                      <Crown className="w-3 h-3 mr-1 text-yellow-500" />
                    )}
                    {user?.subscription_tier === 'free' ? 'Free Tier' : `${user.subscription_tier} Member`}
                  </p>
                </div>
              </div>
            ) : (
              <div className="text-sm text-gray-600">
                <span>Login to place bets</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Auth Notice */}
        {!isAuthenticated && (
          <div className="mb-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div className="flex items-center">
              <Target className="w-5 h-5 text-blue-600 mr-2" />
              <p className="text-blue-800 text-sm">
                <strong>Sign in to place bets:</strong> You can view live odds below, but you'll need to create an account to place bets.
              </p>
            </div>
          </div>
        )}
        
        {/* Free Tier Upsell */}
        {isAuthenticated && user?.subscription_tier === 'free' && (
          <div className="mb-6 bg-gradient-to-r from-purple-50 to-blue-50 border border-purple-200 rounded-lg p-4">
            <div className="flex items-center">
              <Crown className="w-5 h-5 text-purple-600 mr-2" />
              <div>
                <p className="text-purple-800 text-sm">
                  <strong>Upgrade to Pro:</strong> Get advanced analytics, better odds tracking, and personalized betting recommendations.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Live Odds Display with Betting */}
        <LiveOdds 
          showPopular={true}
          autoRefresh={true}
          refreshInterval={300000} // 5 minutes
          maxGames={20}
          onPlaceBet={handlePlaceBet}
        />
        
        {/* Additional Information */}
        <div className="mt-8 bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-bold text-gray-900 mb-4">How It Works</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="text-center">
              <div className="w-12 h-12 bg-[#A855F7] rounded-lg flex items-center justify-center mx-auto mb-3">
                <Activity className="w-6 h-6 text-white" />
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">Live Odds</h3>
              <p className="text-sm text-gray-600">
                Real-time odds from multiple sportsbooks, updated every 5 minutes.
              </p>
            </div>
            
            <div className="text-center">
              <div className="w-12 h-12 bg-[#A855F7] rounded-lg flex items-center justify-center mx-auto mb-3">
                <Target className="w-6 h-6 text-white" />
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">Easy Betting</h3>
              <p className="text-sm text-gray-600">
                Click "Place Bet" on any game to open the betting interface with pre-filled odds.
              </p>
            </div>
            
            <div className="text-center">
              <div className="w-12 h-12 bg-[#A855F7] rounded-lg flex items-center justify-center mx-auto mb-3">
                <Crown className="w-6 h-6 text-white" />
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">AI Insights</h3>
              <p className="text-sm text-gray-600">
                Get AI-powered betting recommendations and analysis with Pro membership.
              </p>
            </div>
          </div>
        </div>

        {/* Responsible Gambling */}
        <div className="mt-6 text-center">
          <p className="text-xs text-gray-500">
            Please bet responsibly. Must be 21+ to place bets. If you need help, call 1-800-GAMBLER.
          </p>
        </div>
      </div>

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