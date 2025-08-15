'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { Crown, Check, Zap, Star, TrendingUp, Users, Shield, Brain } from 'lucide-react';

export default function UpgradePage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();
  const [selectedPlan, setSelectedPlan] = useState('pro');

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

  const plans = [
    {
      name: 'Free',
      price: '$0',
      period: '/month',
      description: 'Perfect for getting started',
      features: [
        '5 bets per month',
        'Basic odds viewing',
        'Community access',
        'Email support'
      ],
      buttonText: 'Current Plan',
      buttonStyle: 'bg-gray-300 text-gray-600 cursor-not-allowed'
    },
    {
      name: 'Pro',
      price: '$19',
      period: '/month',
      description: 'For serious bettors',
      features: [
        'Unlimited bets',
        'AI predictions',
        'Advanced analytics',
        'Live chat support',
        'Fantasy insights',
        'Priority notifications'
      ],
      buttonText: 'Upgrade to Pro',
      buttonStyle: 'bg-blue-600 text-white hover:bg-blue-700',
      popular: true
    },
    {
      name: 'Elite',
      price: '$49',
      period: '/month',
      description: 'Maximum winning potential',
      features: [
        'Everything in Pro',
        'Premium AI models',
        'Personal betting coach',
        'Advanced parlay builder',
        'White-glove support',
        'Exclusive community',
        'Custom analytics'
      ],
      buttonText: 'Upgrade to Elite',
      buttonStyle: 'bg-purple-600 text-white hover:bg-purple-700'
    }
  ];

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-gray-900 mb-4">Upgrade Your Experience</h1>
          <p className="text-gray-600 mb-8">Unlock advanced features and maximize your betting potential</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-12">
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

              <button className={`w-full py-3 rounded-lg font-medium transition-colors ${plan.buttonStyle}`}>
                {plan.buttonText}
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