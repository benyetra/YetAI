'use client';

import { useState, useEffect, Suspense } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { handleUnauthorizedResponse, persistAuthToken } from '@/lib/auth-session';
import {
  isSafeReturnPath,
  resolvePostLoginRedirect,
  stashOAuthReturnPath,
} from '@/lib/auth-redirect';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/components/Auth';
import { Eye, EyeOff, Mail, Lock } from 'lucide-react';
import Link from 'next/link';
import Script from 'next/script';
import ForgotPasswordModal from '@/components/ForgotPasswordModal';
import { AuthShell } from '@/components/yetai/auth/AuthShell';
import AppLoading from '@/components/yetai/AppLoading';

declare global {
  interface Window {
    google: {
      accounts: {
        id: {
          initialize: (config: Record<string, unknown>) => void;
          prompt: () => void;
          renderButton: (element: HTMLElement, options: Record<string, unknown>) => void;
        };
      };
    };
  }
}

function LoginPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextParam = searchParams.get('next');
  const { login, isAuthenticated, loading } = useAuth();
  const [formData, setFormData] = useState({
    emailOrUsername: '',
    password: '',
    rememberMe: false,
  });
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [showForgotPasswordModal, setShowForgotPasswordModal] = useState(false);

  const postLoginPath = resolvePostLoginRedirect(nextParam);

  useEffect(() => {
    if (isAuthenticated) router.push(postLoginPath);
  }, [isAuthenticated, router, postLoginPath]);

  const handleInputChange = (field: string, value: string | boolean) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setError('');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');
    try {
      const result = await login(formData.emailOrUsername, formData.password);
      if (result.success) router.push(postLoginPath);
      else setError(result.message || 'Login failed. Please check your credentials.');
    } catch {
      setError('An unexpected error occurred. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleCallback = async (response: { credential: string }) => {
    try {
      setIsLoading(true);
      setError('');
      const result = await fetch(getApiUrl('/api/auth/google/verify'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id_token: response.credential }),
      });
      if (handleUnauthorizedResponse(result, { hadAuthToken: false })) return;
      const data = await result.json();
      if (data.status === 'success') {
        persistAuthToken(data.access_token);
        if (data.user) {
          localStorage.setItem('user_data', JSON.stringify(data.user));
        }
        // Full reload so AuthProvider picks up token + user (same as /auth/callback)
        window.location.href = postLoginPath;
        return;
      } else {
        setError(data.message || 'Google Sign-in failed');
      }
    } catch {
      setError('Google Sign-in failed. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleSignIn = async () => {
    try {
      setIsLoading(true);
      setError('');
      if (typeof window !== 'undefined' && window.google) {
        window.google.accounts.id.initialize({
          client_id: process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || 'your-google-client-id',
          callback: handleGoogleCallback,
        });
        window.google.accounts.id.prompt();
      } else {
        if (nextParam && isSafeReturnPath(nextParam)) {
          stashOAuthReturnPath(nextParam);
        }
        const response = await fetch(getApiUrl('/api/auth/google/url'));
        const data = await response.json();
        if (data.status === 'success') window.location.href = data.authorization_url;
        else setError('Failed to initialize Google Sign-in');
      }
    } catch {
      setError('Google Sign-in failed. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  if (loading) {
    return (
      <AuthShell showHero={false}>
        <AppLoading label="Loading…" />
      </AuthShell>
    );
  }

  return (
    <>
      <Script src="https://accounts.google.com/gsi/client" strategy="beforeInteractive" />
      <ForgotPasswordModal
        isOpen={showForgotPasswordModal}
        onClose={() => setShowForgotPasswordModal(false)}
      />
      <AuthShell>
        <div>
          <h1 className="type-page-title" style={{ fontSize: 26 }}>Welcome back</h1>
          <p className="dim" style={{ marginTop: 6, fontSize: 14 }}>
            Sign in to your YetAI account
          </p>
        </div>

        <button type="button" className="btn" style={{ width: '100%' }} onClick={handleGoogleSignIn} disabled={isLoading}>
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden style={{ marginRight: 8 }}>
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
          </svg>
          Sign in with Google
        </button>

        <div className="auth-divider">or email</div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {error ? <div className="alert alert-error">{error}</div> : null}

          <div className="field">
            <label htmlFor="emailOrUsername">Email or username</label>
            <div className="field-input-wrap">
              <Mail className="field-icon" size={18} />
              <input
                id="emailOrUsername"
                className="input has-toggle"
                type="text"
                autoComplete="username email"
                required
                value={formData.emailOrUsername}
                onChange={(e) => handleInputChange('emailOrUsername', e.target.value)}
                placeholder="john@example.com"
              />
            </div>
          </div>

          <div className="field">
            <label htmlFor="password">Password</label>
            <div className="field-input-wrap">
              <Lock className="field-icon" size={18} />
              <input
                id="password"
                className="input has-toggle"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                required
                value={formData.password}
                onChange={(e) => handleInputChange('password', e.target.value)}
                placeholder="••••••••"
              />
              <button
                type="button"
                className="field-toggle"
                onClick={() => setShowPassword(!showPassword)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-2)' }}>
              <input
                type="checkbox"
                checked={formData.rememberMe}
                onChange={(e) => handleInputChange('rememberMe', e.target.checked)}
              />
              Remember me
            </label>
            <button
              type="button"
              onClick={() => setShowForgotPasswordModal(true)}
              style={{ color: 'var(--accent)', fontSize: 13 }}
            >
              Forgot password?
            </button>
          </div>

          <button type="submit" className="btn btn-primary" disabled={isLoading} style={{ width: '100%' }}>
            {isLoading ? 'Signing in…' : 'Log in'}
          </button>

          <p className="dim" style={{ textAlign: 'center', fontSize: 13, margin: 0 }}>
            Not registered?{' '}
            <Link href="/signup" style={{ color: 'var(--accent)' }}>
              Create an account
            </Link>
          </p>
        </form>
      </AuthShell>
    </>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <AuthShell showHero={false}>
          <AppLoading label="Loading…" />
        </AuthShell>
      }
    >
      <LoginPageContent />
    </Suspense>
  );
}
