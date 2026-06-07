'use client';

import { useEffect, useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import ParlayBuilder from '@/components/ParlayBuilder';
import ParlayList from '@/components/ParlayList';
import AppLoading from '@/components/yetai/AppLoading';
import PageHeader from '@/components/yetai/PageHeader';
import { StatTile } from '@/components/yetai/primitives';
import { sportsAPI } from '@/lib/api';
import { Layers, TrendingUp, DollarSign, Plus } from 'lucide-react';

type ParlayAvailableGame = {
  id: string;
  sport: string;
  teams: string[];
  gameTime: string;
  odds: {
    moneyline: number[];
    spread: string[];
    total: string[];
  };
  raw_moneyline: unknown[];
  raw_spread: unknown[];
  raw_total: unknown[];
};

export default function ParlaysPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();
  const [showParlayBuilder, setShowParlayBuilder] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [availableGames, setAvailableGames] = useState<ParlayAvailableGame[]>([]);
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
      const allGames: Array<Record<string, unknown>> = [];
      const popularResult = await sportsAPI.getPopularOdds();
      if (popularResult.status === 'success' && popularResult.games) {
        allGames.push(...popularResult.games);
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

  const transformApiGamesToParlayFormat = (apiGames: any[]): ParlayAvailableGame[] => {
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

      const odds: ParlayAvailableGame['odds'] = {
        moneyline: [] as number[],
        spread: [] as string[],
        total: [] as string[],
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
    }).filter((game): game is NonNullable<typeof game> => game !== null) as ParlayAvailableGame[];
  };

  const handleParlayCreated = () => {
    setShowParlayBuilder(false);
    setRefreshTrigger(prev => prev + 1);
  };

  if (loading) {
    return (
      <Layout>
        <AppLoading />
      </Layout>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <Layout requiresAuth fullWidth>
      <PageHeader
        title="Parlays"
        subtitle="Build multi-leg slips with boosted payouts"
        actions={
          <button
            type="button"
            onClick={() => setShowParlayBuilder(true)}
            disabled={gamesLoading}
            className="btn btn-primary"
          >
            <Plus size={14} />
            {gamesLoading ? 'Loading games…' : 'Create parlay'}
          </button>
        }
      />

      <div className="stat-grid">
        <StatTile label="Active parlays" value={stats.activeParlays} deltaKind="neutral" icon={<Layers size={12} />} />
        <StatTile label="Win rate" value={`${stats.winRate}%`} deltaKind="up" icon={<TrendingUp size={12} />} />
        <StatTile label="Total winnings" value={`$${stats.totalWinnings.toFixed(2)}`} deltaKind="up" icon={<DollarSign size={12} />} />
      </div>

      <div className="card" style={{ marginTop: 8 }}>
        <h2 className="section-title" style={{ marginBottom: 14 }}>Your parlays</h2>
        <ParlayList refreshTrigger={refreshTrigger} />
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