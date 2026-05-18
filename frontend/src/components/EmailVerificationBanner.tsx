'use client';

import { useState } from 'react';
import { X, Mail, AlertCircle } from 'lucide-react';
import { useAuth } from './Auth';
import { getApiUrl } from '@/lib/api-config';

export default function EmailVerificationBanner() {
  const { user } = useAuth();
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  if (!user || user.is_verified || dismissed) {
    return null;
  }

  const handleResendEmail = async () => {
    setLoading(true);
    setMessage('');

    try {
      const response = await fetch(getApiUrl('/api/auth/resend-verification'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email: user.email }),
      });

      const data = await response.json();

      if (response.ok) {
        setMessage('Verification email sent! Check your inbox (and spam folder).');
      } else {
        setMessage(data.detail || 'Failed to resend email. Please try again.');
      }
    } catch {
      setMessage('An error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="card card-tight"
      style={{
        borderColor: 'color-mix(in oklab, var(--accent) 40%, var(--border))',
        background:
          'linear-gradient(90deg, color-mix(in oklab, var(--accent) 18%, var(--surface)), var(--surface))',
      }}
    >
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 flex-1">
          <AlertCircle className="w-5 h-5 flex-shrink-0" style={{ color: 'var(--accent)' }} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium">
              Please verify your email address to unlock all features
            </p>
            {message && <p className="text-xs mt-1 dim">{message}</p>}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleResendEmail}
            disabled={loading}
            className="btn btn-primary btn-sm flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
          >
            <Mail className="w-4 h-4" />
            {loading ? 'Sending...' : 'Resend Email'}
          </button>

          <button
            onClick={() => setDismissed(true)}
            className="icon-btn"
            aria-label="Dismiss banner"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
