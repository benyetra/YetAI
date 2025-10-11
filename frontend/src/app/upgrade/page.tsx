'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { Crown, Check, Zap, Star, TrendingUp, Users, Shield, Brain } from 'lucide-react';

export default function UpgradePage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

  if (loading) {
    return (
      <Layout>
        <div className="min-h-screen flex items-center justify-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
      </Layout>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  const handleUpgrade = async () => {
    setCheckoutLoading(true);
    setError('');

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/subscription/create-checkout`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('auth_token')}`,
        },
        body: JSON.stringify({
          tier: 'pro',
          return_url: `${window.location.origin}/dashboard`,
        }),
      });

      const data = await response.json();

      if (response.ok && data.checkout_url) {
        // Redirect to Stripe Checkout
        window.location.href = data.checkout_url;
      } else {
        setError(data.detail || 'Failed to start checkout process');
        setCheckoutLoading(false);
      }
    } catch (err) {
      setError('An error occurred. Please try again.');
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
      features: [
        '5 parlays per month',
        'Basic odds viewing',
        'Community access',
        'Email support'
      ],
      buttonText: isProUser ? 'Downgrade to Free' : 'Current Plan',
      buttonStyle: 'bg-gray-300 text-gray-600 cursor-not-allowed',
      tier: 'free'
    },
    {
      name: 'Pro',
      price: '$19',
      period: '/month',
      description: 'For serious bettors',
      features: [
        'Unlimited parlays',
        'AI-powered predictions',
        'Advanced analytics',
        'Live chat support',
        'Fantasy insights',
        'Priority notifications',
        'Early access to new features'
      ],
      buttonText: isProUser ? 'Current Plan' : 'Upgrade to Pro',
      buttonStyle: isProUser
        ? 'bg-gray-300 text-gray-600 cursor-not-allowed'
        : 'bg-gradient-to-r from-purple-600 to-blue-600 text-white hover:from-purple-700 hover:to-blue-700',
      popular: true,
      tier: 'pro'
    }
  ];

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-gray-900 mb-4">Upgrade Your Experience</h1>
          <p className="text-gray-600 mb-8">Unlock advanced features and maximize your betting potential</p>
          {isProUser && (
            <div className="inline-flex items-center px-4 py-2 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm">
              <Check className="w-4 h-4 mr-2" />
              You're currently on the Pro plan
            </div>
          )}
        </div>

        {error && (
          <div className="max-w-2xl mx-auto p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-12 max-w-4xl mx-auto">
          {plans.map((plan) => (
            <div
              key={plan.name}
              className={`relative bg-white rounded-lg border-2 p-6 ${
                plan.popular ? 'border-blue-500 shadow-lg' : 'border-gray-200'
              }`}
            >
              {plan.popular && (
                <div className="absolute -top-3 left-1/2 transform -translate-x-1/2">
                  <span className="bg-blue-500 text-white px-4 py-1 rounded-full text-sm font-medium">
                    Most Popular
                  </span>
                </div>
              )}
              
              <div className="text-center">
                <h3 className="text-xl font-semibold mb-2">{plan.name}</h3>
                <div className="mb-4">
                  <span className="text-4xl font-bold">{plan.price}</span>
                  <span className="text-gray-600">{plan.period}</span>
                </div>
                <p className="text-gray-600 mb-6">{plan.description}</p>
              </div>

              <ul className="space-y-3 mb-8">
                {plan.features.map((feature, index) => (
                  <li key={index} className="flex items-center">
                    <Check className="w-5 h-5 text-green-500 mr-3" />
                    <span className="text-sm">{feature}</span>
                  </li>
                ))}
              </ul>

              <button
                onClick={() => {
                  if (plan.tier === 'pro' && !isProUser) {
                    handleUpgrade();
                  }
                }}
                disabled={checkoutLoading || plan.tier === 'free' || isProUser}
                className={`w-full py-3 rounded-lg font-medium transition-colors ${plan.buttonStyle}`}
              >
                {checkoutLoading && plan.tier === 'pro' && !isProUser ? (
                  <span className="flex items-center justify-center">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                    Processing...
                  </span>
                ) : (
                  plan.buttonText
                )}
              </button>
            </div>
          ))}
        </div>

        <div className="bg-gradient-to-r from-blue-50 to-purple-50 rounded-lg p-8">
          <h2 className="text-2xl font-bold text-center mb-8">Why Upgrade?</h2>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="text-center">
              <Brain className="w-12 h-12 text-blue-600 mx-auto mb-4" />
              <h3 className="font-semibold mb-2">Advanced AI</h3>
              <p className="text-sm text-gray-600">Get access to our most sophisticated prediction models</p>
            </div>
            
            <div className="text-center">
              <TrendingUp className="w-12 h-12 text-green-600 mx-auto mb-4" />
              <h3 className="font-semibold mb-2">Better Results</h3>
              <p className="text-sm text-gray-600">Pro users see 23% higher win rates on average</p>
            </div>
            
            <div className="text-center">
              <Shield className="w-12 h-12 text-purple-600 mx-auto mb-4" />
              <h3 className="font-semibold mb-2">Priority Support</h3>
              <p className="text-sm text-gray-600">Get help faster with priority customer support</p>
            </div>
            
            <div className="text-center">
              <Users className="w-12 h-12 text-orange-600 mx-auto mb-4" />
              <h3 className="font-semibold mb-2">Elite Community</h3>
              <p className="text-sm text-gray-600">Connect with top-performing bettors</p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h3 className="text-lg font-semibold mb-4">Frequently Asked Questions</h3>
          
          <div className="space-y-4">
            <div>
              <h4 className="font-medium text-gray-900">Can I cancel anytime?</h4>
              <p className="text-sm text-gray-600">Yes, you can cancel your subscription at any time. Your access will continue until the end of your billing period.</p>
            </div>
            
            <div>
              <h4 className="font-medium text-gray-900">Do you offer refunds?</h4>
              <p className="text-sm text-gray-600">We offer a 7-day money-back guarantee for all new subscriptions. No questions asked.</p>
            </div>
            
            <div>
              <h4 className="font-medium text-gray-900">What payment methods do you accept?</h4>
              <p className="text-sm text-gray-600">We accept all major credit cards, PayPal, and bank transfers for annual plans.</p>
            </div>
          </div>
        </div>

        <div className="text-center">
          <p className="text-sm text-gray-600">
            Need help choosing? <button className="text-blue-600 hover:text-blue-700 underline">Contact our sales team</button>
          </p>
        </div>
      </div>
    </Layout>
  );
}