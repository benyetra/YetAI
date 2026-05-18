'use client';

import { useState } from 'react';
import Link from 'next/link';
import { apiClient } from '@/lib/api';
import { Mail, ArrowLeft, Check, AlertCircle } from 'lucide-react';
import { AuthCentered } from '@/components/yetai/auth/AuthShell';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError('');
    try {
      await apiClient.post('/api/auth/forgot-password', { email });
      setSubmitted(true);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail;
      setError(detail || 'Failed to send reset email');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <AuthCentered>
        <div style={{ textAlign: 'center' }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: '50%',
              background: 'var(--win-soft)',
              display: 'grid',
              placeItems: 'center',
              margin: '0 auto 16px',
            }}
          >
            <Check size={28} style={{ color: 'var(--win)' }} />
          </div>
          <h1 className="type-section-title" style={{ marginBottom: 8 }}>Check your email</h1>
          <p className="dim" style={{ fontSize: 13, marginBottom: 16 }}>
            We sent a reset link to <strong style={{ color: 'var(--text)' }}>{email}</strong> if an account exists.
          </p>
          <p className="dim" style={{ fontSize: 12, marginBottom: 20 }}>
            The link expires in 1 hour.
          </p>
          <Link href="/login" className="btn" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <ArrowLeft size={16} /> Back to login
          </Link>
        </div>
      </AuthCentered>
    );
  }

  return (
    <AuthCentered>
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        <Mail size={32} style={{ color: 'var(--accent)', marginBottom: 12 }} />
        <h1 className="type-section-title">Forgot password?</h1>
        <p className="dim" style={{ fontSize: 13, marginTop: 8 }}>
          Enter your email and we&apos;ll send a reset link.
        </p>
      </div>

      {error ? (
        <div className="alert alert-error" style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <AlertCircle size={18} />
          {error}
        </div>
      ) : null}

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div className="field">
          <label htmlFor="email">Email</label>
          <div className="field-input-wrap">
            <Mail className="field-icon" size={18} />
            <input
              id="email"
              type="email"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@email.com"
              required
            />
          </div>
        </div>
        <button type="submit" className="btn btn-primary" disabled={isSubmitting} style={{ width: '100%' }}>
          {isSubmitting ? 'Sending…' : 'Send reset link'}
        </button>
      </form>

      <Link href="/login" className="btn" style={{ marginTop: 16, width: '100%', justifyContent: 'center' }}>
        <ArrowLeft size={16} /> Back to login
      </Link>
    </AuthCentered>
  );
}
