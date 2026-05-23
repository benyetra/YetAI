'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import AppLoading from '@/components/yetai/AppLoading';
import ProfilePageView, {
  AppPreferences,
  ProfileFormData,
  ProfilePreferences,
} from '@/components/profile/ProfilePageView';
import { AuthUser } from '@/components/profile/profile-utils';
import { useAuth } from '@/components/Auth';
import { useNotifications } from '@/components/NotificationProvider';
import { sportsAPI, apiClient } from '@/lib/api';
import { AvatarRef } from '@/components/Avatar';

const EMPTY_PROFILE: ProfileFormData = {
  email: '',
  username: '',
  first_name: '',
  last_name: '',
  current_password: '',
  new_password: '',
  confirm_password: '',
};

export default function ProfilePage() {
  const { isAuthenticated, loading, user, token, refreshUser } = useAuth();
  const { addNotification } = useNotifications();
  const router = useRouter();

  const [profileData, setProfileData] = useState<ProfileFormData>(EMPTY_PROFILE);
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(
    null
  );
  const [emailChanged, setEmailChanged] = useState(false);
  const [avatarUrl, setAvatarUrl] = useState('');
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false);
  const avatarRef = useRef<AvatarRef>(null);
  const [isCancelingSubscription, setIsCancelingSubscription] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [sportsList, setSportsList] = useState<{ key: string; title: string }[]>([]);
  const [preferences, setPreferences] = useState<ProfilePreferences>({
    favorite_teams: [],
    preferred_sports: ['americanfootball_nfl'],
    notification_settings: {
      bet_updates: true,
      ai_predictions: true,
      game_alerts: false,
      login_alerts: true,
      email: true,
      push: false,
    },
  });
  const [appPreferences, setAppPreferences] = useState<AppPreferences>({
    theme: 'light',
    default_sport: 'americanfootball_nfl',
    odds_format: 'american',
  });
  const [show2FAModal, setShow2FAModal] = useState(false);
  const [twoFAStatus, setTwoFAStatus] = useState({
    enabled: false,
    backup_codes_remaining: 0,
    setup_in_progress: false,
  });
  const [qrCodeData, setQrCodeData] = useState('');
  const [secretKey, setSecretKey] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [verificationCode, setVerificationCode] = useState('');
  const [setupStep, setSetupStep] = useState(1);
  const [copiedCodes, setCopiedCodes] = useState(false);

  const normalizeSportKeys = (sports: string[]): string[] => {
    const sportKeyMap: Record<string, string> = {
      NFL: 'americanfootball_nfl',
      NBA: 'basketball_nba',
      MLB: 'baseball_mlb',
      NHL: 'icehockey_nhl',
      NCAAB: 'basketball_ncaab',
      NCAAF: 'americanfootball_ncaaf',
      WNBA: 'basketball_wnba',
      EPL: 'soccer_epl',
    };
    return sports.map((sport) => sportKeyMap[sport] || sport);
  };

  const snapshotFromUser = (authUser: typeof user): ProfileFormData => ({
    email: authUser?.email || '',
    username: authUser?.username || '',
    first_name: authUser?.first_name || '',
    last_name: authUser?.last_name || '',
    current_password: '',
    new_password: '',
    confirm_password: '',
  });

  const testNotification = (type: 'bet_won' | 'odds_change' | 'prediction' | 'achievement') => {
    const testNotifications = {
      bet_won: {
        type: 'bet_won' as const,
        title: 'Test Bet Won!',
        message: 'Your test bet just won! +$50.00',
        priority: 'high' as const,
      },
      odds_change: {
        type: 'odds_change' as const,
        title: 'Test Odds Change',
        message: 'Odds changed for Test Game (+150 → +175)',
        priority: 'medium' as const,
      },
      prediction: {
        type: 'prediction' as const,
        title: 'Test AI Prediction',
        message: 'New high-confidence test prediction available',
        priority: 'medium' as const,
      },
      achievement: {
        type: 'achievement' as const,
        title: 'Test Achievement!',
        message: 'You unlocked a test achievement badge',
        priority: 'low' as const,
      },
    };
    addNotification(testNotifications[type]);
  };

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

  useEffect(() => {
    if (isAuthenticated && token && !loading) {
      refreshUser();
    }
  }, [isAuthenticated, token, loading, refreshUser]);

  useEffect(() => {
    if (user) {
      setProfileData(snapshotFromUser(user));
      setAvatarUrl(user.avatar_url || '');
    }
  }, [user]);

  useEffect(() => {
    if (!user || !isAuthenticated) return;

    try {
      let favoriteTeams: string[] = [];
      let preferredSports = ['americanfootball_nfl'];
      let notificationSettings: ProfilePreferences['notification_settings'] = {
        bet_updates: true,
        ai_predictions: true,
        game_alerts: false,
        login_alerts: true,
        email: true,
        push: false,
      };

      if (user.favorite_teams) {
        favoriteTeams =
          typeof user.favorite_teams === 'string'
            ? JSON.parse(user.favorite_teams)
            : Array.isArray(user.favorite_teams)
              ? user.favorite_teams
              : [];
      }

      if (user.preferred_sports) {
        const rawSports =
          typeof user.preferred_sports === 'string'
            ? JSON.parse(user.preferred_sports)
            : Array.isArray(user.preferred_sports)
              ? user.preferred_sports
              : ['americanfootball_nfl'];
        preferredSports = normalizeSportKeys(rawSports);
      }

      if (user.notification_settings) {
        const parsed =
          typeof user.notification_settings === 'string'
            ? JSON.parse(user.notification_settings)
            : user.notification_settings;
        notificationSettings = { ...notificationSettings, ...parsed };
      }

      setPreferences({
        favorite_teams: favoriteTeams,
        preferred_sports: preferredSports,
        notification_settings: notificationSettings,
      });
    } catch (error) {
      console.error('Error setting up user preferences:', error);
    }

    setAppPreferences({
      theme: localStorage.getItem('app_theme') || 'light',
      default_sport: localStorage.getItem('default_sport') || 'americanfootball_nfl',
      odds_format: localStorage.getItem('odds_format') || 'american',
    });
  }, [user, isAuthenticated]);

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

  useEffect(() => {
    const load2FAStatus = async () => {
      if (!token) return;
      try {
        const response = await apiClient.get('/api/auth/2fa/status', token);
        if (response.status === 'success') {
          setTwoFAStatus({
            enabled: response.enabled || false,
            backup_codes_remaining: response.backup_codes_remaining || 0,
            setup_in_progress: response.setup_in_progress || false,
          });
        }
      } catch (error) {
        console.error('Error loading 2FA status:', error);
      }
    };
    if (isAuthenticated && token) load2FAStatus();
  }, [isAuthenticated, token]);

  const handleInputChange = (field: keyof ProfileFormData, value: string) => {
    setProfileData((prev) => ({ ...prev, [field]: value }));
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
      setMessage({
        type: 'error',
        text: 'Username can only contain letters, numbers, underscores, and hyphens',
      });
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

  const saveProfile = async (): Promise<boolean> => {
    if (!token) return false;
    const updateData: Record<string, string> = {
      email: profileData.email,
      username: profileData.username,
      first_name: profileData.first_name,
      last_name: profileData.last_name,
    };
    if (profileData.new_password && profileData.current_password) {
      updateData.current_password = profileData.current_password;
      updateData.new_password = profileData.new_password;
    }
    const response = await apiClient.put('/api/auth/profile', updateData, token);
    if (response.status !== 'success') return false;

    setProfileData((prev) => ({
      ...prev,
      current_password: '',
      new_password: '',
      confirm_password: '',
    }));
    setEmailChanged(false);
    return true;
  };

  const savePreferences = async (): Promise<boolean> => {
    if (!token || !user) return false;
    const response = await apiClient.put('/api/auth/preferences', preferences, token);
    if (response.status !== 'success') return false;

    localStorage.setItem('app_theme', appPreferences.theme);
    localStorage.setItem('default_sport', appPreferences.default_sport);
    localStorage.setItem('odds_format', appPreferences.odds_format);
    await refreshUser();
    return true;
  };

  const handleSaveAll = async () => {
    setMessage(null);
    if (!validateForm()) return;

    setIsSubmitting(true);
    setIsLoading(true);
    try {
      await saveProfile();
      await savePreferences();
      setMessage({
        type: 'success',
        text: emailChanged
          ? 'Profile updated. Check your email if you changed your address.'
          : 'Profile updated successfully',
      });
      addNotification({
        type: 'system',
        title: 'Profile saved',
        message: 'Your account settings were updated.',
        priority: 'medium',
      });
    } catch (error: unknown) {
      const detail =
        error &&
        typeof error === 'object' &&
        'response' in error &&
        (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setMessage({
        type: 'error',
        text: typeof detail === 'string' ? detail : 'Failed to update profile',
      });
    } finally {
      setIsSubmitting(false);
      setIsLoading(false);
    }
  };

  const handleCancel = () => {
    if (user) setProfileData(snapshotFromUser(user));
    setMessage(null);
    setEmailChanged(false);
  };

  const handleAvatarUpload = async (file: File) => {
    if (!file || !token) return;
    const maxSize = 5 * 1024 * 1024;
    const allowedTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/webp'];
    if (file.size > maxSize) {
      setMessage({ type: 'error', text: 'File too large. Maximum size is 5MB.' });
      return;
    }
    if (!allowedTypes.includes(file.type.toLowerCase())) {
      setMessage({
        type: 'error',
        text: 'Invalid file type. Please upload PNG, JPEG, JPG, GIF, or WEBP images.',
      });
      return;
    }

    setIsUploadingAvatar(true);
    const reader = new FileReader();
    reader.onload = async (e) => {
      const imageData = e.target?.result as string;
      try {
        const response = await apiClient.post('/api/auth/avatar', { image_data: imageData }, token);
        if (response.status === 'success') {
          setAvatarUrl(response.avatar_url);
          refreshUser();
          avatarRef.current?.refresh();
          setMessage({ type: 'success', text: 'Avatar updated successfully' });
        }
      } catch (error: unknown) {
        const detail =
          error &&
          typeof error === 'object' &&
          'response' in error &&
          (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
        setMessage({
          type: 'error',
          text: typeof detail === 'string' ? detail : 'Failed to upload avatar',
        });
      } finally {
        setIsUploadingAvatar(false);
      }
    };
    reader.onerror = () => {
      setIsUploadingAvatar(false);
      setMessage({ type: 'error', text: 'Failed to read file' });
    };
    reader.readAsDataURL(file);
  };

  const handleCancelSubscription = async () => {
    if (!token || isCancelingSubscription) return;
    setIsCancelingSubscription(true);
    try {
      const response = await apiClient.post('/api/subscription/cancel', {}, token);
      if (response.status === 'success') {
        setMessage({
          type: 'success',
          text: 'Subscription cancelled. Access continues through your billing period.',
        });
        setShowCancelConfirm(false);
        await refreshUser();
      }
    } catch (error: unknown) {
      const detail =
        error &&
        typeof error === 'object' &&
        'response' in error &&
        (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setMessage({
        type: 'error',
        text: typeof detail === 'string' ? detail : 'Failed to cancel subscription',
      });
    } finally {
      setIsCancelingSubscription(false);
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
        setTwoFAStatus((prev) => ({ ...prev, setup_in_progress: true }));
      }
    } catch (error) {
      console.error('Error setting up 2FA:', error);
      addNotification({
        type: 'system',
        title: 'Error',
        message: 'Failed to setup 2FA. Please try again.',
        priority: 'high',
      });
    }
  };

  const verify2FASetup = async () => {
    if (!token || !verificationCode) return;
    try {
      const response = await apiClient.post('/api/auth/2fa/enable', { token: verificationCode }, token);
      if (response.status === 'success') {
        setSetupStep(3);
        setTwoFAStatus({
          enabled: true,
          backup_codes_remaining: backupCodes.length,
          setup_in_progress: false,
        });
        addNotification({
          type: 'system',
          title: '2FA Enabled',
          message: 'Two-factor authentication has been successfully enabled',
          priority: 'medium',
        });
      }
    } catch (error) {
      console.error('Error verifying 2FA:', error);
      addNotification({
        type: 'system',
        title: 'Invalid Code',
        message: 'Please check your code and try again',
        priority: 'high',
      });
    }
  };

  const disable2FA = async () => {
    if (!token) return;
    try {
      const response = await apiClient.post('/api/auth/2fa/disable', {}, token);
      if (response.status === 'success') {
        setTwoFAStatus({ enabled: false, backup_codes_remaining: 0, setup_in_progress: false });
        addNotification({
          type: 'system',
          title: '2FA Disabled',
          message: 'Two-factor authentication has been disabled',
          priority: 'medium',
        });
      }
    } catch (error) {
      console.error('Error disabling 2FA:', error);
      addNotification({
        type: 'system',
        title: 'Error',
        message: 'Failed to disable 2FA. Please try again.',
        priority: 'high',
      });
    }
  };

  const copyBackupCodes = () => {
    navigator.clipboard.writeText(backupCodes.join('\n')).then(() => {
      setCopiedCodes(true);
      setTimeout(() => setCopiedCodes(false), 2000);
    });
  };

  if (loading) {
    return (
      <Layout requiresAuth>
        <AppLoading label="Loading profile…" />
      </Layout>
    );
  }

  if (!isAuthenticated || !user) {
    return null;
  }

  return (
    <Layout requiresAuth>
      <ProfilePageView
        user={user as AuthUser}
        avatarUrl={avatarUrl}
        isUploadingAvatar={isUploadingAvatar}
        message={message}
        emailChanged={emailChanged}
        profileData={profileData}
        showCurrentPassword={showCurrentPassword}
        showNewPassword={showNewPassword}
        showConfirmPassword={showConfirmPassword}
        isSubmitting={isSubmitting}
        isLoading={isLoading}
        sportsList={sportsList}
        preferences={preferences}
        appPreferences={appPreferences}
        twoFAStatus={twoFAStatus}
        show2FAModal={show2FAModal}
        setupStep={setupStep}
        qrCodeData={qrCodeData}
        secretKey={secretKey}
        backupCodes={backupCodes}
        verificationCode={verificationCode}
        copiedCodes={copiedCodes}
        showCancelConfirm={showCancelConfirm}
        isCancelingSubscription={isCancelingSubscription}
        onProfileChange={handleInputChange}
        onTogglePassword={(field) => {
          if (field === 'current') setShowCurrentPassword((v) => !v);
          if (field === 'new') setShowNewPassword((v) => !v);
          if (field === 'confirm') setShowConfirmPassword((v) => !v);
        }}
        onPreferencesChange={setPreferences}
        onAppPreferencesChange={setAppPreferences}
        onAvatarUpload={handleAvatarUpload}
        onSaveAll={handleSaveAll}
        onCancel={handleCancel}
        onSetup2FA={setup2FA}
        onDisable2FA={disable2FA}
        onVerify2FA={verify2FASetup}
        onCopyBackupCodes={copyBackupCodes}
        onClose2FAModal={() => setShow2FAModal(false)}
        on2FAStep={setSetupStep}
        onVerificationCodeChange={setVerificationCode}
        onCancelSubscription={handleCancelSubscription}
        onShowCancelConfirm={setShowCancelConfirm}
        onTestNotification={testNotification}
      />
    </Layout>
  );
}
