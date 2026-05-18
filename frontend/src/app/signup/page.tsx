'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/components/Auth';
import { Eye, EyeOff, Mail, Lock, User } from 'lucide-react';
import Link from 'next/link';
import { AuthShell } from '@/components/yetai/auth/AuthShell';
import AppLoading from '@/components/yetai/AppLoading';

export default function SignUpPage() {
  const router = useRouter();
  const { signup, isAuthenticated, loading } = useAuth();
  const [formData, setFormData] = useState({
    firstName: '',
    lastName: '',
    email: '',
    username: '',
    password: '',
    confirmPassword: '',
    agreeToTerms: false,
  });
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (isAuthenticated) router.push('/dashboard');
  }, [isAuthenticated, router]);

  const handleInputChange = (field: string, value: string | boolean) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setError('');
  };

  const validateForm = () => {
    if (!formData.firstName.trim()) return setError('First name is required'), false;
    if (!formData.email.trim()) return setError('Email is required'), false;
    if (!formData.username.trim()) return setError('Username is required'), false;
    if (formData.username.length < 3) return setError('Username must be at least 3 characters'), false;
    if (!/^[a-zA-Z0-9_-]+$/.test(formData.username))
      return setError('Username can only contain letters, numbers, underscores, and hyphens'), false;
    if (formData.password.length < 6) return setError('Password must be at least 6 characters'), false;
    if (formData.password !== formData.confirmPassword) return setError('Passwords do not match'), false;
    if (!formData.agreeToTerms) return setError('You must agree to the terms'), false;
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateForm()) return;
    setIsLoading(true);
    setError('');
    try {
      const result = await signup(
        formData.email,
        formData.username,
        formData.password,
        formData.firstName,
        formData.lastName,
      );
      if (result.success) router.push('/dashboard');
      else setError(result.message || 'Signup failed. Please try again.');
    } catch {
      setError('An unexpected error occurred. Please try again.');
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
    <AuthShell>
      <div>
        <h1 className="type-page-title" style={{ fontSize: 26 }}>Create account</h1>
        <p className="dim" style={{ marginTop: 6, fontSize: 14 }}>
          Join YetAI and start your betting journey
        </p>
      </div>

      <button
        type="button"
        className="btn"
        style={{ width: '100%' }}
        onClick={() => setError('Google Sign-up is coming soon. Please use email for now.')}
      >
        Sign up with Google
      </button>

      <div className="auth-divider">or email</div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {error ? <div className="alert alert-error">{error}</div> : null}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="field">
            <label htmlFor="firstName">First name</label>
            <input
              id="firstName"
              className="input"
              required
              value={formData.firstName}
              onChange={(e) => handleInputChange('firstName', e.target.value)}
              placeholder="John"
            />
          </div>
          <div className="field">
            <label htmlFor="lastName">Last name</label>
            <input
              id="lastName"
              className="input"
              value={formData.lastName}
              onChange={(e) => handleInputChange('lastName', e.target.value)}
              placeholder="Doe"
            />
          </div>
        </div>

        <div className="field">
          <label htmlFor="email">Email</label>
          <div className="field-input-wrap">
            <Mail className="field-icon" size={18} />
            <input
              id="email"
              type="email"
              className="input"
              required
              value={formData.email}
              onChange={(e) => handleInputChange('email', e.target.value)}
              placeholder="john@example.com"
            />
          </div>
        </div>

        <div className="field">
          <label htmlFor="username">Username</label>
          <div className="field-input-wrap">
            <User className="field-icon" size={18} />
            <input
              id="username"
              className="input"
              required
              value={formData.username}
              onChange={(e) => handleInputChange('username', e.target.value)}
              placeholder="john_doe"
            />
          </div>
          <p className="dim" style={{ fontSize: 11, marginTop: 4 }}>
            3+ characters; letters, numbers, _ and -
          </p>
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <div className="field-input-wrap">
            <Lock className="field-icon" size={18} />
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              className="input has-toggle"
              required
              value={formData.password}
              onChange={(e) => handleInputChange('password', e.target.value)}
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
              required
              value={formData.confirmPassword}
              onChange={(e) => handleInputChange('confirmPassword', e.target.value)}
            />
            <button type="button" className="field-toggle" onClick={() => setShowConfirmPassword(!showConfirmPassword)}>
              {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
        </div>

        <label style={{ display: 'flex', gap: 8, fontSize: 13, color: 'var(--text-2)', alignItems: 'start' }}>
          <input
            type="checkbox"
            checked={formData.agreeToTerms}
            onChange={(e) => handleInputChange('agreeToTerms', e.target.checked)}
            style={{ marginTop: 3 }}
          />
          <span>
            I agree to the{' '}
            <Link href="/terms" style={{ color: 'var(--accent)' }}>
              Terms
            </Link>{' '}
            and{' '}
            <Link href="/privacy" style={{ color: 'var(--accent)' }}>
              Privacy Policy
            </Link>
          </span>
        </label>

        <button type="submit" className="btn btn-primary" disabled={isLoading} style={{ width: '100%' }}>
          {isLoading ? 'Creating account…' : 'Create account'}
        </button>

        <p className="dim" style={{ textAlign: 'center', fontSize: 13, margin: 0 }}>
          Already have an account?{' '}
          <Link href="/login" style={{ color: 'var(--accent)' }}>
            Log in
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
