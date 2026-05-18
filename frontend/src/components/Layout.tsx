import React from 'react';
import { Sidebar, Header, MobileBottomNav } from './Navigation';
import { useAuth } from './Auth';
import EmailVerificationBanner from './EmailVerificationBanner';

interface LayoutProps {
  children: React.ReactNode;
  requiresAuth?: boolean;
  fullWidth?: boolean;
}

export default function Layout({ children, fullWidth = false }: LayoutProps) {
  const { user } = useAuth();
  const showBanner = user && !user.is_verified;

  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <Header />
        {showBanner && (
          <div className="px-7 pt-2">
            <EmailVerificationBanner />
          </div>
        )}
        <div className={fullWidth ? 'content content--full' : 'content'}>
          {children}
        </div>
      </div>
      <MobileBottomNav />
    </div>
  );
}
