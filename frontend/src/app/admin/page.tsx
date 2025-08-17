'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { 
  Shield, 
  Plus, 
  Target, 
  Layers, 
  Clock, 
  Save,
  Lock,
  Unlock,
  Users
} from 'lucide-react';


export default function AdminPage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  
  // Form states
  const [betType, setBetType] = useState<'straight' | 'parlay'>('straight');
  const [formData, setFormData] = useState({
    sport: '',
    game: '',
    bet_type: '',
    pick: '',
    odds: '',
    confidence: 80,
    reasoning: '',
    game_time: '',
    is_premium: true
  });
  
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<{type: 'success' | 'error', text: string} | null>(null);

  useEffect(() => {
    if (!loading && (!isAuthenticated || !user?.is_admin)) {
      router.push('/dashboard');
    }
  }, [isAuthenticated, loading, user, router]);

  if (loading) {
    return (
      <Layout>
        <div className="min-h-screen flex items-center justify-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
      </Layout>
    );
  }

  if (!isAuthenticated || !user?.is_admin) {
    return null;
  }

  const handleSubmitBet = async () => {
    setIsSubmitting(true);
    setMessage(null);
    
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch('http://localhost:8000/api/admin/yetai-bets', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(formData)
      });
      
      if (response.ok) {
        setMessage({ type: 'success', text: 'Bet created successfully!' });
        // Reset form
        setFormData({
          sport: '',
          game: '',
          bet_type: '',
          pick: '',
          odds: '',
          confidence: 80,
          reasoning: '',
          game_time: '',
          is_premium: true
        });
      } else {
        const error = await response.json();
        setMessage({ type: 'error', text: error.detail || 'Failed to create bet' });
      }
    } catch (error) {
      console.error('Error creating bet:', error);
      setMessage({ type: 'error', text: 'Network error occurred' });
    } finally {
      setIsSubmitting(false);
    }
  };


  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center">
              <Shield className="w-8 h-8 text-red-600 mr-3" />
              Admin Dashboard
            </h1>
            <p className="text-gray-600 mt-1">
              Create and manage YetAI Bets for all users
            </p>
          </div>
        </div>
        
        {/* Quick Actions */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <button
            onClick={() => router.push('/admin/users')}
            className="bg-white rounded-lg border border-gray-200 p-6 hover:border-blue-500 transition-colors group"
          >
            <div className="flex items-center">
              <Users className="w-8 h-8 text-blue-600 mr-4" />
              <div className="text-left">
                <h3 className="text-lg font-semibold text-gray-900 group-hover:text-blue-600">
                  User Management
                </h3>
                <p className="text-sm text-gray-600">
                  View, edit, and manage all user accounts
                </p>
              </div>
            </div>
          </button>
          
          <div className="bg-white rounded-lg border border-gray-200 p-6 opacity-50 cursor-not-allowed">
            <div className="flex items-center">
              <Shield className="w-8 h-8 text-gray-400 mr-4" />
              <div className="text-left">
                <h3 className="text-lg font-semibold text-gray-500">
                  System Settings
                </h3>
                <p className="text-sm text-gray-400">
                  Coming soon...
                </p>
              </div>
            </div>
          </div>
        </div>
        
        {/* Message Alert */}
        {message && (
          <div className={`p-4 rounded-lg ${
            message.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
          }`}>
            {message.text}
          </div>
        )}

        {/* Bet Constructor */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
            <Plus className="w-5 h-5 mr-2" />
            Create New Bet
          </h2>

          {/* Bet Type Selector */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-2">Bet Type</label>
            <div className="flex space-x-4">
              <button
                onClick={() => setBetType('straight')}
                className={`flex items-center px-4 py-2 rounded-lg font-medium transition-colors ${
                  betType === 'straight'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                <Target className="w-4 h-4 mr-2" />
                Straight Bet
              </button>
              <button
                onClick={() => setBetType('parlay')}
                className={`flex items-center px-4 py-2 rounded-lg font-medium transition-colors ${
                  betType === 'parlay'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                <Layers className="w-4 h-4 mr-2" />
                Parlay Bet (Coming Soon)
              </button>
            </div>
          </div>

          {/* Bet Form Fields */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Sport</label>
              <select
                value={formData.sport}
                onChange={(e) => setFormData({...formData, sport: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="">Select Sport</option>
                <option value="NFL">NFL</option>
                <option value="NBA">NBA</option>
                <option value="MLB">MLB</option>
                <option value="NHL">NHL</option>
                <option value="NCAA Football">NCAA Football</option>
                <option value="NCAA Basketball">NCAA Basketball</option>
                <option value="Soccer">Soccer</option>
                <option value="Tennis">Tennis</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Game</label>
              <input
                type="text"
                value={formData.game}
                onChange={(e) => setFormData({...formData, game: e.target.value})}
                placeholder="e.g., Chiefs vs Bills"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Bet Type</label>
              <select
                value={formData.bet_type}
                onChange={(e) => setFormData({...formData, bet_type: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="">Select Bet Type</option>
                <option value="Spread">Spread</option>
                <option value="Moneyline">Moneyline</option>
                <option value="Total">Total (Over/Under)</option>
                <option value="Puck Line">Puck Line</option>
                <option value="Run Line">Run Line</option>
                <option value="1st Half">1st Half</option>
                <option value="1st Quarter">1st Quarter</option>
                <option value="Player Props">Player Props</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Pick</label>
              <input
                type="text"
                value={formData.pick}
                onChange={(e) => setFormData({...formData, pick: e.target.value})}
                placeholder="e.g., Chiefs -3.5, Over 228.5"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Odds</label>
              <input
                type="text"
                value={formData.odds}
                onChange={(e) => setFormData({...formData, odds: e.target.value})}
                placeholder="e.g., -110, +150"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Game Time</label>
              <input
                type="text"
                value={formData.game_time}
                onChange={(e) => setFormData({...formData, game_time: e.target.value})}
                placeholder="e.g., 8:20 PM EST"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </div>

          {/* Confidence and Access Level */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Confidence Level: {formData.confidence}%
              </label>
              <input
                type="range"
                min="50"
                max="100"
                value={formData.confidence}
                onChange={(e) => setFormData({...formData, confidence: parseInt(e.target.value)})}
                className="w-full"
              />
              <div className="flex justify-between text-xs text-gray-500 mt-1">
                <span>50%</span>
                <span>100%</span>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Access Level</label>
              <div className="flex items-center space-x-4">
                <button
                  onClick={() => setFormData({...formData, is_premium: false})}
                  className={`flex items-center px-4 py-2 rounded-lg font-medium transition-colors ${
                    !formData.is_premium
                      ? 'bg-green-600 text-white'
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  <Unlock className="w-4 h-4 mr-2" />
                  Free
                </button>
                <button
                  onClick={() => setFormData({...formData, is_premium: true})}
                  className={`flex items-center px-4 py-2 rounded-lg font-medium transition-colors ${
                    formData.is_premium
                      ? 'bg-yellow-600 text-white'
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  <Lock className="w-4 h-4 mr-2" />
                  Premium
                </button>
              </div>
            </div>
          </div>

          {/* Reasoning */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-2">Reasoning</label>
            <textarea
              value={formData.reasoning}
              onChange={(e) => setFormData({...formData, reasoning: e.target.value})}
              placeholder="Explain your analysis and reasoning for this bet..."
              rows={4}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>

          {/* Submit Button */}
          <button
            onClick={handleSubmitBet}
            disabled={isSubmitting || !formData.sport || !formData.game || !formData.reasoning}
            className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center justify-center"
          >
            {isSubmitting ? (
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
            ) : (
              <>
                <Save className="w-5 h-5 mr-2" />
                Create Bet
              </>
            )}
          </button>
        </div>
      </div>
    </Layout>
  );
}