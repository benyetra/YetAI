'use client';

import { useState } from 'react';
import Layout from '@/components/Layout';
import { LiveOdds } from '@/components/LiveOdds';
import { SportsSelector } from '@/components/SportsSelector';
import { LiveScores } from '@/components/LiveScores';
import { TrendingUp, Activity, Trophy, Target, BarChart3, Zap } from 'lucide-react';

export default function OddsPage() {
  const [selectedSport, setSelectedSport] = useState<string>('');
  const [selectedSportTitle, setSelectedSportTitle] = useState<string>('');
  const [activeTab, setActiveTab] = useState<'odds' | 'scores' | 'popular'>('popular');

  const handleSportChange = (sportKey: string, sportTitle: string) => {
    setSelectedSport(sportKey);
    setSelectedSportTitle(sportTitle);
    if (sportKey) {
      setActiveTab('odds');
    }
  };

  return (
    <Layout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between space-y-4 lg:space-y-0">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-[#A855F7]/10 rounded-lg">
              <TrendingUp className="w-6 h-6 text-[#A855F7]" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-gray-900">Live Odds & Scores</h1>
              <p className="text-gray-600">Real-time betting odds and game results</p>
            </div>
          </div>

          {/* Sports Selector */}
          <div className="w-full lg:w-80">
            <SportsSelector
              selectedSport={selectedSport}
              onSportChange={handleSportChange}
              placeholder="Select a sport for odds..."
            />
          </div>
        </div>

        {/* Tabs */}
        <div className="bg-white">
          <nav className="flex space-x-2 py-4">
            <button
              onClick={() => setActiveTab('popular')}
              className={`px-6 py-2.5 font-medium text-sm transition-all duration-200 rounded-full ${
                activeTab === 'popular'
                  ? 'bg-[#A855F7] text-white shadow-lg shadow-[#A855F7]/25'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100 bg-gray-50'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Zap className="w-4 h-4" />
                <span>Popular Sports</span>
              </div>
            </button>

            <button
              onClick={() => setActiveTab('odds')}
              disabled={!selectedSport}
              className={`px-6 py-2.5 font-medium text-sm transition-all duration-200 rounded-full ${
                activeTab === 'odds' && selectedSport
                  ? 'bg-[#A855F7] text-white shadow-lg shadow-[#A855F7]/25'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100 bg-gray-50'
              } ${!selectedSport ? 'opacity-50 cursor-not-allowed hover:bg-gray-50' : ''}`}
            >
              <div className="flex items-center space-x-2">
                <Target className="w-4 h-4" />
                <span>{selectedSportTitle || 'Sport Odds'}</span>
              </div>
            </button>

            <button
              onClick={() => setActiveTab('scores')}
              disabled={!selectedSport}
              className={`px-6 py-2.5 font-medium text-sm transition-all duration-200 rounded-full ${
                activeTab === 'scores' && selectedSport
                  ? 'bg-[#A855F7] text-white shadow-lg shadow-[#A855F7]/25'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100 bg-gray-50'
              } ${!selectedSport ? 'opacity-50 cursor-not-allowed hover:bg-gray-50' : ''}`}
            >
              <div className="flex items-center space-x-2">
                <Trophy className="w-4 h-4" />
                <span>Scores</span>
              </div>
            </button>
          </nav>
        </div>

        {/* Content */}
        <div className="space-y-6">
          {activeTab === 'popular' && (
            <div className="space-y-6">
              {/* Popular Sports Odds */}
              <div>
                <div className="mb-4 flex items-center space-x-2">
                  <Activity className="w-5 h-5 text-[#A855F7]" />
                  <h2 className="text-xl font-semibold text-gray-900">Popular Sports</h2>
                  <span className="text-sm text-gray-600">NFL • NBA • MLB • NHL</span>
                </div>
                <LiveOdds 
                  showPopular={true}
                  autoRefresh={true}
                  refreshInterval={300000} // 5 minutes
                  maxGames={12}
                />
              </div>

              {/* Featured Stats */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-8">
                <div className="bg-gradient-to-r from-[#A855F7] to-[#F59E0B] rounded-lg p-6 text-white">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-medium opacity-90">Live Games</h3>
                      <p className="text-2xl font-bold">8</p>
                    </div>
                    <Activity className="w-8 h-8 opacity-80" />
                  </div>
                </div>

                <div className="bg-white rounded-lg shadow-lg p-6 border">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-medium text-gray-600">Best Odds</h3>
                      <p className="text-2xl font-bold text-gray-900">+450</p>
                    </div>
                    <TrendingUp className="w-8 h-8 text-green-500" />
                  </div>
                </div>

                <div className="bg-white rounded-lg shadow-lg p-6 border">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-medium text-gray-600">Markets</h3>
                      <p className="text-2xl font-bold text-gray-900">150+</p>
                    </div>
                    <BarChart3 className="w-8 h-8 text-[#A855F7]" />
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'odds' && selectedSport && (
            <LiveOdds 
              sportKey={selectedSport}
              autoRefresh={true}
              refreshInterval={180000} // 3 minutes for specific sports
              maxGames={20}
            />
          )}

          {activeTab === 'scores' && selectedSport && (
            <LiveScores 
              sportKey={selectedSport}
              daysFrom={3}
              autoRefresh={true}
              refreshInterval={600000} // 10 minutes
              maxScores={15}
              showCompleted={true}
              showLive={true}
            />
          )}
        </div>

        {/* Help Text */}
        {!selectedSport && (activeTab === 'odds' || activeTab === 'scores') && (
          <div className="bg-gray-50 rounded-lg p-8 text-center">
            <div className="max-w-md mx-auto">
              <Target className="w-12 h-12 text-gray-400 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-gray-900 mb-2">Select a Sport</h3>
              <p className="text-gray-600">
                Choose a sport from the dropdown above to view live odds and scores.
              </p>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}