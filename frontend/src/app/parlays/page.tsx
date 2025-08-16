'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import ParlayBuilder from '@/components/ParlayBuilder';
import ParlayList from '@/components/ParlayList';
import { Layers, TrendingUp, DollarSign, Plus } from 'lucide-react';

export default function ParlaysPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();
  const [showParlayBuilder, setShowParlayBuilder] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
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
    }
  }, [isAuthenticated, refreshTrigger]);

  const fetchParlayStats = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch('http://localhost:8000/api/bets/parlays', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      const result = await response.json();
      if (result.status === 'success') {
        const parlays = result.parlays || [];
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
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center"
            style={{ color: 'white', backgroundColor: '#2563eb' }}
          >
            <Plus className="w-4 h-4 mr-2" />
            Create Parlay
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
        />
      )}
    </Layout>
  );
}