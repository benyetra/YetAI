'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { useNotifications } from '@/components/NotificationProvider';
import { DetailedWebSocketStatus } from '@/components/WebSocketIndicator';
import { sportsAPI, apiClient } from '@/lib/api';
import { User, Bell, Shield, CreditCard, Smartphone, Eye, EyeOff, TestTube, Save, AlertCircle } from 'lucide-react';

export default function SettingsPage() {
  const { isAuthenticated, loading, user, token, refreshUser } = useAuth();
  const { addNotification } = useNotifications();
  const router = useRouter();
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [sportsList, setSportsList] = useState<any[]>([]);
  const [errors, setErrors] = useState<{[key: string]: string}>({});
  
  // Form state
  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    password: '',
    confirmPassword: ''
  });
  
  // Preferences state
  const [preferences, setPreferences] = useState({
    favorite_teams: [] as string[],
    preferred_sports: ['NFL'] as string[],
    notification_settings: {
      bet_updates: true,
      ai_predictions: true,
      game_alerts: false,
      login_alerts: true,
      email: true,
      push: false
    }
  });
  
  // App preferences state
  const [appPreferences, setAppPreferences] = useState({
    theme: 'light',
    default_sport: 'NFL'
  });

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
  
  // Load user data when component mounts
  useEffect(() => {
    if (user && isAuthenticated) {
      // Populate form data with user info
      setFormData({
        first_name: user.first_name || '',
        last_name: user.last_name || '',
        email: user.email || '',
        password: '',
        confirmPassword: ''
      });
      
      // Parse user preferences
      try {
        const favoriteTeams = typeof user.favorite_teams === 'string' 
          ? JSON.parse(user.favorite_teams) 
          : user.favorite_teams || [];
        const preferredSports = typeof user.preferred_sports === 'string' 
          ? JSON.parse(user.preferred_sports) 
          : user.preferred_sports || ['NFL'];
        const notificationSettings = typeof user.notification_settings === 'string' 
          ? JSON.parse(user.notification_settings) 
          : user.notification_settings || {};
        
        setPreferences({
          favorite_teams: favoriteTeams,
          preferred_sports: preferredSports,
          notification_settings: {
            bet_updates: true,
            ai_predictions: true,
            game_alerts: false,
            login_alerts: true,
            email: true,
            push: false,
            ...notificationSettings
          }
        });
      } catch (error) {
        console.error('Error parsing user preferences:', error);
      }
      
      // Load app preferences from localStorage
      const savedTheme = localStorage.getItem('app_theme') || 'light';
      const savedDefaultSport = localStorage.getItem('default_sport') || 'NFL';
      setAppPreferences({
        theme: savedTheme,
        default_sport: savedDefaultSport
      });
    }
  }, [user, isAuthenticated]);
  
  // Load sports list
  useEffect(() => {
    const loadSports = async () => {
      try {
        const sportsData = await sportsAPI.getSports();
        setSportsList(sportsData.sports || []);
      } catch (error) {
        console.error('Error loading sports:', error);
      }
    };
    
    loadSports();
  }, []);

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

  // Validation function
  const validateForm = () => {
    const newErrors: {[key: string]: string} = {};
    
    if (!formData.first_name.trim()) {
      newErrors.first_name = 'First name is required';
    }
    
    if (!formData.last_name.trim()) {
      newErrors.last_name = 'Last name is required';
    }
    
    if (formData.password && formData.password.length < 6) {
      newErrors.password = 'Password must be at least 6 characters';
    }
    
    if (formData.password && formData.password !== formData.confirmPassword) {
      newErrors.confirmPassword = 'Passwords do not match';
    }
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };
  
  // Save changes function
  const handleSaveChanges = async () => {
    if (!validateForm()) {
      addNotification({
        type: 'system',
        title: 'Validation Error',
        message: 'Please fix the form errors before saving',
        priority: 'high'
      });
      return;
    }
    
    setIsLoading(true);
    setErrors({});
    
    try {
      // Update user preferences
      const preferencesData = {
        first_name: formData.first_name,
        last_name: formData.last_name,
        favorite_teams: preferences.favorite_teams,
        preferred_sports: preferences.preferred_sports,
        notification_settings: preferences.notification_settings
      };
      
      const response = await apiClient.put('/api/auth/preferences', preferencesData, token);
      
      if (response.status === 'success') {
        // Refresh user data to reflect the changes
        const refreshResult = await refreshUser();
        
        if (refreshResult?.success) {
          addNotification({
            type: 'system',
            title: 'Settings Saved',
            message: 'Your settings have been updated successfully',
            priority: 'medium'
          });
        } else {
          addNotification({
            type: 'system',
            title: 'Settings Saved',
            message: 'Settings saved, but please refresh the page to see changes',
            priority: 'medium'
          });
        }
        
        // If password was changed, we could handle that separately
        if (formData.password) {
          // For now, just show a message that password change requires separate handling
          addNotification({
            type: 'system',
            title: 'Password Change',
            message: 'Password change functionality will be available soon',
            priority: 'low'
          });
        }
      } else {
        throw new Error(response.detail || 'Failed to save settings');
      }
    } catch (error: any) {
      console.error('Error saving settings:', error);
      addNotification({
        type: 'system',
        title: 'Save Failed',
        message: error.message || 'Failed to save settings. Please try again.',
        priority: 'high'
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
          {user && (
            <div className="flex items-center space-x-2 text-sm text-gray-600">
              <User className="w-4 h-4" />
              <span>{user.subscription_tier?.charAt(0).toUpperCase() + user.subscription_tier?.slice(1)} Account</span>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            {/* Profile Settings */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <div className="flex items-center mb-6">
                <User className="w-6 h-6 text-gray-600 mr-3" />
                <h2 className="text-xl font-semibold">Profile</h2>
              </div>
              
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">First Name</label>
                    <input
                      type="text"
                      value={formData.first_name}
                      onChange={(e) => setFormData({...formData, first_name: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Enter first name"
                    />
                    {errors.first_name && (
                      <p className="text-red-500 text-sm mt-1">{errors.first_name}</p>
                    )}
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Last Name</label>
                    <input
                      type="text"
                      value={formData.last_name}
                      onChange={(e) => setFormData({...formData, last_name: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Enter last name"
                    />
                    {errors.last_name && (
                      <p className="text-red-500 text-sm mt-1">{errors.last_name}</p>
                    )}
                  </div>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Email</label>
                  <input
                    type="email"
                    value={formData.email}
                    onChange={(e) => setFormData({...formData, email: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 bg-gray-50"
                    placeholder="Enter email address"
                    disabled
                  />
                  <p className="text-gray-500 text-sm mt-1">Email address cannot be changed</p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">New Password</label>
                  <div className="relative">
                    <input
                      type={showPassword ? 'text' : 'password'}
                      value={formData.password}
                      onChange={(e) => setFormData({...formData, password: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Enter new password (leave blank to keep current)"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600"
                    >
                      {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  {errors.password && (
                    <p className="text-red-500 text-sm mt-1">{errors.password}</p>
                  )}
                </div>
                
                {formData.password && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Confirm New Password</label>
                    <input
                      type="password"
                      value={formData.confirmPassword}
                      onChange={(e) => setFormData({...formData, confirmPassword: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Confirm new password"
                    />
                    {errors.confirmPassword && (
                      <p className="text-red-500 text-sm mt-1">{errors.confirmPassword}</p>
                    )}
                  </div>
                )}
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
                  <input 
                    type="checkbox" 
                    checked={preferences.notification_settings.bet_updates}
                    onChange={(e) => setPreferences({
                      ...preferences,
                      notification_settings: {
                        ...preferences.notification_settings,
                        bet_updates: e.target.checked
                      }
                    })}
                    className="w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500"
                  />
                </div>
                
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">AI Predictions</h3>
                    <p className="text-sm text-gray-600">Receive AI-powered betting insights</p>
                  </div>
                  <input 
                    type="checkbox" 
                    checked={preferences.notification_settings.ai_predictions}
                    onChange={(e) => setPreferences({
                      ...preferences,
                      notification_settings: {
                        ...preferences.notification_settings,
                        ai_predictions: e.target.checked
                      }
                    })}
                    className="w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500"
                  />
                </div>

                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">Game Alerts</h3>
                    <p className="text-sm text-gray-600">Notifications for upcoming games</p>
                  </div>
                  <input 
                    type="checkbox" 
                    checked={preferences.notification_settings.game_alerts}
                    onChange={(e) => setPreferences({
                      ...preferences,
                      notification_settings: {
                        ...preferences.notification_settings,
                        game_alerts: e.target.checked
                      }
                    })}
                    className="w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500"
                  />
                </div>
                
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">Email Notifications</h3>
                    <p className="text-sm text-gray-600">Receive notifications via email</p>
                  </div>
                  <input 
                    type="checkbox" 
                    checked={preferences.notification_settings.email}
                    onChange={(e) => setPreferences({
                      ...preferences,
                      notification_settings: {
                        ...preferences.notification_settings,
                        email: e.target.checked
                      }
                    })}
                    className="w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500"
                  />
                </div>
                
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">Push Notifications</h3>
                    <p className="text-sm text-gray-600">Receive browser push notifications</p>
                  </div>
                  <input 
                    type="checkbox" 
                    checked={preferences.notification_settings.push}
                    onChange={(e) => setPreferences({
                      ...preferences,
                      notification_settings: {
                        ...preferences.notification_settings,
                        push: e.target.checked
                      }
                    })}
                    className="w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500"
                  />
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
                  <input 
                    type="checkbox" 
                    checked={preferences.notification_settings.login_alerts}
                    onChange={(e) => setPreferences({
                      ...preferences,
                      notification_settings: {
                        ...preferences.notification_settings,
                        login_alerts: e.target.checked
                      }
                    })}
                    className="w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500"
                  />
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
                  <select 
                    value={appPreferences.theme}
                    onChange={(e) => {
                      setAppPreferences({...appPreferences, theme: e.target.value});
                      localStorage.setItem('app_theme', e.target.value);
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="light">Light</option>
                    <option value="dark">Dark</option>
                    <option value="auto">Auto</option>
                  </select>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Default Sport</label>
                  <select 
                    value={appPreferences.default_sport}
                    onChange={(e) => {
                      setAppPreferences({...appPreferences, default_sport: e.target.value});
                      localStorage.setItem('default_sport', e.target.value);
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="NFL">NFL</option>
                    <option value="NBA">NBA</option>
                    <option value="MLB">MLB</option>
                    <option value="NHL">NHL</option>
                    <option value="NCAAF">NCAAF</option>
                    <option value="NCAAB">NCAAB</option>
                  </select>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Preferred Sports</label>
                  <div className="space-y-2 max-h-32 overflow-y-auto">
                    {sportsList.map((sport) => (
                      <div key={sport.key} className="flex items-center">
                        <input
                          type="checkbox"
                          id={sport.key}
                          checked={preferences.preferred_sports.includes(sport.title)}
                          onChange={(e) => {
                            const newSports = e.target.checked
                              ? [...preferences.preferred_sports, sport.title]
                              : preferences.preferred_sports.filter(s => s !== sport.title);
                            setPreferences({...preferences, preferred_sports: newSports});
                          }}
                          className="w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500 mr-2"
                        />
                        <label htmlFor={sport.key} className="text-sm text-gray-700">
                          {sport.title}
                        </label>
                      </div>
                    ))}
                  </div>
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

            <button 
              onClick={handleSaveChanges}
              disabled={isLoading}
              className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
            >
              {isLoading ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                  Saving...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4 mr-2" />
                  Save Changes
                </>
              )}
            </button>
          </div>

          <div className="space-y-6">
            {/* WebSocket Status */}
            <DetailedWebSocketStatus />
          </div>
        </div>
        
        {/* Status Messages */}
        {Object.keys(errors).length > 0 && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex items-center">
              <AlertCircle className="w-5 h-5 text-red-600 mr-2" />
              <h3 className="text-red-800 font-medium">Please fix the following errors:</h3>
            </div>
            <ul className="mt-2 text-red-700 text-sm">
              {Object.values(errors).map((error, index) => (
                <li key={index}>• {error}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Layout>
  );
}