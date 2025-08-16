'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { useNotifications } from '@/components/NotificationProvider';
import { DetailedWebSocketStatus } from '@/components/WebSocketIndicator';
import { sportsAPI, apiClient } from '@/lib/api';
import { User, Bell, Shield, CreditCard, Smartphone, Eye, EyeOff, TestTube, Save, AlertCircle, QrCode, Copy, Check, X } from 'lucide-react';

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
  
  // 2FA state
  const [show2FAModal, setShow2FAModal] = useState(false);
  const [twoFAStatus, setTwoFAStatus] = useState({
    enabled: false,
    backup_codes_remaining: 0,
    setup_in_progress: false
  });
  const [qrCodeData, setQrCodeData] = useState('');
  const [secretKey, setSecretKey] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [verificationCode, setVerificationCode] = useState('');
  const [setupStep, setSetupStep] = useState(1); // 1: QR, 2: Verify, 3: Backup codes
  const [copiedCodes, setCopiedCodes] = useState(false);

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
      
      // Parse user preferences with better error handling
      try {
        let favoriteTeams = [];
        let preferredSports = ['NFL'];
        let notificationSettings = {};
        
        // Safely parse favorite_teams
        if (user.favorite_teams) {
          try {
            favoriteTeams = typeof user.favorite_teams === 'string' 
              ? JSON.parse(user.favorite_teams) 
              : Array.isArray(user.favorite_teams) ? user.favorite_teams : [];
          } catch (e) {
            console.warn('Error parsing favorite_teams:', e);
            favoriteTeams = [];
          }
        }
        
        // Safely parse preferred_sports
        if (user.preferred_sports) {
          try {
            preferredSports = typeof user.preferred_sports === 'string' 
              ? JSON.parse(user.preferred_sports) 
              : Array.isArray(user.preferred_sports) ? user.preferred_sports : ['NFL'];
          } catch (e) {
            console.warn('Error parsing preferred_sports:', e);
            preferredSports = ['NFL'];
          }
        }
        
        // Safely parse notification_settings
        if (user.notification_settings) {
          try {
            notificationSettings = typeof user.notification_settings === 'string' 
              ? JSON.parse(user.notification_settings) 
              : (typeof user.notification_settings === 'object' ? user.notification_settings : {});
          } catch (e) {
            console.warn('Error parsing notification_settings:', e);
            notificationSettings = {};
          }
        }
        
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
        console.error('Error setting up user preferences:', error);
        // Set safe defaults
        setPreferences({
          favorite_teams: [],
          preferred_sports: ['NFL'],
          notification_settings: {
            bet_updates: true,
            ai_predictions: true,
            game_alerts: false,
            login_alerts: true,
            email: true,
            push: false
          }
        });
      }
      
      // Load app preferences from localStorage
      try {
        const savedTheme = localStorage.getItem('app_theme') || 'light';
        const savedDefaultSport = localStorage.getItem('default_sport') || 'NFL';
        setAppPreferences({
          theme: savedTheme,
          default_sport: savedDefaultSport
        });
      } catch (error) {
        console.error('Error loading app preferences:', error);
        setAppPreferences({
          theme: 'light',
          default_sport: 'NFL'
        });
      }
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
  
  // Load 2FA status
  useEffect(() => {
    const load2FAStatus = async () => {
      if (!token) return;
      
      try {
        const response = await apiClient.get('/api/auth/2fa/status', token);
        if (response.status === 'success') {
          setTwoFAStatus({
            enabled: response.data?.enabled || false,
            backup_codes_remaining: response.data?.backup_codes_remaining || 0,
            setup_in_progress: response.data?.setup_in_progress || false
          });
        }
      } catch (error) {
        console.error('Error loading 2FA status:', error);
        // Set safe defaults on error
        setTwoFAStatus({
          enabled: false,
          backup_codes_remaining: 0,
          setup_in_progress: false
        });
      }
    };
    
    if (isAuthenticated && token) {
      load2FAStatus();
    }
  }, [isAuthenticated, token]);

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
  
  // 2FA functions
  const start2FASetup = async () => {
    setIsLoading(true);
    try {
      const response = await apiClient.post('/api/auth/2fa/setup', {}, token);
      if (response.status === 'success') {
        setQrCodeData(response.data.qr_code);
        setSecretKey(response.data.secret);
        setBackupCodes(response.data.backup_codes);
        setSetupStep(1);
        setShow2FAModal(true);
      } else {
        throw new Error(response.detail || 'Failed to setup 2FA');
      }
    } catch (error: any) {
      addNotification({
        type: 'system',
        title: '2FA Setup Failed',
        message: error.message || 'Failed to setup 2FA. Please try again.',
        priority: 'high'
      });
    } finally {
      setIsLoading(false);
    }
  };
  
  const verify2FASetup = async () => {
    if (!verificationCode || verificationCode.length !== 6) {
      addNotification({
        type: 'system',
        title: 'Invalid Code',
        message: 'Please enter a 6-digit verification code',
        priority: 'high'
      });
      return;
    }
    
    setIsLoading(true);
    try {
      const response = await apiClient.post('/api/auth/2fa/enable', {
        token: verificationCode
      }, token);
      
      if (response.status === 'success') {
        setSetupStep(3); // Show backup codes
        setTwoFAStatus(prev => ({ ...prev, enabled: true, backup_codes_remaining: backupCodes.length }));
        addNotification({
          type: 'system',
          title: '2FA Enabled',
          message: 'Two-factor authentication has been enabled successfully',
          priority: 'medium'
        });
      } else {
        throw new Error(response.detail || 'Invalid verification code');
      }
    } catch (error: any) {
      addNotification({
        type: 'system',
        title: 'Verification Failed',
        message: error.message || 'Invalid verification code. Please try again.',
        priority: 'high'
      });
    } finally {
      setIsLoading(false);
    }
  };
  
  const disable2FA = async () => {
    // This would require password + 2FA token, implement later
    addNotification({
      type: 'system',
      title: 'Feature Coming Soon',
      message: '2FA disable functionality will be available soon',
      priority: 'low'
    });
  };
  
  const copyBackupCodes = async () => {
    const codesText = backupCodes.join('\n');
    try {
      await navigator.clipboard.writeText(codesText);
      setCopiedCodes(true);
      setTimeout(() => setCopiedCodes(false), 2000);
      addNotification({
        type: 'system',
        title: 'Codes Copied',
        message: 'Backup codes copied to clipboard',
        priority: 'low'
      });
    } catch (error) {
      addNotification({
        type: 'system',
        title: 'Copy Failed',
        message: 'Failed to copy codes. Please save them manually.',
        priority: 'high'
      });
    }
  };
  
  const close2FAModal = () => {
    setShow2FAModal(false);
    setSetupStep(1);
    setVerificationCode('');
    setQrCodeData('');
    setSecretKey('');
    setBackupCodes([]);
    setCopiedCodes(false);
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
                    <p className="text-sm text-gray-600">
                      {twoFAStatus?.enabled ? 'Enabled - Your account is secured with 2FA' : 'Add an extra layer of security'}
                    </p>
                    {twoFAStatus?.enabled && (
                      <p className="text-xs text-green-600 mt-1">
                        {twoFAStatus?.backup_codes_remaining || 0} backup codes remaining
                      </p>
                    )}
                  </div>
                  <button 
                    onClick={twoFAStatus?.enabled ? disable2FA : start2FASetup}
                    disabled={isLoading}
                    className={`px-4 py-2 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                      twoFAStatus?.enabled 
                        ? 'bg-red-600 text-white hover:bg-red-700' 
                        : 'bg-blue-600 text-white hover:bg-blue-700'
                    }`}
                  >
                    {twoFAStatus?.enabled ? 'Disable' : 'Enable'}
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
                    {Array.isArray(sportsList) && sportsList.map((sport) => (
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
        
        {/* 2FA Setup Modal */}
        {show2FAModal && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg max-w-md w-full p-6">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-semibold">Setup Two-Factor Authentication</h2>
                <button 
                  onClick={close2FAModal}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              
              {setupStep === 1 && (
                <div className="space-y-4">
                  <div className="text-center">
                    <QrCode className="w-8 h-8 text-blue-600 mx-auto mb-4" />
                    <h3 className="font-medium mb-2">Scan QR Code</h3>
                    <p className="text-sm text-gray-600 mb-4">
                      Use your authenticator app (Google Authenticator, Authy, etc.) to scan this QR code:
                    </p>
                  </div>
                  
                  {qrCodeData && (
                    <div className="flex justify-center mb-4">
                      <img src={qrCodeData} alt="2FA QR Code" className="border rounded-lg" />
                    </div>
                  )}
                  
                  <div className="bg-gray-50 p-3 rounded-lg">
                    <p className="text-xs text-gray-600 mb-1">Manual Entry Key:</p>
                    <code className="text-sm font-mono break-all">{secretKey}</code>
                  </div>
                  
                  <button
                    onClick={() => setSetupStep(2)}
                    className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                  >
                    I've Added the Account
                  </button>
                </div>
              )}
              
              {setupStep === 2 && (
                <div className="space-y-4">
                  <div className="text-center">
                    <Shield className="w-8 h-8 text-green-600 mx-auto mb-4" />
                    <h3 className="font-medium mb-2">Verify Setup</h3>
                    <p className="text-sm text-gray-600 mb-4">
                      Enter the 6-digit code from your authenticator app:
                    </p>
                  </div>
                  
                  <div>
                    <input
                      type="text"
                      value={verificationCode}
                      onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      placeholder="000000"
                      className="w-full px-4 py-3 text-center text-lg font-mono border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      maxLength={6}
                    />
                  </div>
                  
                  <div className="flex space-x-3">
                    <button
                      onClick={() => setSetupStep(1)}
                      className="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
                    >
                      Back
                    </button>
                    <button
                      onClick={verify2FASetup}
                      disabled={isLoading || verificationCode.length !== 6}
                      className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isLoading ? 'Verifying...' : 'Verify & Enable'}
                    </button>
                  </div>
                </div>
              )}
              
              {setupStep === 3 && (
                <div className="space-y-4">
                  <div className="text-center">
                    <Check className="w-8 h-8 text-green-600 mx-auto mb-4" />
                    <h3 className="font-medium mb-2">2FA Enabled Successfully!</h3>
                    <p className="text-sm text-gray-600 mb-4">
                      Save these backup codes in a safe place. You can use them to access your account if you lose your authenticator device.
                    </p>
                  </div>
                  
                  <div className="bg-gray-50 p-4 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="font-medium text-sm">Backup Codes</h4>
                      <button
                        onClick={copyBackupCodes}
                        className="flex items-center text-sm text-blue-600 hover:text-blue-700"
                      >
                        {copiedCodes ? (
                          <><Check className="w-4 h-4 mr-1" /> Copied</>
                        ) : (
                          <><Copy className="w-4 h-4 mr-1" /> Copy All</>
                        )}
                      </button>
                    </div>
                    <div className="grid grid-cols-2 gap-2 font-mono text-sm">
                      {Array.isArray(backupCodes) && backupCodes.map((code, index) => (
                        <div key={index} className="bg-white p-2 rounded border text-center">
                          {code}
                        </div>
                      ))}
                    </div>
                  </div>
                  
                  <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                    <p className="text-sm text-yellow-800">
                      <strong>Important:</strong> Each backup code can only be used once. Store them securely!
                    </p>
                  </div>
                  
                  <button
                    onClick={close2FAModal}
                    className="w-full px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
                  >
                    Complete Setup
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}