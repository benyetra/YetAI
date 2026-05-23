'use client';

import React, { useRef } from 'react';
import PageHeader from '@/components/yetai/PageHeader';
import { DetailedWebSocketStatus } from '@/components/WebSocketIndicator';
import {
  User,
  Lock,
  AlertCircle,
  Eye,
  EyeOff,
  Check,
  X,
  Camera,
  Shield,
  Heart,
  Bell,
  TestTube,
  QrCode,
  Copy,
  Smartphone,
  Crown,
  XCircle,
} from 'lucide-react';
import {
  AuthUser,
  formatMemberSince,
  planDisplayName,
  profileInitials,
  subscriptionTierLabel,
} from './profile-utils';

const PREFERRED_SPORT_KEYS = [
  'baseball_mlb',
  'basketball_nba',
  'americanfootball_nfl',
  'icehockey_nhl',
  'basketball_ncaab',
  'americanfootball_ncaaf',
  'basketball_wnba',
  'soccer_epl',
] as const;

export type ProfileFormData = {
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  current_password: string;
  new_password: string;
  confirm_password: string;
};

export type ProfilePreferences = {
  favorite_teams: string[];
  preferred_sports: string[];
  notification_settings: {
    bet_updates: boolean;
    ai_predictions: boolean;
    game_alerts: boolean;
    login_alerts: boolean;
    email: boolean;
    push: boolean;
  };
};

export type AppPreferences = {
  theme: string;
  default_sport: string;
  odds_format: string;
};

export type TwoFAStatus = {
  enabled: boolean;
  backup_codes_remaining: number;
  setup_in_progress: boolean;
};

type SportOption = { key: string; title: string };

export type ProfilePageViewProps = {
  user: AuthUser;
  avatarUrl: string;
  isUploadingAvatar: boolean;
  message: { type: 'success' | 'error'; text: string } | null;
  emailChanged: boolean;
  profileData: ProfileFormData;
  showCurrentPassword: boolean;
  showNewPassword: boolean;
  showConfirmPassword: boolean;
  isSubmitting: boolean;
  isLoading: boolean;
  sportsList: SportOption[];
  preferences: ProfilePreferences;
  appPreferences: AppPreferences;
  twoFAStatus: TwoFAStatus;
  show2FAModal: boolean;
  setupStep: number;
  qrCodeData: string;
  secretKey: string;
  backupCodes: string[];
  verificationCode: string;
  copiedCodes: boolean;
  showCancelConfirm: boolean;
  isCancelingSubscription: boolean;
  onProfileChange: (field: keyof ProfileFormData, value: string) => void;
  onTogglePassword: (field: 'current' | 'new' | 'confirm') => void;
  onPreferencesChange: (next: ProfilePreferences) => void;
  onAppPreferencesChange: (next: AppPreferences) => void;
  onAvatarUpload: (file: File) => void;
  onSaveAll: () => void;
  onCancel: () => void;
  onSetup2FA: () => void;
  onDisable2FA: () => void;
  onVerify2FA: () => void;
  onCopyBackupCodes: () => void;
  onClose2FAModal: () => void;
  on2FAStep: (step: number) => void;
  onVerificationCodeChange: (code: string) => void;
  onCancelSubscription: () => void;
  onShowCancelConfirm: (show: boolean) => void;
  onTestNotification: (type: 'bet_won' | 'odds_change' | 'prediction' | 'achievement') => void;
};

function MessageBanner({
  message,
}: {
  message: { type: 'success' | 'error'; text: string };
}) {
  return (
    <div
      className={`card ${message.type === 'success' ? 'border-green-500/30' : 'border-red-500/30'}`}
      style={{
        padding: '12px 16px',
        borderColor:
          message.type === 'success'
            ? 'color-mix(in oklab, var(--win) 40%, var(--border))'
            : 'color-mix(in oklab, var(--loss) 40%, var(--border))',
        background:
          message.type === 'success' ? 'var(--win-soft)' : 'var(--loss-soft)',
        color: message.type === 'success' ? 'var(--win)' : 'var(--loss)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
        {message.type === 'success' ? (
          <Check size={16} aria-hidden />
        ) : (
          <AlertCircle size={16} aria-hidden />
        )}
        <span>{message.text}</span>
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div
      className="card"
      style={{
        padding: '14px 16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
      }}
    >
      <div>
        <div style={{ fontSize: 13.5, fontWeight: 500 }}>{label}</div>
        <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>{hint}</div>
      </div>
      <label className="relative inline-flex items-center cursor-pointer">
        <input
          type="checkbox"
          className="sr-only"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span
          className={`w-11 h-6 rounded-full transition-colors ${checked ? 'btn-primary' : ''}`}
          style={{
            display: 'inline-block',
            background: checked ? undefined : 'var(--surface-3)',
          }}
        >
          <span
            className="block w-5 h-5 bg-white rounded-full shadow-md transition-transform"
            style={{
              marginTop: 2,
              transform: checked ? 'translateX(22px)' : 'translateX(2px)',
            }}
          />
        </span>
      </label>
    </div>
  );
}

export default function ProfilePageView(props: ProfilePageViewProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const {
    user,
    avatarUrl,
    isUploadingAvatar,
    message,
    emailChanged,
    profileData,
    showCurrentPassword,
    showNewPassword,
    showConfirmPassword,
    isSubmitting,
    isLoading,
    sportsList,
    preferences,
    appPreferences,
    twoFAStatus,
    show2FAModal,
    setupStep,
    qrCodeData,
    secretKey,
    backupCodes,
    verificationCode,
    copiedCodes,
    showCancelConfirm,
    isCancelingSubscription,
    onProfileChange,
    onTogglePassword,
    onPreferencesChange,
    onAppPreferencesChange,
    onAvatarUpload,
    onSaveAll,
    onCancel,
    onSetup2FA,
    onDisable2FA,
    onVerify2FA,
    onCopyBackupCodes,
    onClose2FAModal,
    on2FAStep,
    onVerificationCodeChange,
    onCancelSubscription,
    onShowCancelConfirm,
    onTestNotification,
  } = props;

  const filteredSports = sportsList.filter((sport) =>
    (PREFERRED_SPORT_KEYS as readonly string[]).includes(sport.key)
  );

  const displayAvatar = avatarUrl || user.avatar_url;
  const busy = isSubmitting || isLoading;

  return (
    <>
      <PageHeader
        title="Profile"
        subtitle="Manage your account, preferences, and security settings"
      />

      <div className="profile-grid">
        <aside className="profile-side">
          <div className="card profile-id-card">
            <div className="profile-avatar" style={{ position: 'relative' }} aria-hidden>
              {displayAvatar ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={displayAvatar} alt="" />
              ) : (
                profileInitials(user)
              )}
              {isUploadingAvatar ? (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    background: 'rgba(0,0,0,0.45)',
                    display: 'grid',
                    placeItems: 'center',
                    borderRadius: 16,
                  }}
                >
                  <span className="w-6 h-6 border-2 border-white border-t-transparent rounded-full animate-spin" />
                </div>
              ) : null}
            </div>
            <div className="profile-name">
              {[user.first_name, user.last_name].filter(Boolean).join(' ') || user.username}
            </div>
            <span className="profile-tier">
              <Crown size={11} aria-hidden />
              {subscriptionTierLabel(user.subscription_tier)}
            </span>
            <div className="profile-meta-list">
              <div className="pmrow">
                <span className="pml">Plan</span>
                <span className="pmv">{planDisplayName(user.subscription_tier)}</span>
              </div>
              <div className="pmrow">
                <span className="pml">2FA</span>
                <span
                  className="pmv"
                  style={{ color: twoFAStatus.enabled ? 'var(--win)' : 'var(--text-2)' }}
                >
                  {twoFAStatus.enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
              <div className="pmrow">
                <span className="pml">Status</span>
                <span className="pmv" style={{ color: 'var(--win)' }}>
                  {user.is_verified ? 'Verified' : 'Unverified'}
                </span>
              </div>
              <div className="pmrow">
                <span className="pml">Member since</span>
                <span className="pmv">{formatMemberSince(user)}</span>
              </div>
            </div>
          </div>
          <button
            type="button"
            className="btn btn-block"
            style={{ padding: 10 }}
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploadingAvatar}
          >
            <Camera size={13} aria-hidden />
            Change photo
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/jpg,image/gif,image/webp"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onAvatarUpload(file);
              e.target.value = '';
            }}
          />
        </aside>

        <div className="profile-main">
          {message ? <MessageBanner message={message} /> : null}

          <div className="card">
            <div className="form-section-head">
              <User size={14} style={{ color: 'var(--text-3)' }} aria-hidden />
              <h3>Personal information</h3>
            </div>
            <div className="form-section">
              <div className="form-row">
                <div>
                  <label className="field-label" htmlFor="profile-first-name">
                    First name
                  </label>
                  <input
                    id="profile-first-name"
                    className="input"
                    value={profileData.first_name}
                    onChange={(e) => onProfileChange('first_name', e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label className="field-label" htmlFor="profile-last-name">
                    Last name
                  </label>
                  <input
                    id="profile-last-name"
                    className="input"
                    value={profileData.last_name}
                    onChange={(e) => onProfileChange('last_name', e.target.value)}
                  />
                </div>
              </div>
              <div>
                <label className="field-label" htmlFor="profile-email">
                  Email
                </label>
                <input
                  id="profile-email"
                  type="email"
                  className="input"
                  value={profileData.email}
                  onChange={(e) => onProfileChange('email', e.target.value)}
                  required
                />
                {emailChanged ? (
                  <p className="field-hint" style={{ color: 'var(--gold)' }}>
                    Email verification will be required after saving
                  </p>
                ) : null}
              </div>
              <div>
                <label className="field-label" htmlFor="profile-username">
                  Username
                </label>
                <input
                  id="profile-username"
                  className="input"
                  value={profileData.username}
                  onChange={(e) => onProfileChange('username', e.target.value)}
                  required
                />
                <p className="field-hint">
                  3+ characters · letters, numbers, underscores and hyphens only
                </p>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="form-section-head">
              <Heart size={14} style={{ color: 'var(--text-3)' }} aria-hidden />
              <h3>Preferences</h3>
            </div>
            <div className="form-section">
              <div>
                <span className="field-label">Preferred sports</span>
                <div className="chip-row" style={{ marginTop: 4 }}>
                  {filteredSports.map((sport) => {
                    const active =
                      preferences.preferred_sports.includes(sport.key) ||
                      preferences.preferred_sports.includes(sport.title);
                    return (
                      <button
                        key={sport.key}
                        type="button"
                        className={`chip ${active ? 'active' : ''}`}
                        onClick={() => {
                          if (active) {
                            onPreferencesChange({
                              ...preferences,
                              preferred_sports: preferences.preferred_sports.filter(
                                (s) => s !== sport.key && s !== sport.title
                              ),
                            });
                          } else {
                            onPreferencesChange({
                              ...preferences,
                              preferred_sports: [
                                ...preferences.preferred_sports.filter(
                                  (s) => s !== sport.title
                                ),
                                sport.key,
                              ],
                            });
                          }
                        }}
                      >
                        {sport.title}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="form-row">
                <div>
                  <label className="field-label" htmlFor="profile-default-sport">
                    Default sport
                  </label>
                  <select
                    id="profile-default-sport"
                    className="select"
                    value={appPreferences.default_sport}
                    onChange={(e) =>
                      onAppPreferencesChange({
                        ...appPreferences,
                        default_sport: e.target.value,
                      })
                    }
                  >
                    {filteredSports.map((sport) => (
                      <option key={sport.key} value={sport.key}>
                        {sport.title}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="field-label" htmlFor="profile-odds-format">
                    Default odds format
                  </label>
                  <select
                    id="profile-odds-format"
                    className="select"
                    value={appPreferences.odds_format}
                    onChange={(e) =>
                      onAppPreferencesChange({
                        ...appPreferences,
                        odds_format: e.target.value,
                      })
                    }
                  >
                    <option value="american">American</option>
                    <option value="decimal">Decimal</option>
                    <option value="fractional">Fractional</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="field-label" htmlFor="profile-theme">
                  Theme
                </label>
                <select
                  id="profile-theme"
                  className="select"
                  value={appPreferences.theme}
                  onChange={(e) =>
                    onAppPreferencesChange({ ...appPreferences, theme: e.target.value })
                  }
                >
                  <option value="light">Light</option>
                  <option value="dark">Dark</option>
                  <option value="auto">Auto</option>
                </select>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="form-section-head">
              <Lock size={14} style={{ color: 'var(--text-3)' }} aria-hidden />
              <h3>Security</h3>
            </div>
            <div className="form-section">
              <div className="form-row">
                <div>
                  <label className="field-label" htmlFor="profile-current-password">
                    Current password
                  </label>
                  <div style={{ position: 'relative' }}>
                    <input
                      id="profile-current-password"
                      className="input"
                      type={showCurrentPassword ? 'text' : 'password'}
                      value={profileData.current_password}
                      onChange={(e) => onProfileChange('current_password', e.target.value)}
                      placeholder="••••••••"
                      style={{ paddingRight: 40 }}
                    />
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      style={{ position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)' }}
                      onClick={() => onTogglePassword('current')}
                      aria-label={showCurrentPassword ? 'Hide password' : 'Show password'}
                    >
                      {showCurrentPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
                <div aria-hidden />
              </div>
              <div className="form-row">
                <div>
                  <label className="field-label" htmlFor="profile-new-password">
                    New password
                  </label>
                  <div style={{ position: 'relative' }}>
                    <input
                      id="profile-new-password"
                      className="input"
                      type={showNewPassword ? 'text' : 'password'}
                      value={profileData.new_password}
                      onChange={(e) => onProfileChange('new_password', e.target.value)}
                      placeholder="••••••••"
                      style={{ paddingRight: 40 }}
                    />
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      style={{ position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)' }}
                      onClick={() => onTogglePassword('new')}
                      aria-label={showNewPassword ? 'Hide password' : 'Show password'}
                    >
                      {showNewPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
                <div>
                  <label className="field-label" htmlFor="profile-confirm-password">
                    Confirm new password
                  </label>
                  <div style={{ position: 'relative' }}>
                    <input
                      id="profile-confirm-password"
                      className="input"
                      type={showConfirmPassword ? 'text' : 'password'}
                      value={profileData.confirm_password}
                      onChange={(e) => onProfileChange('confirm_password', e.target.value)}
                      placeholder="••••••••"
                      style={{ paddingRight: 40 }}
                    />
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      style={{ position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)' }}
                      onClick={() => onTogglePassword('confirm')}
                      aria-label={showConfirmPassword ? 'Hide password' : 'Show password'}
                    >
                      {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
              </div>
              <p className="field-hint">Leave blank to keep your current password</p>

              <div
                style={{
                  marginTop: 8,
                  paddingTop: 16,
                  borderTop: '1px solid var(--border)',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 12,
                    marginBottom: 12,
                  }}
                >
                  <div>
                    <div style={{ fontSize: 13.5, fontWeight: 500 }}>Two-factor authentication</div>
                    <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>
                      Add an extra layer of security to your account
                    </p>
                  </div>
                  <span
                    className="badge"
                    style={{
                      background: twoFAStatus.enabled ? 'var(--win-soft)' : 'var(--surface-3)',
                      color: twoFAStatus.enabled ? 'var(--win)' : 'var(--text-2)',
                    }}
                  >
                    {twoFAStatus.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
                {twoFAStatus.enabled ? (
                  <p className="field-hint" style={{ marginBottom: 12 }}>
                    {twoFAStatus.backup_codes_remaining} backup codes remaining
                  </p>
                ) : null}
                {!twoFAStatus.enabled ? (
                  <button type="button" className="btn btn-primary btn-sm" onClick={onSetup2FA}>
                    Enable 2FA
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={{ color: 'var(--loss)', borderColor: 'color-mix(in oklab, var(--loss) 35%, var(--border))' }}
                    onClick={onDisable2FA}
                  >
                    Disable 2FA
                  </button>
                )}
              </div>

              <div style={{ paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                <div style={{ fontSize: 13.5, fontWeight: 500, marginBottom: 8 }}>Active session</div>
                <DetailedWebSocketStatus />
              </div>
            </div>
          </div>

          <div className="card">
            <div className="form-section-head">
              <Bell size={14} style={{ color: 'var(--text-3)' }} aria-hidden />
              <h3>Notifications</h3>
            </div>
            <div className="form-section" style={{ gap: 10 }}>
              {(
                [
                  ['bet_updates', 'Bet updates', 'Get notified when your bets win or lose'],
                  ['ai_predictions', 'AI predictions', 'Receive new AI prediction alerts'],
                  ['game_alerts', 'Game alerts', 'Game start and score notifications'],
                  ['login_alerts', 'Login alerts', 'Security notifications for account access'],
                ] as const
              ).map(([key, label, hint]) => (
                <ToggleRow
                  key={key}
                  label={label}
                  hint={hint}
                  checked={
                    preferences.notification_settings[
                      key as keyof typeof preferences.notification_settings
                    ]
                  }
                  onChange={(checked) =>
                    onPreferencesChange({
                      ...preferences,
                      notification_settings: {
                        ...preferences.notification_settings,
                        [key]: checked,
                      },
                    })
                  }
                />
              ))}
              <div style={{ paddingTop: 8 }}>
                <span className="field-label">Delivery methods</span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                  <ToggleRow
                    label="Email notifications"
                    hint="Send alerts to your inbox"
                    checked={preferences.notification_settings.email}
                    onChange={(checked) =>
                      onPreferencesChange({
                        ...preferences,
                        notification_settings: {
                          ...preferences.notification_settings,
                          email: checked,
                        },
                      })
                    }
                  />
                  <ToggleRow
                    label="Push notifications"
                    hint="Browser push when enabled"
                    checked={preferences.notification_settings.push}
                    onChange={(checked) =>
                      onPreferencesChange({
                        ...preferences,
                        notification_settings: {
                          ...preferences.notification_settings,
                          push: checked,
                        },
                      })
                    }
                  />
                </div>
              </div>
            </div>
          </div>

          {user.subscription_tier === 'pro' ? (
            <div className="card">
              <div className="form-section-head">
                <Crown size={14} style={{ color: 'var(--gold)' }} aria-hidden />
                <h3>Subscription</h3>
              </div>
              <div className="form-section">
                <p style={{ fontSize: 13, color: 'var(--text-2)' }}>
                  Pro access includes AI predictions, unlimited bets, and advanced analytics.
                </p>
                <div className="profile-meta-list" style={{ marginTop: 0, paddingTop: 0, borderTop: 0 }}>
                  <div className="pmrow">
                    <span className="pml">Status</span>
                    <span className="pmv" style={{ color: 'var(--win)' }}>
                      {user.subscription_status === 'canceling' ? 'Canceling' : 'Active'}
                    </span>
                  </div>
                  {user.subscription_current_period_end ? (
                    <div className="pmrow">
                      <span className="pml">
                        {user.subscription_status === 'canceling' ? 'Access until' : 'Next billing'}
                      </span>
                      <span className="pmv">
                        {new Date(user.subscription_current_period_end).toLocaleDateString()}
                      </span>
                    </div>
                  ) : null}
                </div>
                {user.subscription_status !== 'canceling' ? (
                  !showCancelConfirm ? (
                    <button
                      type="button"
                      className="btn btn-block"
                      style={{ color: 'var(--loss)' }}
                      onClick={() => onShowCancelConfirm(true)}
                    >
                      <XCircle size={14} aria-hidden />
                      Cancel subscription
                    </button>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <p className="field-hint" style={{ color: 'var(--gold)' }}>
                        You will retain access until the end of your billing period.
                      </p>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          type="button"
                          className="btn btn-primary"
                          style={{ flex: 1 }}
                          disabled={isCancelingSubscription}
                          onClick={onCancelSubscription}
                        >
                          {isCancelingSubscription ? 'Canceling…' : 'Confirm cancel'}
                        </button>
                        <button
                          type="button"
                          className="btn"
                          style={{ flex: 1 }}
                          disabled={isCancelingSubscription}
                          onClick={() => onShowCancelConfirm(false)}
                        >
                          Keep Pro
                        </button>
                      </div>
                    </div>
                  )
                ) : (
                  <p className="field-hint">
                    Subscription cancelled — Pro features remain until{' '}
                    {user.subscription_current_period_end
                      ? new Date(user.subscription_current_period_end).toLocaleDateString()
                      : 'period end'}
                    .
                  </p>
                )}
              </div>
            </div>
          ) : null}

          {user.is_admin ? (
            <div className="card">
              <div className="form-section-head">
                <TestTube size={14} style={{ color: 'var(--text-3)' }} aria-hidden />
                <h3>Developer tools</h3>
              </div>
              <p className="field-hint" style={{ marginBottom: 12 }}>
                Test notification system functionality
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
                {(
                  [
                    ['bet_won', 'Bet won'],
                    ['odds_change', 'Odds change'],
                    ['prediction', 'Prediction'],
                    ['achievement', 'Achievement'],
                  ] as const
                ).map(([type, label]) => (
                  <button
                    key={type}
                    type="button"
                    className="btn btn-sm"
                    onClick={() => onTestNotification(type)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="profile-footer">
            <button type="button" className="btn" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button type="button" className="btn btn-primary" onClick={onSaveAll} disabled={busy}>
              {busy ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </div>
      </div>

      {show2FAModal ? (
        <div
          className="fixed inset-0 flex items-center justify-center p-4 z-50"
          style={{ background: 'rgba(0,0,0,0.55)' }}
          role="dialog"
          aria-modal
          aria-labelledby="profile-2fa-title"
        >
          <div
            className="card"
            style={{ maxWidth: 480, width: '100%', padding: 24, position: 'relative' }}
          >
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              style={{ position: 'absolute', top: 12, right: 12 }}
              onClick={onClose2FAModal}
              aria-label="Close"
            >
              <X size={18} />
            </button>

            {setupStep === 1 ? (
              <>
                <div style={{ textAlign: 'center', marginBottom: 20 }}>
                  <QrCode size={40} style={{ color: 'var(--accent)', margin: '0 auto 12px' }} />
                  <h3 id="profile-2fa-title" style={{ margin: 0, fontSize: 18 }}>
                    Setup 2FA
                  </h3>
                  <p style={{ color: 'var(--text-3)', fontSize: 13, marginTop: 8 }}>
                    Scan this QR code with your authenticator app
                  </p>
                </div>
                {qrCodeData ? (
                  <div style={{ textAlign: 'center', marginBottom: 16 }}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={qrCodeData}
                      alt="2FA QR code"
                      style={{ margin: '0 auto', borderRadius: 8, border: '1px solid var(--border)' }}
                    />
                    <p className="field-hint" style={{ marginTop: 8 }}>
                      Manual entry: {secretKey}
                    </p>
                  </div>
                ) : null}
                <button type="button" className="btn btn-primary btn-block" onClick={() => on2FAStep(2)}>
                  I&apos;ve scanned the QR code
                </button>
              </>
            ) : null}

            {setupStep === 2 ? (
              <>
                <div style={{ textAlign: 'center', marginBottom: 20 }}>
                  <Smartphone size={40} style={{ color: 'var(--accent)', margin: '0 auto 12px' }} />
                  <h3 style={{ margin: 0, fontSize: 18 }}>Verify setup</h3>
                  <p style={{ color: 'var(--text-3)', fontSize: 13, marginTop: 8 }}>
                    Enter the 6-digit code from your authenticator app
                  </p>
                </div>
                <input
                  className="input mono"
                  style={{ textAlign: 'center', letterSpacing: '0.2em', marginBottom: 16 }}
                  value={verificationCode}
                  onChange={(e) => onVerificationCodeChange(e.target.value)}
                  placeholder="000000"
                  maxLength={6}
                  inputMode="numeric"
                />
                <div style={{ display: 'flex', gap: 8 }}>
                  <button type="button" className="btn" style={{ flex: 1 }} onClick={() => on2FAStep(1)}>
                    Back
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    style={{ flex: 1 }}
                    disabled={verificationCode.length !== 6}
                    onClick={onVerify2FA}
                  >
                    Verify
                  </button>
                </div>
              </>
            ) : null}

            {setupStep === 3 ? (
              <>
                <div style={{ textAlign: 'center', marginBottom: 20 }}>
                  <Check size={40} style={{ color: 'var(--win)', margin: '0 auto 12px' }} />
                  <h3 style={{ margin: 0, fontSize: 18 }}>2FA enabled</h3>
                  <p style={{ color: 'var(--text-3)', fontSize: 13, marginTop: 8 }}>
                    Save these backup codes in a safe place
                  </p>
                </div>
                <div
                  className="card"
                  style={{
                    padding: 12,
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: 6,
                    fontFamily: 'var(--mono)',
                    fontSize: 12,
                  }}
                >
                  {backupCodes.map((code) => (
                    <div key={code} style={{ textAlign: 'center' }}>
                      {code}
                    </div>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
                  <button type="button" className="btn" style={{ flex: 1 }} onClick={onCopyBackupCodes}>
                    <Copy size={14} aria-hidden />
                    {copiedCodes ? 'Copied' : 'Copy codes'}
                  </button>
                  <button type="button" className="btn btn-primary" style={{ flex: 1 }} onClick={onClose2FAModal}>
                    Done
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}
