'use client';

import { useState } from 'react';
import { X, Mail, AlertCircle } from 'lucide-react';
import { useAuth } from './Auth';

export default function EmailVerificationBanner() {
  const { user } = useAuth();
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  // Debug logging
  console.log('EmailVerificationBanner - user:', user);
  console.log('EmailVerificationBanner - is_verified:', user?.is_verified);

  // Don't show if user is verified, not logged in, or banner dismissed
  if (!user || user.is_verified || dismissed) {
    console.log('Banner hidden - user:', !!user, 'verified:', user?.is_verified, 'dismissed:', dismissed);
    return null;
  }

  console.log('Banner SHOWING for user:', user.email);

  const handleResendEmail = async () => {
    setLoading(true);
    setMessage('');

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/resend-verification`, {
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
    } catch (error) {
      setMessage('An error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-gradient-to-r from-purple-600 to-amber-500 text-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between gap-4 py-3">
          <div className="flex items-center gap-3 flex-1">
            <AlertCircle className="w-5 h-5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">
                Please verify your email address to unlock all features
              </p>
              {message && (
                <p className="text-xs mt-1 opacity-90">
                  {message}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleResendEmail}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-1.5 bg-white/20 hover:bg-white/30 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
            >
              <Mail className="w-4 h-4" />
              {loading ? 'Sending...' : 'Resend Email'}
            </button>

            <button
              onClick={() => setDismissed(true)}
              className="p-1.5 hover:bg-white/20 rounded-lg transition-colors"
              aria-label="Dismiss banner"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
