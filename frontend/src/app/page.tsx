'use client';

import { useState } from 'react';
import Link from 'next/link';
import BettingDashboard from '@/components/BettingDashboard';
import { useAuth, UserMenu, AuthModal } from '@/components/Auth';

export default function Home() {
  const { isAuthenticated, loading } = useAuth();
  const [showAuthModal, setShowAuthModal] = useState(false);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-lg">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center space-x-8">
              <h1 className="text-xl font-bold text-gray-900">
                AI Sports Betting MVP
              </h1>
              
              {/* Navigation Links */}
              {isAuthenticated && (
                <nav className="flex space-x-6">
                  <Link 
                    href="/" 
                    className="text-gray-600 hover:text-gray-900 font-medium"
                  >
                    Home
                  </Link>
                  <Link 
                    href="/dashboard" 
                    className="text-blue-600 hover:text-blue-700 font-medium"
                  >
                    Dashboard
                  </Link>
                  <Link 
                    href="/bets" 
                    className="text-purple-600 hover:text-purple-700 font-medium"
                  >
                    My Bets
                  </Link>
                </nav>
              )}
            </div>
            
            <div className="flex items-center space-x-4">
              {isAuthenticated ? (
                <div className="flex items-center space-x-4">
                  <Link 
                    href="/dashboard"
                    className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 font-medium"
                  >
                    Go to Dashboard
                  </Link>
                  <UserMenu />
                </div>
              ) : (
                <button
                  onClick={() => setShowAuthModal(true)}
                  className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 font-medium"
                >
                  Sign In
                </button>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main>
        <BettingDashboard />
      </main>

      {/* Auth Modal */}
      <AuthModal 
        isOpen={showAuthModal} 
        onClose={() => setShowAuthModal(false)} 
      />
    </div>
  );
}
