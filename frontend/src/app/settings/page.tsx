'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { useNotifications } from '@/components/NotificationProvider';
import { DetailedWebSocketStatus } from '@/components/WebSocketIndicator';
import { User, Bell, Shield, CreditCard, Smartphone, Eye, EyeOff, TestTube } from 'lucide-react';

export default function SettingsPage() {
  const { isAuthenticated, loading } = useAuth();
  const { addNotification } = useNotifications();
  const router = useRouter();
  const [showPassword, setShowPassword] = useState(false);

  const testNotification = (type: 'bet_won' | 'odds_change' | 'prediction' | 'achievement') => {
    const testNotifications = {
      bet_won: {
        type: 'bet_won' as const,
        title: 'Test Bet Won!',
        message: 'Your test bet just won! +$50.00',
        priority: 'high' as const
      },
      odds_change: {
        type: 'odds_change' as const,
        title: 'Test Odds Change',
        message: 'Odds changed for Test Game (+150 → +175)',
        priority: 'medium' as const
      },
      prediction: {
        type: 'prediction' as const,
        title: 'Test AI Prediction',
        message: 'New high-confidence test prediction available',
        priority: 'medium' as const
      },
      achievement: {
        type: 'achievement' as const,
        title: 'Test Achievement!',
        message: 'You unlocked a test achievement badge',
        priority: 'low' as const
      }
    };

    addNotification(testNotifications[type]);
  };

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

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
        <h1 className="text-3xl font-bold text-gray-900">Settings</h1>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            {/* Profile Settings */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <div className="flex items-center mb-6">
                <User className="w-6 h-6 text-gray-600 mr-3" />
                <h2 className="text-xl font-semibold">Profile</h2>
              </div>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Display Name</label>
                  <input
                    type="text"
                    defaultValue="John Doe"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Email</label>
                  <input
                    type="email"
                    defaultValue="john@example.com"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Password</label>
                  <div className="relative">
                    <input
                      type={showPassword ? 'text' : 'password'}
                      defaultValue="••••••••"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600"
                    >
                      {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Notification Settings */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <div className="flex items-center mb-6">
                <Bell className="w-6 h-6 text-gray-600 mr-3" />
                <h2 className="text-xl font-semibold">Notifications</h2>
              </div>
              
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">Bet Updates</h3>
                    <p className="text-sm text-gray-600">Get notified when your bets win or lose</p>
                  </div>
                  <input type="checkbox" defaultChecked className="toggle" />
                </div>
                
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">AI Predictions</h3>
                    <p className="text-sm text-gray-600">Receive AI-powered betting insights</p>
                  </div>
                  <input type="checkbox" defaultChecked className="toggle" />
                </div>

                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">Game Alerts</h3>
                    <p className="text-sm text-gray-600">Notifications for upcoming games</p>
                  </div>
                  <input type="checkbox" className="toggle" />
                </div>
              </div>
            </div>

            {/* Security Settings */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <div className="flex items-center mb-6">
                <Shield className="w-6 h-6 text-gray-600 mr-3" />
                <h2 className="text-xl font-semibold">Security</h2>
              </div>
              
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">Two-Factor Authentication</h3>
                    <p className="text-sm text-gray-600">Add an extra layer of security</p>
                  </div>
                  <button className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                    Enable
                  </button>
                </div>
                
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">Login Alerts</h3>
                    <p className="text-sm text-gray-600">Get notified of new login attempts</p>
                  </div>
                  <input type="checkbox" defaultChecked className="toggle" />
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-6">
            {/* Payment Methods */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <div className="flex items-center mb-6">
                <CreditCard className="w-6 h-6 text-gray-600 mr-3" />
                <h2 className="text-xl font-semibold">Payment</h2>
              </div>
              
              <div className="space-y-4">
                <div className="p-3 border border-gray-200 rounded-lg">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium">•••• •••• •••• 1234</p>
                      <p className="text-sm text-gray-600">Expires 12/25</p>
                    </div>
                    <button className="text-blue-600 hover:text-blue-700 text-sm">Edit</button>
                  </div>
                </div>
                
                <button className="w-full px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors">
                  Add Payment Method
                </button>
              </div>
            </div>

            {/* App Settings */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <div className="flex items-center mb-6">
                <Smartphone className="w-6 h-6 text-gray-600 mr-3" />
                <h2 className="text-xl font-semibold">App Preferences</h2>
              </div>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Theme</label>
                  <select className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500">
                    <option>Light</option>
                    <option>Dark</option>
                    <option>Auto</option>
                  </select>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Default Sport</label>
                  <select className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500">
                    <option>NFL</option>
                    <option>NBA</option>
                    <option>MLB</option>
                    <option>NHL</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Developer Tools */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <div className="flex items-center mb-6">
                <TestTube className="w-6 h-6 text-gray-600 mr-3" />
                <h2 className="text-xl font-semibold">Developer Tools</h2>
              </div>
              
              <div className="space-y-4">
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-3">Test Notifications</h3>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      onClick={() => testNotification('bet_won')}
                      className="px-3 py-2 text-sm bg-green-100 text-green-700 rounded-lg hover:bg-green-200 transition-colors"
                    >
                      Test Bet Won
                    </button>
                    <button
                      onClick={() => testNotification('odds_change')}
                      className="px-3 py-2 text-sm bg-blue-100 text-blue-700 rounded-lg hover:bg-blue-200 transition-colors"
                    >
                      Test Odds Change
                    </button>
                    <button
                      onClick={() => testNotification('prediction')}
                      className="px-3 py-2 text-sm bg-purple-100 text-purple-700 rounded-lg hover:bg-purple-200 transition-colors"
                    >
                      Test Prediction
                    </button>
                    <button
                      onClick={() => testNotification('achievement')}
                      className="px-3 py-2 text-sm bg-yellow-100 text-yellow-700 rounded-lg hover:bg-yellow-200 transition-colors"
                    >
                      Test Achievement
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <button className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
              Save Changes
            </button>
          </div>

          <div className="space-y-6">
            {/* WebSocket Status */}
            <DetailedWebSocketStatus />
          </div>
        </div>
      </div>
    </Layout>
  );
}