'use client';

import React from 'react';
import Link from 'next/link';
import AuthPlatformStats from './AuthPlatformStats';

export function AuthBrand() {
  return (
    <Link href="/" className="auth-brand">
      <img src="/logo.png" alt="YetAI" />
      <span>YetAI</span>
    </Link>
  );
}

export function AuthShell({
  children,
  showHero = true,
}: {
  children: React.ReactNode;
  showHero?: boolean;
}) {
  return (
    <div className="auth-page">
      <div className="auth-form-panel">
        <div className="auth-form-inner">
          <AuthBrand />
          {children}
        </div>
      </div>
      {showHero ? (
        <div className="auth-hero-panel">
          <AuthPlatformStats />
        </div>
      ) : null}
    </div>
  );
}

export function AuthCentered({ children }: { children: React.ReactNode }) {
  return (
    <div className="auth-centered">
      <div className="auth-card card" style={{ padding: 28 }}>
        <AuthBrand />
        <div style={{ marginTop: 24 }}>{children}</div>
      </div>
    </div>
  );
}
