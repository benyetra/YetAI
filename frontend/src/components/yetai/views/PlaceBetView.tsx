'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/components/Auth';
import BetSlipPlaceModal from '@/components/BetSlipPlaceModal';
import { sportsAPI } from '@/lib/api';
import { apiGameToDesignGame } from '@/lib/yetai-odds';
import PlaceBetScreen from '../screens/PlaceBetScreen';
import type { BetSlipPlaceContext, DesignGame, SlipItem } from '../types';

export default function PlaceBetView() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();
  const [games, setGames] = useState<DesignGame[]>([]);
  const [loadingGames, setLoadingGames] = useState(true);
  const [slip, setSlip] = useState<SlipItem[]>([]);
  const [placeContext, setPlaceContext] = useState<BetSlipPlaceContext | null>(null);
  const [showPlaceModal, setShowPlaceModal] = useState(false);

  useEffect(() => {
    if (!loading && !isAuthenticated) router.push('/?login=true');
  }, [isAuthenticated, loading, router]);

  const loadOdds = useCallback(async (sportKey: string) => {
    setLoadingGames(true);
    try {
      const data = await sportsAPI.getOdds(sportKey);
      const list = data.games || [];
      setGames(list.map(apiGameToDesignGame));
    } catch (e) {
      console.error('Failed to load odds', e);
      setGames([]);
    } finally {
      setLoadingGames(false);
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    sportsAPI.getSports().then((data) => {
      const active = data.sports?.filter((s: { active: boolean }) => s.active) || [];
      const preferred =
        active.find((s: { key: string }) => s.key === 'basketball_nba') ||
        active.find((s: { key: string }) => s.key === 'americanfootball_nfl') ||
        active[0];
      const key = preferred?.key || 'americanfootball_nfl';
      loadOdds(key);
    });
  }, [isAuthenticated, loadOdds]);

  const onPlaceSlip = (ctx: BetSlipPlaceContext) => {
    if (ctx.slip.length === 0) return;
    setPlaceContext(ctx);
    setShowPlaceModal(true);
  };

  const handlePlaced = () => {
    setSlip([]);
  };

  if (loading) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center">
        <div
          className="animate-spin rounded-full h-12 w-12 border-2 border-transparent"
          style={{ borderBottomColor: 'var(--accent)' }}
        />
      </div>
    );
  }

  return (
    <>
      <PlaceBetScreen
        games={games}
        slip={slip}
        setSlip={setSlip}
        onAddToSlip={() => {}}
        onPlaceSlip={onPlaceSlip}
        loading={loadingGames}
      />
      <BetSlipPlaceModal
        isOpen={showPlaceModal}
        onClose={() => {
          setShowPlaceModal(false);
          setPlaceContext(null);
        }}
        context={placeContext}
        onPlaced={handlePlaced}
      />
    </>
  );
}
