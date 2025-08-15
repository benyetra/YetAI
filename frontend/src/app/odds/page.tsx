'use client';

import { useState, useEffect } from 'react';
import Layout from '@/components/Layout';
import { apiClient } from '@/lib/api';
import { TrendingUp, TrendingDown, Minus, Clock, DollarSign } from 'lucide-react';

export default function OddsPage() {
  const [odds, setOdds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedSport, setSelectedSport] = useState('nfl');

  useEffect(() => {
    fetchOdds();
  }, [selectedSport]);

  const fetchOdds = async () => {
    setLoading(true);
    try {
      const data = await apiClient.get(`/api/odds/${selectedSport}`);
      setOdds(data.odds || []);
    } catch (error) {
      console.error('Error fetching odds:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Layout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold text-gray-900">Live Odds</h1>
          <select
            value={selectedSport}
            onChange={(e) => setSelectedSport(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="nfl">NFL</option>
            <option value="nba">NBA</option>
            <option value="mlb">MLB</option>
            <option value="nhl">NHL</option>
          </select>
        </div>

        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {odds.map((game: any, index: number) => (
              <div key={index} className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-medium px-2 py-1 bg-gray-100 rounded">
                    {selectedSport.toUpperCase()}
                  </span>
                  <Clock className="w-4 h-4 text-gray-500" />
                </div>
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <span className="font-medium">{game.away_team}</span>
                    <span className="text-lg font-bold">+110</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="font-medium">{game.home_team}</span>
                    <span className="text-lg font-bold">-130</span>
                  </div>
                </div>
                <button className="w-full mt-4 bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 transition-colors">
                  Place Bet
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}