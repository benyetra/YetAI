'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { useNotifications } from '@/components/NotificationProvider';
import { DetailedWebSocketStatus } from '@/components/WebSocketIndicator';
import { sportsAPI, apiClient } from '@/lib/api';
import Avatar, { AvatarRef } from '@/components/Avatar';
import { 
  User, 
  Mail, 
  Lock,
  Save,
  AlertCircle,
  Eye,
  EyeOff,
  Check,
  X,
  Camera,
  Upload,
  Trash2,
  UserCircle,
  Shield,
  Heart,
  Bell,
  TestTube,
  QrCode,
  Copy,
  Smartphone
} from 'lucide-react';

export default function ProfilePage() {
  const { isAuthenticated, loading, user, token, logout, refreshUser } = useAuth();
  const { addNotification } = useNotifications();
  const router = useRouter();
  
  const [profileData, setProfileData] = useState({
    email: '',
    username: '',
    first_name: '',
    last_name: '',
    current_password: '',
    new_password: '',
    confirm_password: ''
  });
  
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<{type: 'success' | 'error', text: string} | null>(null);
  const [emailChanged, setEmailChanged] = useState(false);
  
  // Avatar state
  const [avatarUrl, setAvatarUrl] = useState<string>('');
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false);
  const avatarRef = useRef<AvatarRef>(null);
  
  // Settings state
  const [isLoading, setIsLoading] = useState(false);
  const [sportsList, setSportsList] = useState<any[]>([]);
  
  // Preferences state
  const [preferences, setPreferences] = useState({
    favorite_teams: [] as string[],
    preferred_sports: ['americanfootball_nfl'] as string[],
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
    default_sport: 'americanfootball_nfl'
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
  const [setupStep, setSetupStep] = useState(1);
  const [copiedCodes, setCopiedCodes] = useState(false);

  // Data migration helper to normalize sport formats  
  const normalizeSportKeys = (sports: string[]): string[] => {
    const sportKeyMap: { [key: string]: string } = {
      'NFL': 'americanfootball_nfl',
      'NBA': 'basketball_nba', 
      'MLB': 'baseball_mlb',
      'NHL': 'icehockey_nhl',
      'NCAAB': 'basketball_ncaab',
      'NCAAF': 'americanfootball_ncaaf',
      'WNBA': 'basketball_wnba',
      'EPL': 'soccer_epl'
    };
    
    return sports.map(sport => sportKeyMap[sport] || sport);
  };

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

  // Refresh user data on profile page load
  useEffect(() => {
    if (isAuthenticated && token && !loading) {
      refreshUser();
    }
  }, [isAuthenticated, token, loading]);

  // Initialize form with user data
  useEffect(() => {
    if (user) {
      setProfileData(prev => ({
        ...prev,
        email: user.email || '',
        username: user.username || '',
        first_name: user.first_name || '',
        last_name: user.last_name || ''
      }));
      setAvatarUrl(user.avatar_url || '');
    }
  }, [user]);
  
  // Load user preferences when component mounts
  useEffect(() => {
    if (user && isAuthenticated) {
      try {
        let favoriteTeams = [];
        let preferredSports = ['americanfootball_nfl'];
        let notificationSettings = {};
        
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
        
        if (user.preferred_sports) {
          try {
            const rawSports = typeof user.preferred_sports === 'string' 
              ? JSON.parse(user.preferred_sports) 
              : Array.isArray(user.preferred_sports) ? user.preferred_sports : ['americanfootball_nfl'];
            preferredSports = normalizeSportKeys(rawSports);
          } catch (e) {
            console.warn('Error parsing preferred_sports:', e);
            preferredSports = ['americanfootball_nfl'];
          }
        }
        
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
        setPreferences({
          favorite_teams: [],
          preferred_sports: ['americanfootball_nfl'],
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
      
      try {
        const savedTheme = localStorage.getItem('app_theme') || 'light';
        const savedDefaultSport = localStorage.getItem('default_sport') || 'americanfootball_nfl';
        setAppPreferences({
          theme: savedTheme,
          default_sport: savedDefaultSport
        });
      } catch (error) {
        console.error('Error loading app preferences:', error);
        setAppPreferences({
          theme: 'light',
          default_sport: 'americanfootball_nfl'
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
            enabled: response.enabled || false,
            backup_codes_remaining: response.backup_codes_remaining || 0,
            setup_in_progress: response.setup_in_progress || false
          });
        } else if (response.status === 'error') {
          console.error('2FA status API error:', response.detail);
        }
      } catch (error) {
        console.error('Error loading 2FA status:', error);
      }
    };
    
    if (isAuthenticated && token) {
      load2FAStatus();
    }
  }, [isAuthenticated, token]);

  const handleInputChange = (field: string, value: string) => {
    setProfileData(prev => ({ ...prev, [field]: value }));
    
    if (field === 'email' && user && value !== user.email) {
      setEmailChanged(true);
    } else if (field === 'email') {
      setEmailChanged(false);
    }
  };

  const validateForm = () => {
    if (!profileData.email || !profileData.first_name || !profileData.username) {
      setMessage({ type: 'error', text: 'Email, username, and first name are required' });
      return false;
    }

    if (profileData.username.length < 3) {
      setMessage({ type: 'error', text: 'Username must be at least 3 characters long' });
      return false;
    }

    if (!/^[a-zA-Z0-9_-]+$/.test(profileData.username)) {
      setMessage({ type: 'error', text: 'Username can only contain letters, numbers, underscores, and hyphens' });
      return false;
    }

    if (profileData.new_password && profileData.new_password.length < 6) {
      setMessage({ type: 'error', text: 'New password must be at least 6 characters' });
      return false;
    }

    if (profileData.new_password && profileData.new_password !== profileData.confirm_password) {
      setMessage({ type: 'error', text: 'New passwords do not match' });
      return false;
    }

    if (profileData.new_password && !profileData.current_password) {
      setMessage({ type: 'error', text: 'Current password is required to change password' });
      return false;
    }

    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);

    if (!validateForm()) return;

    setIsSubmitting(true);
    try {
      const updateData: any = {
        email: profileData.email,
        username: profileData.username,
        first_name: profileData.first_name,
        last_name: profileData.last_name
      };

      if (profileData.new_password && profileData.current_password) {
        updateData.current_password = profileData.current_password;
        updateData.new_password = profileData.new_password;
      }

      const response = await apiClient.put('/api/auth/profile', updateData, token);

      if (response.status === 'success') {
        setMessage({ type: 'success', text: 'Profile updated successfully' });
        setProfileData(prev => ({ ...prev, current_password: '', new_password: '', confirm_password: '' }));
        setEmailChanged(false);
        
        if (emailChanged) {
          setMessage({ 
            type: 'success', 
            text: 'Profile updated successfully. Please check your email for verification if you changed your email address.' 
          });
        }
      }
    } catch (error: any) {
      setMessage({ 
        type: 'error', 
        text: error.response?.data?.detail || 'Failed to update profile' 
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const savePreferences = async () => {
    if (!token || !user) return;
    
    setIsLoading(true);
    try {
      const response = await apiClient.put('/api/auth/preferences', preferences, token);
      
      if (response.status === 'success') {
        addNotification({
          type: 'system',
          title: 'Preferences Saved',
          message: 'Your preferences have been updated successfully',
          priority: 'medium'
        });
        
        localStorage.setItem('app_theme', appPreferences.theme);
        localStorage.setItem('default_sport', appPreferences.default_sport);

        await refreshUser();
      }
    } catch (error) {
      console.error('Error saving preferences:', error);
      addNotification({
        type: 'system',
        title: 'Error',
        message: 'Failed to save preferences. Please try again.',
        priority: 'high'
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleAvatarUpload = async (file: File) => {
    if (!file || !token) return;

    setIsUploadingAvatar(true);
    try {
      const reader = new FileReader();
      reader.onload = async (e) => {
        const imageData = e.target?.result as string;
        
        try {
          const response = await apiClient.post('/api/auth/avatar', {
            image_data: imageData
          }, token);

          if (response.status === 'success') {
            setAvatarUrl(response.avatar_url);
            // Force refresh user data to update avatar display
            refreshUser();
            // Force refresh both avatar components
            avatarRef.current?.refresh();
            setMessage({ type: 'success', text: 'Avatar updated successfully' });
          }
        } catch (error: any) {
          setMessage({ 
            type: 'error', 
            text: error.response?.data?.detail || 'Failed to upload avatar' 
          });
        } finally {
          setIsUploadingAvatar(false);
        }
      };
      
      reader.readAsDataURL(file);
    } catch (error) {
      setIsUploadingAvatar(false);
      setMessage({ type: 'error', text: 'Failed to read file' });
    }
  };

  const handleDeleteAvatar = async () => {
    if (!token) return;

    try {
      const response = await apiClient.delete('/api/auth/avatar', token);

      if (response.status === 'success') {
        setAvatarUrl('');
        setMessage({ type: 'success', text: 'Avatar deleted successfully' });
      }
    } catch (error: any) {
      setMessage({ 
        type: 'error', 
        text: error.response?.data?.detail || 'Failed to delete avatar' 
      });
    }
  };

  const setup2FA = async () => {
    if (!token) return;
    
    try {
      const response = await apiClient.post('/api/auth/2fa/setup', {}, token);
      
      if (response.status === 'success') {
        setQrCodeData(response.qr_code);
        setSecretKey(response.secret_key);
        setBackupCodes(response.backup_codes || []);
        setSetupStep(1);
        setShow2FAModal(true);
        setTwoFAStatus(prev => ({ ...prev, setup_in_progress: true }));
      }
    } catch (error) {
      console.error('Error setting up 2FA:', error);
      addNotification({
        type: 'system',
        title: 'Error',
        message: 'Failed to setup 2FA. Please try again.',
        priority: 'high'
      });
    }
  };

  const verify2FASetup = async () => {
    if (!token || !verificationCode) return;
    
    try {
      const response = await apiClient.post('/api/auth/2fa/enable', {
        token: verificationCode
      }, token);
      
      if (response.status === 'success') {
        setSetupStep(3);
        setTwoFAStatus(prev => ({ 
          ...prev, 
          enabled: true, 
          backup_codes_remaining: backupCodes.length,
          setup_in_progress: false 
        }));
        addNotification({
          type: 'system',
          title: '2FA Enabled',
          message: 'Two-factor authentication has been successfully enabled',
          priority: 'medium'
        });
      }
    } catch (error) {
      console.error('Error verifying 2FA:', error);
      addNotification({
        type: 'system',
        title: 'Invalid Code',
        message: 'Please check your code and try again',
        priority: 'high'
      });
    }
  };

  const disable2FA = async () => {
    if (!token) return;
    
    try {
      const response = await apiClient.post('/api/auth/2fa/disable', {}, token);
      
      if (response.status === 'success') {
        setTwoFAStatus({
          enabled: false,
          backup_codes_remaining: 0,
          setup_in_progress: false
        });
        addNotification({
          type: 'system',
          title: '2FA Disabled',
          message: 'Two-factor authentication has been disabled',
          priority: 'medium'
        });
      }
    } catch (error) {
      console.error('Error disabling 2FA:', error);
      addNotification({
        type: 'system',
        title: 'Error',
        message: 'Failed to disable 2FA. Please try again.',
        priority: 'high'
      });
    }
  };

  const copyBackupCodes = () => {
    const codesText = backupCodes.join('\n');
    navigator.clipboard.writeText(codesText).then(() => {
      setCopiedCodes(true);
      setTimeout(() => setCopiedCodes(false), 2000);
    });
  };

  if (loading) {
    return (
      <Layout>
        <div className="min-h-screen flex items-center justify-center">
          <div className="text-lg">Loading...</div>
        </div>
      </Layout>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <Layout>
      <style jsx>{`
        .sport-selected {
          border-color: #9333ea !important;
          background-color: #f3f4f6 !important;
          color: #9333ea !important;
        }
        .sport-unselected {
          border-color: #d1d5db !important;
          background-color: #ffffff !important;
          color: #374151 !important;
        }
      `}</style>
      <div className="min-h-screen bg-gray-50">
        {/* Header */}
        <div className="bg-white border-b border-gray-200">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="py-8">
              <div className="flex items-center space-x-3">
                <div className="p-3 bg-[#A855F7]/10 rounded-xl">
                  <UserCircle className="w-8 h-8 text-[#A855F7]" />
                </div>
                <div>
                  <h1 className="text-3xl font-bold text-gray-900">Profile</h1>
                  <p className="text-gray-600 mt-1">Manage your account, preferences, and security settings</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="grid grid-cols-1 lg:grid-cols-5 xl:grid-cols-4 gap-8">
            
            {/* Account Info Sidebar */}
            <div className="lg:col-span-2 xl:col-span-1">
              <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 h-auto">
                {/* User Info */}
                <div className="text-center mb-6">
                  <Avatar 
                    user={user} 
                    size="xl" 
                    className="mx-auto mb-4 min-w-[80px] min-h-[80px] lg:min-w-[96px] lg:min-h-[96px] flex-shrink-0"
                  />
                  <h3 className="font-semibold text-gray-900">{user?.first_name} {user?.last_name}</h3>
                  <p className="text-sm text-gray-600 capitalize">{user?.subscription_tier} Member</p>
                </div>

                <div className="pt-4 border-t border-gray-100">
                  <h3 className="text-sm font-medium text-gray-900 mb-3">Account Info</h3>
                  <div className="space-y-2 text-sm text-gray-600">
                    <div className="flex justify-between">
                      <span>Plan</span>
                      <span className={`font-medium capitalize ${
                        user?.subscription_tier === 'free' ? 'text-gray-600' :
                        user?.subscription_tier === 'pro' ? 'text-blue-600' : 'text-purple-600'
                      }`}>
                        {user?.subscription_tier}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>2FA</span>
                      <span className={`font-medium ${twoFAStatus.enabled ? 'text-green-600' : 'text-gray-400'}`}>
                        {twoFAStatus.enabled ? 'Enabled' : 'Disabled'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Status</span>
                      <span className="font-medium text-green-600">
                        {user?.is_verified ? 'Verified' : 'Unverified'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Profile Content */}
            <div className="lg:col-span-3 xl:col-span-3">
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">

              {/* Avatar Card */}
              <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 h-auto">
                <div className="flex items-center space-x-3 mb-6">
                  <Camera className="w-6 h-6 text-[#A855F7]" />
                  <h2 className="text-xl font-semibold text-gray-900">Profile Picture</h2>
                </div>

                <div className="space-y-6">
                  <div className="flex justify-center">
                    <div className="relative">
                      <Avatar
                        ref={avatarRef}
                        user={user}
                        size="xl"
                        key={`avatar-${user?.id}-${avatarUrl}`}
                      />
                      {isUploadingAvatar && (
                        <div className="absolute inset-0 bg-black bg-opacity-50 rounded-full flex items-center justify-center">
                          <div className="w-6 h-6 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="text-center space-y-4">
                    <div>
                      <h3 className="font-medium text-gray-900 mb-2">
                        {user?.first_name} {user?.last_name}
                      </h3>
                      <p className="text-sm text-gray-600">
                        Upload a new profile picture or remove the current one
                      </p>
                    </div>

                    <div className="flex flex-col sm:flex-row justify-center gap-3">
                      <label className="px-4 py-2 bg-[#A855F7] text-white rounded-lg hover:bg-[#9333EA] transition-colors cursor-pointer flex items-center justify-center space-x-2 whitespace-nowrap">
                        <Upload className="w-4 h-4" />
                        <span>Upload New</span>
                        <input
                          type="file"
                          accept="image/*"
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) handleAvatarUpload(file);
                          }}
                          className="hidden"
                        />
                      </label>

                      {avatarUrl && (
                        <button
                          onClick={handleDeleteAvatar}
                          className="px-4 py-2 border border-gray-200 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors flex items-center justify-center space-x-2 whitespace-nowrap"
                        >
                          <Trash2 className="w-4 h-4" />
                          <span>Remove</span>
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* Personal Information Card */}
              <div className="xl:col-span-2 bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
                <div className="flex items-center space-x-3 mb-4">
                  <User className="w-6 h-6 text-[#A855F7]" />
                  <h2 className="text-xl font-semibold text-gray-900">Personal Information</h2>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4">
                  {/* Message */}
                  {message && (
                    <div className={`p-4 rounded-xl border ${
                      message.type === 'success' 
                        ? 'border-green-200 bg-green-50 text-green-800' 
                        : 'border-red-200 bg-red-50 text-red-800'
                    }`}>
                      <div className="flex items-center space-x-2">
                        {message.type === 'success' ? 
                          <Check className="w-5 h-5" /> : 
                          <AlertCircle className="w-5 h-5" />
                        }
                        <span className="text-sm">{message.text}</span>
                      </div>
                    </div>
                  )}

                  {/* Basic Info */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-900 mb-3">
                        First Name *
                      </label>
                      <input
                        type="text"
                        value={profileData.first_name}
                        onChange={(e) => handleInputChange('first_name', e.target.value)}
                        className="w-full px-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[#A855F7] focus:border-transparent"
                        required
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-900 mb-3">
                        Last Name
                      </label>
                      <input
                        type="text"
                        value={profileData.last_name}
                        onChange={(e) => handleInputChange('last_name', e.target.value)}
                        className="w-full px-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[#A855F7] focus:border-transparent"
                      />
                    </div>
                  </div>

                  {/* Email */}
                  <div>
                    <label className="block text-sm font-medium text-gray-900 mb-3">
                      Email Address *
                    </label>
                    <div className="relative">
                      <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                      <input
                        type="email"
                        value={profileData.email}
                        onChange={(e) => handleInputChange('email', e.target.value)}
                        className="w-full pl-12 pr-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[#A855F7] focus:border-transparent"
                        required
                      />
                    </div>
                    {emailChanged && (
                      <p className="text-sm text-amber-600 mt-2 flex items-center space-x-1">
                        <AlertCircle className="w-4 h-4" />
                        <span>Email verification will be required after saving</span>
                      </p>
                    )}
                  </div>

                  {/* Username */}
                  <div>
                    <label className="block text-sm font-medium text-gray-900 mb-3">
                      Username *
                    </label>
                    <div className="relative">
                      <User className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                      <input
                        type="text"
                        value={profileData.username}
                        onChange={(e) => handleInputChange('username', e.target.value)}
                        className="w-full pl-12 pr-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[#A855F7] focus:border-transparent"
                        placeholder="john_doe"
                        required
                      />
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      3+ characters, letters, numbers, underscores and hyphens only
                    </p>
                  </div>

                  {/* Password Section */}
                  <div className="pt-6 border-t border-gray-100">
                    <h3 className="text-lg font-medium text-gray-900 mb-4 flex items-center space-x-2">
                      <Lock className="w-5 h-5" />
                      <span>Change Password</span>
                    </h3>
                    <p className="text-sm text-gray-600 mb-6">
                      Leave blank to keep your current password
                    </p>

                    <div className="space-y-4">
                      {/* Current Password */}
                      <div>
                        <label className="block text-sm font-medium text-gray-900 mb-3">
                          Current Password
                        </label>
                        <div className="relative">
                          <input
                            type={showCurrentPassword ? 'text' : 'password'}
                            value={profileData.current_password}
                            onChange={(e) => handleInputChange('current_password', e.target.value)}
                            className="w-full px-4 py-3 pr-12 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[#A855F7] focus:border-transparent"
                          />
                          <button
                            type="button"
                            onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                            className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
                          >
                            {showCurrentPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                          </button>
                        </div>
                      </div>

                      {/* New Password */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                          <label className="block text-sm font-medium text-gray-900 mb-3">
                            New Password
                          </label>
                          <div className="relative">
                            <input
                              type={showNewPassword ? 'text' : 'password'}
                              value={profileData.new_password}
                              onChange={(e) => handleInputChange('new_password', e.target.value)}
                              className="w-full px-4 py-3 pr-12 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[#A855F7] focus:border-transparent"
                              minLength={6}
                            />
                            <button
                              type="button"
                              onClick={() => setShowNewPassword(!showNewPassword)}
                              className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
                            >
                              {showNewPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                            </button>
                          </div>
                        </div>

                        <div>
                          <label className="block text-sm font-medium text-gray-900 mb-3">
                            Confirm New Password
                          </label>
                          <div className="relative">
                            <input
                              type={showConfirmPassword ? 'text' : 'password'}
                              value={profileData.confirm_password}
                              onChange={(e) => handleInputChange('confirm_password', e.target.value)}
                              className="w-full px-4 py-3 pr-12 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[#A855F7] focus:border-transparent"
                            />
                            <button
                              type="button"
                              onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                              className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
                            >
                              {showConfirmPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Save Button */}
                  <div className="flex justify-end pt-6">
                    <button
                      type="submit"
                      disabled={isSubmitting}
                      className="px-8 py-3 bg-[#A855F7] text-white rounded-xl hover:bg-[#9333EA] transition-colors disabled:opacity-50 flex items-center space-x-2 font-medium"
                    >
                      <Save className="w-5 h-5" />
                      <span>{isSubmitting ? 'Saving...' : 'Save Changes'}</span>
                    </button>
                  </div>
                </form>
              </div>

              {/* Preferences Card */}
              <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 h-auto">
                <div className="flex items-center space-x-3 mb-4">
                  <Heart className="w-6 h-6 text-[#A855F7]" />
                  <h2 className="text-xl font-semibold text-gray-900">Preferences</h2>
                </div>

                <div className="space-y-4">
                  {/* Preferred Sports */}
                  <div>
                    <label className="block text-sm font-medium text-gray-900 mb-3">
                      Preferred Sports
                    </label>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                      {sportsList
                        .filter(sport => ['baseball_mlb', 'basketball_nba', 'americanfootball_nfl', 'icehockey_nhl', 'basketball_ncaab', 'americanfootball_ncaaf', 'basketball_wnba', 'soccer_epl'].includes(sport.key))
                        .map((sport) => (
                        <label key={sport.key} className="relative flex items-center">
                          <input
                            type="checkbox"
                            checked={preferences.preferred_sports.includes(sport.key) || preferences.preferred_sports.includes(sport.title)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setPreferences(prev => ({
                                  ...prev,
                                  preferred_sports: [...prev.preferred_sports.filter(s => s !== sport.title), sport.key]
                                }));
                              } else {
                                setPreferences(prev => ({
                                  ...prev,
                                  preferred_sports: prev.preferred_sports.filter(s => s !== sport.key && s !== sport.title)
                                }));
                              }
                            }}
                            className="sr-only"
                          />
                          <div 
                            className={`flex-1 px-4 py-3 rounded-xl border-2 transition-all cursor-pointer ${
                              preferences.preferred_sports.includes(sport.key) || preferences.preferred_sports.includes(sport.title)
                                ? 'sport-selected' : 'sport-unselected'
                            }`}
                          >
                            <span className="font-medium text-sm">{sport.title}</span>
                          </div>
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* App Preferences */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-900 mb-3">
                        Default Sport
                      </label>
                      <select
                        value={appPreferences.default_sport}
                        onChange={(e) => setAppPreferences(prev => ({ ...prev, default_sport: e.target.value }))}
                        className="w-full px-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[#A855F7] focus:border-transparent"
                      >
                        {sportsList
                          .filter(sport => ['baseball_mlb', 'basketball_nba', 'americanfootball_nfl', 'icehockey_nhl', 'basketball_ncaab', 'americanfootball_ncaaf', 'basketball_wnba', 'soccer_epl'].includes(sport.key))
                          .map((sport) => (
                          <option key={sport.key} value={sport.key}>
                            {sport.title}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-900 mb-3">
                        Theme
                      </label>
                      <select
                        value={appPreferences.theme}
                        onChange={(e) => setAppPreferences(prev => ({ ...prev, theme: e.target.value }))}
                        className="w-full px-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-[#A855F7] focus:border-transparent"
                      >
                        <option value="light">Light</option>
                        <option value="dark">Dark</option>
                        <option value="auto">Auto</option>
                      </select>
                    </div>
                  </div>
                </div>
              </div>

              {/* Notifications Card */}
              <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 h-auto">
                <div className="flex items-center space-x-3 mb-4">
                  <Bell className="w-6 h-6 text-[#A855F7]" />
                  <h2 className="text-xl font-semibold text-gray-900">Notifications</h2>
                </div>

                <div className="space-y-4">
                  {/* Notification Types */}
                  <div className="space-y-4">
                    {Object.entries({
                      bet_updates: 'Bet Updates',
                      ai_predictions: 'AI Predictions',
                      game_alerts: 'Game Alerts',
                      login_alerts: 'Login Alerts'
                    }).map(([key, label]) => (
                      <div key={key} className="flex items-center justify-between p-4 rounded-xl border border-gray-100">
                        <div>
                          <div className="font-medium text-gray-900">{label}</div>
                          <div className="text-sm text-gray-600">
                            {key === 'bet_updates' && 'Get notified when your bets win or lose'}
                            {key === 'ai_predictions' && 'Receive new AI prediction alerts'}
                            {key === 'game_alerts' && 'Game start and score notifications'}
                            {key === 'login_alerts' && 'Security notifications for account access'}
                          </div>
                        </div>
                        <label className="relative inline-flex items-center cursor-pointer">
                          <input
                            type="checkbox"
                            checked={preferences.notification_settings[key as keyof typeof preferences.notification_settings]}
                            onChange={(e) => setPreferences(prev => ({
                              ...prev,
                              notification_settings: {
                                ...prev.notification_settings,
                                [key]: e.target.checked
                              }
                            }))}
                            className="sr-only"
                          />
                          <div className={`w-11 h-6 rounded-full transition-colors ${
                            preferences.notification_settings[key as keyof typeof preferences.notification_settings]
                              ? 'bg-[#A855F7]'
                              : 'bg-gray-200'
                          }`}>
                            <div className={`w-5 h-5 bg-white rounded-full shadow-md transform transition-transform ${
                              preferences.notification_settings[key as keyof typeof preferences.notification_settings]
                                ? 'translate-x-5'
                                : 'translate-x-0.5'
                            } mt-0.5`}></div>
                          </div>
                        </label>
                      </div>
                    ))}
                  </div>

                  {/* Delivery Methods */}
                  <div className="pt-6 border-t border-gray-100">
                    <h3 className="font-medium text-gray-900 mb-4">Delivery Methods</h3>
                    <div className="space-y-3">
                      {Object.entries({
                        email: 'Email Notifications',
                        push: 'Push Notifications'
                      }).map(([key, label]) => (
                        <div key={key} className="flex items-center justify-between">
                          <span className="text-gray-700">{label}</span>
                          <label className="relative inline-flex items-center cursor-pointer">
                            <input
                              type="checkbox"
                              checked={preferences.notification_settings[key as keyof typeof preferences.notification_settings]}
                              onChange={(e) => setPreferences(prev => ({
                                ...prev,
                                notification_settings: {
                                  ...prev.notification_settings,
                                  [key]: e.target.checked
                                }
                              }))}
                              className="sr-only"
                            />
                            <div className={`w-11 h-6 rounded-full transition-colors ${
                              preferences.notification_settings[key as keyof typeof preferences.notification_settings]
                                ? 'bg-[#A855F7]'
                                : 'bg-gray-200'
                            }`}>
                              <div className={`w-5 h-5 bg-white rounded-full shadow-md transform transition-transform ${
                                preferences.notification_settings[key as keyof typeof preferences.notification_settings]
                                  ? 'translate-x-5'
                                  : 'translate-x-0.5'
                              } mt-0.5`}></div>
                            </div>
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Security Card */}
              <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 h-auto">
                <div className="flex items-center space-x-3 mb-4">
                  <Shield className="w-6 h-6 text-[#A855F7]" />
                  <h2 className="text-xl font-semibold text-gray-900">Security</h2>
                </div>

                <div className="space-y-4">
                  {/* 2FA Section */}
                  <div className="p-4 rounded-xl border border-gray-100">
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <h3 className="font-medium text-gray-900">Two-Factor Authentication</h3>
                        <p className="text-sm text-gray-600 mt-1">
                          Add an extra layer of security to your account
                        </p>
                      </div>
                      <div className={`px-3 py-1 rounded-full text-xs font-medium ${
                        twoFAStatus.enabled 
                          ? 'bg-green-100 text-green-800' 
                          : 'bg-gray-100 text-gray-600'
                      }`}>
                        {twoFAStatus.enabled ? 'Enabled' : 'Disabled'}
                      </div>
                    </div>

                    {twoFAStatus.enabled && (
                      <div className="mb-4 p-3 bg-green-50 rounded-lg">
                        <p className="text-sm text-green-800">
                          <strong>{twoFAStatus.backup_codes_remaining}</strong> backup codes remaining
                        </p>
                      </div>
                    )}

                    <div className="flex space-x-3">
                      {!twoFAStatus.enabled ? (
                        <button
                          onClick={setup2FA}
                          className="px-4 py-2 bg-[#A855F7] text-white rounded-lg hover:bg-[#9333EA] transition-colors"
                        >
                          Enable 2FA
                        </button>
                      ) : (
                        <button
                          onClick={disable2FA}
                          className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
                        >
                          Disable 2FA
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Session Info */}
                  <div className="p-4 rounded-xl border border-gray-100">
                    <h3 className="font-medium text-gray-900 mb-2">Active Session</h3>
                    <p className="text-sm text-gray-600 mb-4">
                      You are currently signed in on this device
                    </p>
                    <DetailedWebSocketStatus />
                  </div>
                </div>
              </div>

              {/* Developer Tools Card - Admin Only */}
              {user?.is_admin && (
                <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 h-auto">
                  <div className="flex items-center space-x-3 mb-4">
                    <TestTube className="w-6 h-6 text-[#A855F7]" />
                    <h2 className="text-xl font-semibold text-gray-900">Developer Tools</h2>
                  </div>

                  <div className="space-y-6">
                    <p className="text-sm text-gray-600">
                      Test notification system functionality
                    </p>

                    <div className="grid grid-cols-2 gap-2">
                      {[
                        { type: 'bet_won', label: 'Bet Won', color: 'bg-green-600' },
                        { type: 'odds_change', label: 'Odds Change', color: 'bg-blue-600' },
                        { type: 'prediction', label: 'Prediction', color: 'bg-purple-600' },
                        { type: 'achievement', label: 'Achievement', color: 'bg-yellow-600' }
                      ].map(({ type, label, color }) => (
                        <button
                          key={type}
                          onClick={() => testNotification(type as any)}
                          className={`px-2 py-2 ${color} text-white rounded-lg hover:opacity-90 transition-opacity text-xs font-medium text-center`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              </div>

              {/* Save Button */}
              <div className="flex justify-end mt-6">
                <button
                  onClick={savePreferences}
                  disabled={isLoading}
                  className="px-8 py-3 bg-[#A855F7] text-white rounded-xl hover:bg-[#9333EA] transition-colors disabled:opacity-50 flex items-center space-x-2 font-medium"
                >
                  <Save className="w-5 h-5" />
                  <span>{isLoading ? 'Saving...' : 'Save All Changes'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* 2FA Setup Modal */}
        {show2FAModal && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-2xl max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto">
              {setupStep === 1 && (
                <>
                  <div className="text-center mb-6">
                    <QrCode className="w-12 h-12 text-[#A855F7] mx-auto mb-4" />
                    <h3 className="text-xl font-semibold text-gray-900">Setup 2FA</h3>
                    <p className="text-gray-600 mt-2">
                      Scan this QR code with your authenticator app
                    </p>
                  </div>
                  
                  {qrCodeData && (
                    <div className="text-center mb-6">
                      <img 
                        src={qrCodeData} 
                        alt="2FA QR Code" 
                        className="mx-auto border border-gray-200 rounded-lg"
                      />
                      <p className="text-xs text-gray-500 mt-2">
                        Manual entry: {secretKey}
                      </p>
                    </div>
                  )}
                  
                  <button
                    onClick={() => setSetupStep(2)}
                    className="w-full py-3 bg-[#A855F7] text-white rounded-xl hover:bg-[#9333EA] transition-colors"
                  >
                    I've Scanned the QR Code
                  </button>
                </>
              )}

              {setupStep === 2 && (
                <>
                  <div className="text-center mb-6">
                    <Smartphone className="w-12 h-12 text-[#A855F7] mx-auto mb-4" />
                    <h3 className="text-xl font-semibold text-gray-900">Verify Setup</h3>
                    <p className="text-gray-600 mt-2">
                      Enter the 6-digit code from your authenticator app
                    </p>
                  </div>
                  
                  <div className="mb-6">
                    <input
                      type="text"
                      value={verificationCode}
                      onChange={(e) => setVerificationCode(e.target.value)}
                      placeholder="000000"
                      className="w-full px-4 py-3 border border-gray-200 rounded-xl text-center text-lg font-mono tracking-widest focus:ring-2 focus:ring-[#A855F7] focus:border-transparent"
                      maxLength={6}
                    />
                  </div>
                  
                  <div className="flex space-x-3">
                    <button
                      onClick={() => setSetupStep(1)}
                      className="flex-1 py-3 border border-gray-200 text-gray-700 rounded-xl hover:bg-gray-50 transition-colors"
                    >
                      Back
                    </button>
                    <button
                      onClick={verify2FASetup}
                      disabled={verificationCode.length !== 6}
                      className="flex-1 py-3 bg-[#A855F7] text-white rounded-xl hover:bg-[#9333EA] transition-colors disabled:opacity-50"
                    >
                      Verify
                    </button>
                  </div>
                </>
              )}

              {setupStep === 3 && (
                <>
                  <div className="text-center mb-6">
                    <Check className="w-12 h-12 text-green-600 mx-auto mb-4" />
                    <h3 className="text-xl font-semibold text-gray-900">2FA Enabled!</h3>
                    <p className="text-gray-600 mt-2">
                      Save these backup codes in a safe place
                    </p>
                  </div>
                  
                  <div className="mb-6 p-4 bg-gray-50 rounded-xl">
                    <div className="grid grid-cols-2 gap-2 text-sm font-mono">
                      {backupCodes.map((code, index) => (
                        <div key={index} className="text-center py-1">
                          {code}
                        </div>
                      ))}
                    </div>
                  </div>
                  
                  <div className="flex space-x-3">
                    <button
                      onClick={copyBackupCodes}
                      className="flex-1 py-3 border border-gray-200 text-gray-700 rounded-xl hover:bg-gray-50 transition-colors flex items-center justify-center space-x-2"
                    >
                      {copiedCodes ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                      <span>{copiedCodes ? 'Copied!' : 'Copy Codes'}</span>
                    </button>
                    <button
                      onClick={() => setShow2FAModal(false)}
                      className="flex-1 py-3 bg-[#A855F7] text-white rounded-xl hover:bg-[#9333EA] transition-colors"
                    >
                      Done
                    </button>
                  </div>
                </>
              )}

              <button
                onClick={() => setShow2FAModal(false)}
                className="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
              >
                <X className="w-6 h-6" />
              </button>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}