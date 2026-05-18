'use client';

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Lock, Eye, EyeOff, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { AuthCentered } from '@/components/yetai/auth/AuthShell';
import AppLoading from '@/components/yetai/AppLoading';

function ResetPasswordContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get('token');

  const [formData, setFormData] = useState({ newPassword: '', confirmPassword: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('No reset token provided. Please request a new password reset link.');
    }
  }, [token]);

  const validatePassword = (password: string) => {
    if (password.length < 6) return 'Password must be at least 6 characters long';
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) {
      setStatus('error');
      setMessage('Invalid reset token');
      return;
    }
    if (formData.newPassword !== formData.confirmPassword) {
      setStatus('error');
      setMessage('Passwords do not match');
      return;
    }
    const passwordError = validatePassword(formData.newPassword);
    if (passwordError) {
      setStatus('error');
      setMessage(passwordError);
      return;
    }

    setLoading(true);
    setStatus('idle');
    setMessage('');

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: formData.newPassword }),
      });
      const data = await response.json();
      if (response.ok && data.status === 'success') {
        setStatus('success');
        setMessage(data.message || 'Your password has been reset successfully!');
        setTimeout(() => router.push('/login'), 3000);
      } else {
        setStatus('error');
        setMessage(data.detail || 'Password reset failed. The link may be invalid or expired.');
      }
    } catch {
      setStatus('error');
      setMessage('An error occurred while resetting your password. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthCentered>
      <h1 className="type-section-title" style={{ textAlign: 'center', marginBottom: 8 }}>
        Reset password
      </h1>
      <p className="dim" style={{ textAlign: 'center', fontSize: 13, marginBottom: 20 }}>
        Enter your new password below
      </p>

      {message ? (
        <div
          className={status === 'success' ? 'alert' : 'alert alert-error'}
          style={{ marginBottom: 16, display: 'flex', gap: 8, alignItems: 'start', fontSize: 13 }}
        >
          {status === 'success' ? <CheckCircle size={18} /> : <XCircle size={18} />}
          {message}
        </div>
      ) : null}

      {status !== 'success' && token ? (
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="field">
            <label htmlFor="newPassword">New password</label>
            <div className="field-input-wrap">
              <Lock className="field-icon" size={18} />
              <input
                id="newPassword"
                type={showPassword ? 'text' : 'password'}
                className="input has-toggle"
                value={formData.newPassword}
                onChange={(e) => setFormData({ ...formData, newPassword: e.target.value })}
                required
                minLength={6}
                disabled={loading}
              />
              <button type="button" className="field-toggle" onClick={() => setShowPassword(!showPassword)}>
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </div>

          <div className="field">
            <label htmlFor="confirmPassword">Confirm password</label>
            <div className="field-input-wrap">
              <Lock className="field-icon" size={18} />
              <input
                id="confirmPassword"
                type={showConfirmPassword ? 'text' : 'password'}
                className="input has-toggle"
                value={formData.confirmPassword}
                onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                required
                disabled={loading}
              />
              <button type="button" className="field-toggle" onClick={() => setShowConfirmPassword(!showConfirmPassword)}>
                {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </div>

          <button type="submit" className="btn btn-primary" disabled={loading} style={{ width: '100%' }}>
            {loading ? (
              <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                <Loader2 size={18} className="animate-spin" /> Resetting…
              </span>
            ) : (
              'Reset password'
            )}
          </button>
        </form>
      ) : null}

      {status === 'success' && (
        <Link href="/login" className="btn btn-primary" style={{ display: 'block', textAlign: 'center', marginTop: 8 }}>
          Go to login
        </Link>
      )}

      {status === 'error' && !token && (
        <Link href="/login" className="btn btn-primary" style={{ display: 'block', textAlign: 'center' }}>
          Back to login
        </Link>
      )}

      <p className="dim" style={{ fontSize: 11, textAlign: 'center', marginTop: 20 }}>
        Remember your password?{' '}
        <Link href="/login" style={{ color: 'var(--accent)' }}>
          Sign in
        </Link>
      </p>
    </AuthCentered>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<AuthCentered><AppLoading label="Loading…" /></AuthCentered>}>
      <ResetPasswordContent />
    </Suspense>
  );
}
