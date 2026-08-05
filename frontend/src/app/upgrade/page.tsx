'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import AppLoading from '@/components/yetai/AppLoading';
import PageHeader from '@/components/yetai/PageHeader';
import { StatTile } from '@/components/yetai/primitives';
import { Check, Brain, TrendingUp, Shield, Users, ArrowLeft } from 'lucide-react';
import EmbeddedCheckout from '@/components/EmbeddedCheckout';
import { getApiUrl } from '@/lib/api-config';
import { buildLoginUrl } from '@/lib/auth-redirect';

export default function UpgradePage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [error, setError] = useState('');
  const [clientSecret, setClientSecret] = useState<string | null>(null);
  const [showCheckout, setShowCheckout] = useState(false);

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push(buildLoginUrl());
    }
  }, [isAuthenticated, loading, router]);

  if (loading) {
    return (
      <Layout>
        <AppLoading label="Loading plans…" />
      </Layout>
    );
  }

  if (!isAuthenticated) return null;

  const handleUpgrade = async () => {
    setCheckoutLoading(true);
    setError('');
    try {
      const response = await fetch(getApiUrl('/api/subscription/create-checkout'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('auth_token')}`,
        },
        body: JSON.stringify({
          tier: 'pro',
          return_url: `${window.location.origin}/upgrade/success`,
        }),
      });
      const data = await response.json();
      if (response.ok && data.client_secret) {
        setClientSecret(data.client_secret);
        setShowCheckout(true);
      } else {
        setError(data.detail || 'Failed to start checkout process');
      }
    } catch {
      setError('An error occurred. Please try again.');
    } finally {
      setCheckoutLoading(false);
    }
  };

  const isProUser = user?.subscription_tier === 'pro';

  const plans = [
    {
      name: 'Free',
      price: '$0',
      period: '/month',
      description: 'Perfect for getting started',
      features: ['5 parlays per month', 'Basic odds viewing', 'Community access', 'Email support'],
      tier: 'free' as const,
    },
    {
      name: 'Pro',
      price: '$19',
      period: '/month',
      description: 'For serious bettors',
      popular: true,
      features: [
        'Unlimited parlays',
        'AI-powered predictions',
        'Advanced analytics',
        'Live chat support',
        'Fantasy insights',
        'Priority notifications',
        'Early access to new features',
      ],
      tier: 'pro' as const,
    },
  ];

  return (
    <Layout requiresAuth fullWidth>
      {!showCheckout ? (
        <>
          <PageHeader
            title="Upgrade"
            subtitle="Unlock advanced features and maximize your betting potential"
            actions={
              isProUser ? (
                <span className="badge badge-win" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <Check size={14} /> Pro plan active
                </span>
              ) : null
            }
          />

          <div className="stat-grid" style={{ marginBottom: 24 }}>
            <StatTile label="AI predictions" value="Unlimited" icon={<Brain size={16} />} />
            <StatTile label="Avg win lift" value="+23%" icon={<TrendingUp size={16} />} deltaKind="up" />
            <StatTile label="Support" value="Priority" icon={<Shield size={16} />} />
            <StatTile label="Community" value="Elite" icon={<Users size={16} />} />
          </div>

          {error ? <div className="alert alert-error" style={{ marginBottom: 16 }}>{error}</div> : null}

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
              gap: 16,
              maxWidth: 880,
              margin: '0 auto 24px',
            }}
          >
            {plans.map((plan) => (
              <section
                key={plan.name}
                className="card"
                style={{
                  padding: 24,
                  borderColor: plan.popular ? 'var(--accent)' : undefined,
                  position: 'relative',
                }}
              >
                {plan.popular ? (
                  <span
                    className="badge badge-gold"
                    style={{ position: 'absolute', top: -10, left: '50%', transform: 'translateX(-50%)' }}
                  >
                    Most popular
                  </span>
                ) : null}
                <h3 className="type-section-title">{plan.name}</h3>
                <p className="type-numeric-lg" style={{ margin: '8px 0 4px' }}>
                  {plan.price}
                  <span className="dim" style={{ fontSize: 14, fontFamily: 'var(--sans)' }}>
                    {plan.period}
                  </span>
                </p>
                <p className="dim" style={{ fontSize: 13, marginBottom: 16 }}>{plan.description}</p>
                <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 20px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {plan.features.map((f) => (
                    <li key={f} style={{ display: 'flex', gap: 8, fontSize: 13, color: 'var(--text-2)' }}>
                      <Check size={16} style={{ color: 'var(--win)', flexShrink: 0 }} />
                      {f}
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  className={plan.tier === 'pro' && !isProUser ? 'btn btn-primary' : 'btn'}
                  style={{ width: '100%' }}
                  disabled={checkoutLoading || plan.tier === 'free' || isProUser}
                  onClick={() => {
                    if (plan.tier === 'pro' && !isProUser) handleUpgrade();
                  }}
                >
                  {checkoutLoading && plan.tier === 'pro' && !isProUser
                    ? 'Processing…'
                    : plan.tier === 'pro' && isProUser
                    ? 'Current plan'
                    : plan.tier === 'free'
                    ? 'Current plan'
                    : 'Upgrade to Pro'}
                </button>
              </section>
            ))}
          </div>

          <section className="card" style={{ padding: 24, marginBottom: 16 }}>
            <h2 className="type-section-title" style={{ textAlign: 'center', marginBottom: 20 }}>
              Why upgrade?
            </h2>
            <div className="stat-grid">
              <StatTile label="Advanced AI" value="Pro models" icon={<Brain size={16} />} />
              <StatTile label="Better results" value="23% lift" icon={<TrendingUp size={16} />} deltaKind="up" />
              <StatTile label="Priority support" value="Live chat" icon={<Shield size={16} />} />
              <StatTile label="Elite community" value="Top bettors" icon={<Users size={16} />} />
            </div>
          </section>

          <section className="card" style={{ padding: 24 }}>
            <h3 className="type-section-title" style={{ marginBottom: 16 }}>
              FAQ
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div>
                <h4 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Can I cancel anytime?</h4>
                <p className="dim" style={{ fontSize: 13, margin: 0 }}>
                  Yes. Access continues until the end of your billing period.
                </p>
              </div>
              <div>
                <h4 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Do you offer refunds?</h4>
                <p className="dim" style={{ fontSize: 13, margin: 0 }}>
                  7-day money-back guarantee for new subscriptions.
                </p>
              </div>
              <div>
                <h4 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Payment methods?</h4>
                <p className="dim" style={{ fontSize: 13, margin: 0 }}>
                  Major credit cards and PayPal via Stripe.
                </p>
              </div>
            </div>
          </section>
        </>
      ) : (
        <div style={{ maxWidth: 640, margin: '0 auto' }}>
          <button type="button" className="btn" onClick={() => { setShowCheckout(false); setClientSecret(null); setError(''); }} style={{ marginBottom: 16 }}>
            <ArrowLeft size={16} style={{ marginRight: 6 }} />
            Back to plans
          </button>
          <section className="card" style={{ padding: 24 }}>
            <PageHeader title="Complete checkout" subtitle="Enter payment details to activate Pro" />
            {error ? <div className="alert alert-error" style={{ marginBottom: 16 }}>{error}</div> : null}
            {clientSecret ? (
              <EmbeddedCheckout
                clientSecret={clientSecret}
                onComplete={() => router.push('/upgrade/success')}
                onError={(msg) => {
                  setError(msg);
                  setShowCheckout(false);
                  setClientSecret(null);
                }}
              />
            ) : null}
          </section>
        </div>
      )}
    </Layout>
  );
}
