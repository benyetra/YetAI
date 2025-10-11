import React from 'react';
import { Sidebar, Header, MobileBottomNav } from './Navigation';
import { useAuth } from './Auth';
import EmailVerificationBanner from './EmailVerificationBanner';

interface LayoutProps {
  children: React.ReactNode;
  requiresAuth?: boolean;
  fullWidth?: boolean;
}

export default function Layout({ children, requiresAuth = false, fullWidth = false }: LayoutProps) {
  const { isAuthenticated, user } = useAuth();
  const showBanner = user && !user.is_verified;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sidebar - Desktop */}
      <Sidebar />

      {/* Header */}
      <Header />

      {/* Email Verification Banner */}
      <EmailVerificationBanner />

      {/* Main Content */}
      <main className={`
        ${showBanner ? 'pt-28' : 'pt-16'} pb-16 lg:pb-0
        lg:pl-64
        min-h-screen
        ${fullWidth ? '' : 'max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8'}
      `}>
        {children}
      </main>

      {/* Mobile Bottom Navigation */}
      <MobileBottomNav />
    </div>
  );
}