'use client';

import { useEffect, useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import ParlayBuilder from '@/components/ParlayBuilder';
import ParlayList from '@/components/ParlayList';
import { sportsAPI } from '@/lib/api';
import { Layers, TrendingUp, DollarSign, Plus } from 'lucide-react';

export default function ParlaysPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();
  const [showParlayBuilder, setShowParlayBuilder] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [availableGames, setAvailableGames] = useState([]);
  const [gamesLoading, setGamesLoading] = useState(false);
  const [stats, setStats] = useState({
    activeParlays: 0,
    winRate: 0,
    totalWinnings: 0
  });

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchParlayStats();
      fetchAvailableGames();
    }
  }, [isAuthenticated, refreshTrigger]);

  const fetchParlayStats = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(getApiUrl('/api/bets/parlays'), {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      const result = await response.json();
      if (result.status === 'success') {
        const parlays = Array.isArray(result.parlays) ? result.parlays : [];
        const activeParlays = parlays.filter((p: any) => p.status === 'pending').length;
        const wonParlays = parlays.filter((p: any) => p.status === 'won').length;
        const totalParlays = parlays.length;
        const winRate = totalParlays > 0 ? (wonParlays / totalParlays) * 100 : 0;
        const totalWinnings = parlays
          .filter((p: any) => p.status === 'won')
          .reduce((sum: number, p: any) => sum + (p.result_amount || p.potential_win), 0);

        setStats({
          activeParlays,
          winRate: Math.round(winRate),
          totalWinnings
        });
      }
    } catch (error) {
      console.error('Failed to fetch parlay stats:', error);
    }
  };

  const fetchAvailableGames = async () => {
    setGamesLoading(true);
    try {
      // Fetch from major sports endpoints to get diverse games
      const majorSports = ['americanfootball_nfl', 'basketball_nba', 'baseball_mlb', 'icehockey_nhl'];
      const allGames = [];
      
      // Use Promise.allSettled to get results from all sports, even if some fail
      const results = await Promise.allSettled(
        majorSports.map(sport => sportsAPI.getOdds(sport))
      );
      
      results.forEach((result, index) => {
        if (result.status === 'fulfilled' && result.value.status === 'success' && result.value.games) {
          allGames.push(...result.value.games);
        } else {
          console.warn(`Failed to fetch games for ${majorSports[index]}:`, result.status === 'rejected' ? result.reason : 'No games found');
        }
      });
      
      if (allGames.length === 0) {
        // Fallback to popular odds if no games found from individual sports
        console.log('No games found from individual sports, falling back to popular odds');
        const fallbackResult = await sportsAPI.getPopularOdds();
        if (fallbackResult.status === 'success' && fallbackResult.games) {
          allGames.push(...fallbackResult.games);
        }
      }
      
      const transformedGames = transformApiGamesToParlayFormat(allGames);
      setAvailableGames(transformedGames);
      console.log(`Loaded ${transformedGames.length} games from ${new Set(transformedGames.map(g => g.sport)).size} different sports`);
    } catch (error) {
      console.error('Failed to fetch available games:', error);
    } finally {
      setGamesLoading(false);
    }
  };

  const transformApiGamesToParlayFormat = (apiGames: any[]) => {
    return apiGames.map((game: any) => {
      // Find the best bookmaker (FanDuel, DraftKings, BetMGM are preferred)
      const preferredBookmakers = ['fanduel', 'draftkings', 'betmgm'];
      let bestBookmaker = game.bookmakers?.find((b: any) => preferredBookmakers.includes(b.key));
      if (!bestBookmaker && game.bookmakers?.length > 0) {
        bestBookmaker = game.bookmakers[0];
      }

      if (!bestBookmaker) return null;

      // Extract odds data
      const moneylineMarket = bestBookmaker.markets?.find((m: any) => m.key === 'h2h');
      const spreadMarket = bestBookmaker.markets?.find((m: any) => m.key === 'spreads');
      const totalMarket = bestBookmaker.markets?.find((m: any) => m.key === 'totals');

      const odds = {
        moneyline: [],
        spread: [],
        total: []
      };

      // Parse moneyline odds - store as array matching team order [away, home]
      if (moneylineMarket?.outcomes) {
        const awayOutcome = moneylineMarket.outcomes.find((o: any) => o.name === game.away_team);
        const homeOutcome = moneylineMarket.outcomes.find((o: any) => o.name === game.home_team);
        odds.moneyline = [
          awayOutcome?.price || 0,
          homeOutcome?.price || 0
        ];
      }

      // Parse spread odds - store as array matching team order [away, home]
      if (spreadMarket?.outcomes) {
        const awayOutcome = spreadMarket.outcomes.find((o: any) => o.name === game.away_team);
        const homeOutcome = spreadMarket.outcomes.find((o: any) => o.name === game.home_team);
        odds.spread = [
          `${awayOutcome?.point >= 0 ? '+' : ''}${awayOutcome?.point || 0} (${awayOutcome?.price || -110})`,
          `${homeOutcome?.point >= 0 ? '+' : ''}${homeOutcome?.point || 0} (${homeOutcome?.price || -110})`
        ];
      }

      // Parse total odds
      if (totalMarket?.outcomes) {
        const overOutcome = totalMarket.outcomes.find((o: any) => o.name === 'Over');
        const underOutcome = totalMarket.outcomes.find((o: any) => o.name === 'Under');
        odds.total = [
          `O ${overOutcome?.point || 0} (${overOutcome?.price || -110})`,
          `U ${underOutcome?.point || 0} (${underOutcome?.price || -110})`
        ];
      }

      return {
        id: game.id,
        sport: game.sport_title || 'Unknown',
        teams: [game.away_team, game.home_team], // [away, home]
        gameTime: game.commence_time,
        odds,
        // Store raw API data for proper odds extraction
        raw_moneyline: moneylineMarket?.outcomes || [],
        raw_spread: spreadMarket?.outcomes || [],
        raw_total: totalMarket?.outcomes || []
      };
    }).filter(Boolean);
  };

  const handleParlayCreated = () => {
    setShowParlayBuilder(false);
    setRefreshTrigger(prev => prev + 1);
  };

  if (loading) {
    return (
      <Layout>
        <div className="min-h-screen flex items-center justify-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
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
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold text-gray-900">Parlays</h1>
          <button 
            onClick={() => setShowParlayBuilder(true)}
            disabled={gamesLoading}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ color: 'white', backgroundColor: '#2563eb' }}
          >
            <Plus className="w-4 h-4 mr-2" />
            {gamesLoading ? 'Loading Games...' : 'Create Parlay'}
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Layers className="w-8 h-8 text-blue-600" />
              <span className="text-2xl font-bold text-blue-600">{stats.activeParlays}</span>
            </div>
            <h3 className="font-semibold text-gray-900">Active Parlays</h3>
            <p className="text-sm text-gray-600">Pending settlement</p>
          </div>
          
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <TrendingUp className="w-8 h-8 text-green-600" />
              <span className="text-2xl font-bold text-green-600">{stats.winRate}%</span>
            </div>
            <h3 className="font-semibold text-gray-900">Win Rate</h3>
            <p className="text-sm text-gray-600">All time</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <DollarSign className="w-8 h-8 text-purple-600" />
              <span className="text-2xl font-bold text-purple-600">${stats.totalWinnings.toFixed(2)}</span>
            </div>
            <h3 className="font-semibold text-gray-900">Total Winnings</h3>
            <p className="text-sm text-gray-600">All time</p>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-xl font-semibold mb-4">Your Parlays</h2>
          <ParlayList refreshTrigger={refreshTrigger} />
        </div>
      </div>
      
      {showParlayBuilder && (
        <ParlayBuilder 
          isOpen={showParlayBuilder}
          onClose={() => setShowParlayBuilder(false)}
          onParlayCreated={handleParlayCreated}
          availableGames={availableGames}
        />
      )}
    </Layout>
  );
}