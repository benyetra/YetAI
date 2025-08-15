'use client';

import { useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { AuthModal } from '@/components/Auth';
import { useAuth } from '@/components/Auth';
import Layout from '@/components/Layout';
import { 
  Zap, TrendingUp, Brain, Trophy, Users, Shield, 
  ChevronRight, Star, ArrowRight, DollarSign 
} from 'lucide-react';

export default function HomePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated } = useAuth();
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('login');

  useEffect(() => {
    // Check URL params for login/signup
    if (searchParams.get('login') === 'true') {
      setAuthMode('login');
      setShowAuthModal(true);
    } else if (searchParams.get('signup') === 'true') {
      setAuthMode('signup');
      setShowAuthModal(true);
    }
  }, [searchParams]);

  useEffect(() => {
    // Redirect to dashboard if already authenticated
    if (isAuthenticated) {
      router.push('/dashboard');
    }
  }, [isAuthenticated, router]);

  return (
    <Layout>
      {/* Hero Section */}
      <div className="relative overflow-hidden">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-24">
          <div className="text-center">
            <div className="flex justify-center mb-8">
              <div className="w-24 h-24 rounded-2xl overflow-hidden shadow-lg">
                <img 
                  src="/logo.png" 
                  alt="YetAI Logo" 
                  className="w-full h-full object-cover"
                />
              </div>
            </div>
            <h1 className="text-5xl font-bold text-gray-900 mb-6">
              AI-Powered Sports Betting
              <span className="block bg-gradient-to-r from-[#A855F7] to-[#F59E0B] bg-clip-text text-transparent">Made Simple</span>
            </h1>
            <p className="text-xl text-gray-700 font-medium mb-8 max-w-2xl mx-auto">
              Get real-time odds, AI predictions, and smart betting insights all in one platform.
              Join thousands making smarter bets with YetAI.
            </p>
            <div className="flex justify-center space-x-4">
              <button
                onClick={() => {
                  setAuthMode('signup');
                  setShowAuthModal(true);
                }}
                className="px-8 py-4 bg-[#A855F7] text-white rounded-lg hover:bg-[#A855F7]/90 transition-colors flex items-center"
              >
                Start Free Trial
                <ArrowRight className="w-5 h-5 ml-2" />
              </button>
              <button
                onClick={() => {
                  setAuthMode('login');
                  setShowAuthModal(true);
                }}
                className="px-8 py-4 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Sign In
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Features Grid */}
      <div className="py-20 bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h2 className="text-3xl font-bold text-center mb-12">
            Everything You Need to Win
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            <FeatureCard
              icon={Brain}
              title="AI Predictions"
              description="Advanced algorithms analyze thousands of data points to give you winning predictions"
            />
            <FeatureCard
              icon={TrendingUp}
              title="Live Odds"
              description="Real-time odds from major sportsbooks, all in one place"
            />
            <FeatureCard
              icon={Trophy}
              title="Fantasy Insights"
              description="Optimize your fantasy lineups with AI-powered player projections"
            />
            <FeatureCard
              icon={DollarSign}
              title="Smart Betting"
              description="Track your bets, analyze performance, and improve your strategy"
            />
            <FeatureCard
              icon={Users}
              title="Community"
              description="Join a community of smart bettors and share insights"
            />
            <FeatureCard
              icon={Shield}
              title="Secure & Safe"
              description="Bank-level security to protect your data and privacy"
            />
          </div>
        </div>
      </div>

      {/* Auth Modal */}
      <AuthModal
        isOpen={showAuthModal}
        onClose={() => setShowAuthModal(false)}
        initialMode={authMode}
      />
    </Layout>
  );
}

function FeatureCard({ icon: Icon, title, description }: {
  icon: React.ElementType;
  title: string;
  description: string;
}) {
  return (
    <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 hover:shadow-lg transition-shadow">
      <div className="w-12 h-12 bg-[#A855F7]/10 rounded-lg flex items-center justify-center mb-4">
        <Icon className="w-6 h-6 text-[#A855F7]" />
      </div>
      <h3 className="text-lg font-bold text-gray-900 mb-2">{title}</h3>
      <p className="text-gray-700 leading-relaxed">{description}</p>
    </div>
  );
}
