'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import BetModal from '@/components/BetModal';
import { LiveOdds } from '@/components/LiveOdds';
import { SportsSelector } from '@/components/SportsSelector';
import { sportsAPI, oddsUtils } from '@/lib/api';
import { DollarSign, TrendingUp, Clock, Target, Activity, Crown, RefreshCw, AlertCircle } from 'lucide-react';
import { formatSportName } from '@/lib/formatting';

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

export default function BetPage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  const [selectedSport, setSelectedSport] = useState('');
  const [showBetModal, setShowBetModal] = useState(false);
  const [selectedGame, setSelectedGame] = useState<any>(null);
  const [sportsData, setSportsData] = useState<any>(null);
  const [loadingSports, setLoadingSports] = useState(true);

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

  // Load available sports
  useEffect(() => {
    const loadSports = async () => {
      try {
        const data = await sportsAPI.getSports();
        setSportsData(data);
        // Default to first active sport or popular sport
        if (data.sports && data.sports.length > 0) {
          const activeSports = data.sports.filter((s: any) => s.active);
          const defaultSport = activeSports.find((s: any) => s.key === 'americanfootball_nfl') || 
                             activeSports.find((s: any) => s.key === 'basketball_nba') ||
                             activeSports.find((s: any) => s.key === 'baseball_mlb') ||
                             activeSports[0];
          if (defaultSport) {
            setSelectedSport(defaultSport.key);
          }
        }
      } catch (error) {
        console.error('Failed to load sports:', error);
      } finally {
        setLoadingSports(false);
      }
    };
    
    if (isAuthenticated) {
      loadSports();
    }
  }, [isAuthenticated]);

  // Handle place bet
  const handlePlaceBet = (game: Game) => {
    // Convert live odds data to simple format for BetModal
    const simpleGame = oddsUtils.toSimpleGame(game);
    setSelectedGame(simpleGame);
    setShowBetModal(true);
  };


  if (loading || loadingSports) {
    return (
      <Layout>
        <div className="min-h-screen flex items-center justify-center">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#A855F7] mx-auto"></div>
            <p className="mt-4 text-gray-600">Loading betting opportunities...</p>
          </div>
        </div>
      </Layout>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Place Bets</h1>
            <p className="text-gray-600 mt-1">Live betting opportunities with real-time odds</p>
          </div>
          
          {/* Sport Selector */}
          <div className="flex items-center space-x-3">
            {!loadingSports && sportsData && (
              <SportsSelector
                selectedSport={selectedSport}
                onSportChange={(sportKey: string, sportTitle: string) => setSelectedSport(sportKey)}
                showSearch={false}
                showCategories={false}
                className="min-w-[200px]"
              />
            )}
          </div>
        </div>

        {/* Premium Feature Notice for Free Users */}
        {user?.subscription_tier === 'free' && (
          <div className="bg-gradient-to-r from-purple-50 to-blue-50 border border-purple-200 rounded-lg p-4">
            <div className="flex items-center">
              <Crown className="w-5 h-5 text-purple-600 mr-2" />
              <div className="flex-1">
                <p className="text-purple-800 text-sm font-medium mb-1">
                  Enhanced Betting Experience
                </p>
                <p className="text-purple-700 text-sm">
                  Upgrade to Pro for AI betting recommendations, advanced analytics, and premium odds tracking.
                </p>
              </div>
              <button 
                onClick={() => router.push('/upgrade')}
                className="ml-4 bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                Upgrade
              </button>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Betting Area */}
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200">
                <div className="flex items-center justify-between">
                  <h2 className="text-xl font-semibold text-gray-900 flex items-center">
                    <Activity className="w-5 h-5 mr-2 text-[#A855F7]" />
                    {selectedSport ? 
                      `${formatSportName(selectedSport)} Betting` : 
                      'Live Betting'
                    }
                  </h2>
                  {selectedSport && (
                    <span className="text-sm text-gray-600 bg-gray-100 px-3 py-1 rounded-full">
                      Live Odds
                    </span>
                  )}
                </div>
              </div>

              {selectedSport ? (
                <div className="p-0">
                  <LiveOdds
                    sportKey={selectedSport}
                    autoRefresh={true}
                    refreshInterval={300000}
                    maxGames={20}
                    onPlaceBet={handlePlaceBet}
                  />
                </div>
              ) : (
                <div className="p-6">
                  <div className="text-center py-12 text-gray-500">
                    <Target className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                    <p className="text-lg font-medium mb-2">Select a Sport to Start Betting</p>
                    <p className="text-sm">Choose a sport from the dropdown above to view live betting opportunities</p>
                  </div>
                </div>
              )}
            </div>

            {/* Popular Sports Quick Access */}
            {!selectedSport && (
              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Popular Sports</h3>
                <LiveOdds
                  showPopular={true}
                  autoRefresh={true}
                  refreshInterval={300000}
                  maxGames={6}
                  onPlaceBet={handlePlaceBet}
                />
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* Bet Slip */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <h3 className="text-lg font-semibold mb-4 flex items-center">
                <DollarSign className="w-5 h-5 mr-2 text-green-600" />
                Bet Slip
              </h3>
              <div className="text-center py-8 text-gray-500">
                <Target className="w-8 h-8 mx-auto mb-2 text-gray-300" />
                <p className="text-sm font-medium mb-1">No bets selected</p>
                <p className="text-xs text-gray-400">Click "Place Bet" on any game to add it here</p>
              </div>
            </div>

            {/* Quick Stats */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <h3 className="text-lg font-semibold mb-4 flex items-center">
                <TrendingUp className="w-5 h-5 mr-2 text-blue-600" />
                Account Overview
              </h3>
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <span className="text-gray-600">Pending Bets</span>
                  <span className="font-semibold">0</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-gray-600">Available Balance</span>
                  <span className="font-semibold text-green-600">$100.00</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-gray-600">Today's P&L</span>
                  <span className="font-semibold text-gray-900">$0.00</span>
                </div>
                {user?.subscription_tier !== 'free' && (
                  <>
                    <div className="pt-2 border-t border-gray-200">
                      <div className="flex justify-between items-center">
                        <span className="text-gray-600">This Week</span>
                        <span className="font-semibold text-green-600">+$25.50</span>
                      </div>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-gray-600">Win Rate</span>
                      <span className="font-semibold">78.5%</span>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Betting Tips */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
              <h3 className="text-lg font-semibold mb-3 text-blue-900 flex items-center">
                <AlertCircle className="w-5 h-5 mr-2" />
                Betting Tips
              </h3>
              <div className="space-y-2 text-sm text-blue-800">
                <p>• Compare odds across multiple bookmakers</p>
                <p>• Start with small amounts while learning</p>
                <p>• Set a budget and stick to it</p>
                {user?.subscription_tier !== 'free' && (
                  <p>• Check AI recommendations before betting</p>
                )}
              </div>
              <div className="mt-3 pt-3 border-t border-blue-200">
                <p className="text-xs text-blue-700">
                  Remember: Bet responsibly. Must be 21+ to place bets.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Bet Modal */}
      <BetModal
        isOpen={showBetModal}
        onClose={() => {
          setShowBetModal(false);
          setSelectedGame(null);
        }}
        game={selectedGame}
      />
    </Layout>
  );
}