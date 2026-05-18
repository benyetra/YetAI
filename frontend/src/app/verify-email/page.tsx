'use client';

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { CheckCircle, XCircle, Mail, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { AuthCentered } from '@/components/yetai/auth/AuthShell';
import AppLoading from '@/components/yetai/AppLoading';

function VerifyEmailContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get('token');

  const [status, setStatus] = useState<'verifying' | 'success' | 'error'>('verifying');
  const [message, setMessage] = useState('');
  const [resendingEmail, setResendingEmail] = useState(false);
  const [resendMessage, setResendMessage] = useState('');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('No verification token provided');
      return;
    }
    verifyEmail(token);
  }, [token]);

  const verifyEmail = async (verificationToken: string) => {
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/verify-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: verificationToken }),
      });
      const data = await response.json();
      if (response.ok && data.status === 'success') {
        setStatus('success');
        setMessage(data.message || 'Your email has been verified successfully!');
        const storedUser = localStorage.getItem('user_data');
        if (storedUser) {
          const userData = JSON.parse(storedUser);
          userData.is_verified = true;
          localStorage.setItem('user_data', JSON.stringify(userData));
          window.dispatchEvent(new Event('storage'));
        }
        setTimeout(() => {
          router.push(storedUser ? '/' : '/login');
        }, 3000);
      } else {
        setStatus('error');
        setMessage(data.detail || 'Email verification failed. The link may be invalid or expired.');
      }
    } catch {
      setStatus('error');
      setMessage('An error occurred while verifying your email. Please try again.');
    }
  };

  const handleResendEmail = async () => {
    setResendMessage('Please contact support or sign up again for a new verification email.');
    setResendingEmail(false);
  };

  return (
    <AuthCentered>
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        {status === 'verifying' && <Loader2 size={48} className="animate-spin" style={{ color: 'var(--accent)', margin: '0 auto' }} />}
        {status === 'success' && <CheckCircle size={48} style={{ color: 'var(--win)', margin: '0 auto' }} />}
        {status === 'error' && <XCircle size={48} style={{ color: 'var(--loss)', margin: '0 auto' }} />}
      </div>

      <h1 className="type-section-title" style={{ textAlign: 'center', marginBottom: 8 }}>
        {status === 'verifying' && 'Verifying your email'}
        {status === 'success' && 'Email verified'}
        {status === 'error' && 'Verification failed'}
      </h1>

      {message ? (
        <div className={status === 'success' ? 'alert' : status === 'error' ? 'alert alert-error' : 'alert'} style={{ marginBottom: 16, textAlign: 'center', fontSize: 13 }}>
          {message}
        </div>
      ) : null}

      {resendMessage ? <p className="dim" style={{ fontSize: 13, textAlign: 'center', marginBottom: 16 }}>{resendMessage}</p> : null}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {status === 'success' && (
          <>
            <p className="dim" style={{ fontSize: 13, textAlign: 'center' }}>Redirecting in a few seconds…</p>
            <Link href="/login" className="btn btn-primary" style={{ textAlign: 'center' }}>
              Go to login
            </Link>
          </>
        )}
        {status === 'error' && (
          <>
            <button type="button" className="btn btn-primary" onClick={handleResendEmail} disabled={resendingEmail}>
              <Mail size={16} style={{ marginRight: 6 }} />
              Request new link
            </button>
            <Link href="/signup" className="btn" style={{ textAlign: 'center' }}>
              Create new account
            </Link>
          </>
        )}
        {status === 'verifying' && (
          <p className="dim" style={{ fontSize: 13, textAlign: 'center' }}>Please wait…</p>
        )}
      </div>

      <p className="dim" style={{ fontSize: 11, textAlign: 'center', marginTop: 20 }}>
        Need help? <Link href="/help" style={{ color: 'var(--accent)' }}>Contact support</Link>
      </p>
    </AuthCentered>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<AuthCentered><AppLoading label="Loading…" /></AuthCentered>}>
      <VerifyEmailContent />
    </Suspense>
  );
}
