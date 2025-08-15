'use client';

import React, { useState, useEffect } from 'react';
import { 
  ChevronDown, 
  Search, 
  Activity, 
  RefreshCw, 
  AlertCircle,
  CheckCircle
} from 'lucide-react';
import { sportsAPI } from '../lib/api';

interface Sport {
  key: string;
  title: string;
  category: string;
  active: boolean;
  has_outrights?: boolean;
}

interface SportsData {
  status: string;
  count: number;
  sports: Sport[];
  cached?: boolean;
  last_updated: string;
}

interface SportsSelectorProps {
  selectedSport?: string;
  onSportChange: (sportKey: string, sportTitle: string) => void;
  showSearch?: boolean;
  showCategories?: boolean;
  className?: string;
  placeholder?: string;
}

const SPORT_ICONS: Record<string, string> = {
  'Football': '🏈',
  'Basketball': '🏀',
  'Baseball': '⚾',
  'Hockey': '🏒',
  'Soccer': '⚽',
  'Tennis': '🎾',
  'Golf': '⛳',
  'Combat Sports': '🥊',
  'Other': '🏆'
};

export function SportsSelector({
  selectedSport,
  onSportChange,
  showSearch = true,
  showCategories = true,
  className = '',
  placeholder = 'Select a sport...'
}: SportsSelectorProps) {
  const [sportsData, setSportsData] = useState<SportsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<string>('All');

  useEffect(() => {
    fetchSports();
  }, []);

  const fetchSports = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const data = await sportsAPI.getSports();
      setSportsData(data);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch sports';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  const getFilteredSports = () => {
    if (!sportsData?.sports) return [];

    let filtered = sportsData.sports.filter(sport => sport.active);

    // Filter by category
    if (selectedCategory !== 'All') {
      filtered = filtered.filter(sport => sport.category === selectedCategory);
    }

    // Filter by search term
    if (searchTerm) {
      filtered = filtered.filter(sport =>
        sport.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
        sport.key.toLowerCase().includes(searchTerm.toLowerCase())
      );
    }

    return filtered;
  };

  const getCategories = () => {
    if (!sportsData?.sports) return [];
    
    const categories = Array.from(new Set(
      sportsData.sports
        .filter(sport => sport.active)
        .map(sport => sport.category)
    )).sort();
    
    return ['All', ...categories];
  };

  const getSelectedSportInfo = () => {
    if (!selectedSport || !sportsData?.sports) return null;
    return sportsData.sports.find(sport => sport.key === selectedSport);
  };

  const handleSportSelect = (sport: Sport) => {
    onSportChange(sport.key, sport.title);
    setIsOpen(false);
    setSearchTerm('');
  };

  if (loading) {
    return (
      <div className={`relative ${className}`}>
        <div className="flex items-center justify-between px-4 py-3 bg-white border border-gray-300 rounded-lg">
          <div className="flex items-center space-x-2">
            <RefreshCw className="w-4 h-4 animate-spin text-gray-400" />
            <span className="text-gray-500">Loading sports...</span>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`relative ${className}`}>
        <div className="flex items-center justify-between px-4 py-3 bg-red-50 border border-red-300 rounded-lg">
          <div className="flex items-center space-x-2">
            <AlertCircle className="w-4 h-4 text-red-500" />
            <span className="text-red-700">{error}</span>
          </div>
          <button
            onClick={fetchSports}
            className="text-red-600 hover:text-red-800 text-sm font-medium"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const filteredSports = getFilteredSports();
  const categories = getCategories();
  const selectedSportInfo = getSelectedSportInfo();

  return (
    <div className={`relative ${className}`}>
      {/* Main selector button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-3 bg-white border border-gray-300 rounded-lg hover:border-gray-400 focus:ring-2 focus:ring-[#A855F7] focus:border-transparent transition-all"
      >
        <div className="flex items-center space-x-3">
          {selectedSportInfo ? (
            <>
              <span className="text-lg">
                {SPORT_ICONS[selectedSportInfo.category] || SPORT_ICONS['Other']}
              </span>
              <div className="text-left">
                <div className="font-medium text-gray-900">{selectedSportInfo.title}</div>
                <div className="text-sm text-gray-500">{selectedSportInfo.category}</div>
              </div>
            </>
          ) : (
            <span className="text-gray-500">{placeholder}</span>
          )}
        </div>
        
        <div className="flex items-center space-x-2">
          {sportsData?.cached && (
            <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-1 rounded">
              Cached
            </span>
          )}
          <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        </div>
      </button>

      {/* Dropdown menu */}
      {isOpen && (
        <div className="absolute z-50 w-full mt-2 bg-white border border-gray-300 rounded-lg shadow-lg max-h-96 overflow-hidden">
          {/* Search */}
          {showSearch && (
            <div className="p-3 border-b border-gray-200">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search sports..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[#A855F7] focus:border-transparent"
                />
              </div>
            </div>
          )}

          {/* Categories */}
          {showCategories && categories.length > 1 && (
            <div className="p-3 border-b border-gray-200">
              <div className="flex flex-wrap gap-2">
                {categories.map((category) => (
                  <button
                    key={category}
                    onClick={() => setSelectedCategory(category)}
                    className={`px-3 py-1 text-sm rounded-full transition-colors ${
                      selectedCategory === category
                        ? 'bg-[#A855F7] text-white'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    {category} {category !== 'All' && SPORT_ICONS[category]}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Sports list */}
          <div className="max-h-64 overflow-y-auto">
            {filteredSports.length === 0 ? (
              <div className="p-4 text-center text-gray-500">
                {searchTerm ? 'No sports match your search' : 'No sports available'}
              </div>
            ) : (
              <div className="py-2">
                {filteredSports.map((sport) => (
                  <button
                    key={sport.key}
                    onClick={() => handleSportSelect(sport)}
                    className={`w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors ${
                      selectedSport === sport.key ? 'bg-[#A855F7]/10 border-r-2 border-[#A855F7]' : ''
                    }`}
                  >
                    <div className="flex items-center space-x-3">
                      <span className="text-lg">
                        {SPORT_ICONS[sport.category] || SPORT_ICONS['Other']}
                      </span>
                      <div className="text-left">
                        <div className={`font-medium ${selectedSport === sport.key ? 'text-[#A855F7]' : 'text-gray-900'}`}>
                          {sport.title}
                        </div>
                        <div className="text-sm text-gray-500">{sport.category}</div>
                      </div>
                    </div>
                    
                    <div className="flex items-center space-x-2">
                      {sport.has_outrights && (
                        <span className="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded">
                          Futures
                        </span>
                      )}
                      {selectedSport === sport.key && (
                        <CheckCircle className="w-4 h-4 text-[#A855F7]" />
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="p-3 border-t border-gray-200 bg-gray-50">
            <div className="flex items-center justify-between text-xs text-gray-500">
              <span>{filteredSports.length} sport{filteredSports.length !== 1 ? 's' : ''} available</span>
              <div className="flex items-center space-x-1">
                <Activity className="w-3 h-3" />
                <span>Updated {sportsData ? new Date(sportsData.last_updated).toLocaleTimeString() : 'never'}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Click outside to close */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setIsOpen(false)}
        />
      )}
    </div>
  );
}