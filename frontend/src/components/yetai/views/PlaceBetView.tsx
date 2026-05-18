'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/components/Auth';
import BetModal from '@/components/BetModal';
import { sportsAPI, oddsUtils } from '@/lib/api';
import { apiGameToDesignGame } from '@/lib/yetai-odds';
import PlaceBetScreen from '../screens/PlaceBetScreen';
import type { DesignGame, SlipItem } from '../types';

export default function PlaceBetView() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();
  const [games, setGames] = useState<DesignGame[]>([]);
  const [loadingGames, setLoadingGames] = useState(true);
  const [selectedSport, setSelectedSport] = useState('americanfootball_nfl');
  const [slip, setSlip] = useState<SlipItem[]>([]);
  const [modalGame, setModalGame] = useState<unknown>(null);
  const [showModal, setShowModal] = useState(false);

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
      setSelectedSport(key);
      loadOdds(key);
    });
  }, [isAuthenticated, loadOdds]);

  const onAddToSlip = (item: SlipItem) => {
    if (item.rawGame) {
      setModalGame(oddsUtils.toSimpleGame(item.rawGame as Parameters<typeof oddsUtils.toSimpleGame>[0]));
    }
  };

  const onPlaceSlip = () => {
    if (slip.length === 0) return;
    const first = slip[0];
    if (first.rawGame) {
      setModalGame(oddsUtils.toSimpleGame(first.rawGame as Parameters<typeof oddsUtils.toSimpleGame>[0]));
      setShowModal(true);
    }
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
        onAddToSlip={onAddToSlip}
        onPlaceSlip={onPlaceSlip}
        loading={loadingGames}
      />
      <BetModal
        isOpen={showModal}
        onClose={() => {
          setShowModal(false);
          setModalGame(null);
        }}
        game={modalGame}
      />
    </>
  );
}
