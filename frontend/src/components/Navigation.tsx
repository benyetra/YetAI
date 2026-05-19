'use client';

import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import {
  Home,
  History,
  Trophy,
  Brain,
  Menu,
  X,
  ChevronRight,
  BarChart3,
  Users,
  Activity,
  Bell,
  LogOut,
  User,
  Crown,
  Layers,
  Target,
  Sparkles,
  Shield,
  Search,
  Calculator,
  LineChart,
} from 'lucide-react';
import { useAuth } from './Auth';
import { useNotifications } from './NotificationProvider';
import { WebSocketIndicator } from './WebSocketIndicator';
import { NotificationPanel } from './NotificationPanel';
interface NavItem {
  name: string;
  href: string;
  icon: React.ElementType;
  badge?: string;
  pillClass?: string;
  requiresAuth?: boolean;
}

const mainNavigation: NavItem[] = [
  { name: 'Dashboard', href: '/dashboard', icon: Home, requiresAuth: true },
  { name: 'YetAI Bets', href: '/predictions', icon: Brain, badge: 'AI', pillClass: 'pill-ai' },
  { name: 'Place Bet', href: '/bet', icon: Target, requiresAuth: true },
  { name: 'Live Betting', href: '/live-betting', icon: Activity, requiresAuth: true, badge: 'LIVE', pillClass: 'pill-live' },
];

const toolsNavigation: NavItem[] = [
  { name: 'Stat Projections', href: '/predictions/stats', icon: LineChart, requiresAuth: true },
  { name: 'Bet Calculator', href: '/tools/bet-calculator', icon: Calculator, requiresAuth: true },
  { name: "Owen's Corner", href: '/tools/owens-betting-corner', icon: Sparkles, requiresAuth: true },
  { name: 'Parlays', href: '/parlays', icon: Layers, requiresAuth: true, badge: 'NEW', pillClass: 'pill-new' },
  { name: 'Fantasy', href: '/fantasy', icon: Trophy, requiresAuth: true },
  { name: 'My Bets', href: '/bets', icon: History, requiresAuth: true },
  { name: 'Leaderboard', href: '/leaderboard', icon: Users },
];

const ROUTE_LABELS: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/predictions': 'YetAI Bets',
  '/bet': 'Place Bet',
  '/live-betting': 'Live',
  '/parlays': 'Parlays',
  '/fantasy': 'Fantasy',
  '/bets': 'My Bets',
  '/leaderboard': 'Leaderboard',
  '/profile': 'Profile',
  '/admin': 'Admin',
  '/upgrade': 'Upgrade',
  '/odds': 'Odds',
  '/chat': 'Chat',
  '/help': 'Help',
  '/predictions/stats': 'Stat Projections',
  '/tools/bet-calculator': 'Bet Calculator',
  '/tools/owens-betting-corner': "Owen's Corner",
  '/predictions/mlb': 'MLB Stats',
  '/predictions/nba': 'NBA Stats',
  '/predictions/nfl': 'NFL Stats',
  '/predictions/nhl': 'NHL Stats',
};

function getRouteLabel(pathname: string): string {
  const sorted = Object.entries(ROUTE_LABELS).sort((a, b) => b[0].length - a[0].length);
  for (const [path, label] of sorted) {
    if (pathname === path || pathname.startsWith(`${path}/`)) {
      return label;
    }
  }
  return 'Dashboard';
}

function getUserInitials(user: { first_name?: string; last_name?: string; username?: string }): string {
  if (user.first_name && user.last_name) {
    return `${user.first_name[0]}${user.last_name[0]}`.toUpperCase();
  }
  if (user.first_name) {
    return user.first_name.slice(0, 2).toUpperCase();
  }
  return (user.username || 'U').slice(0, 2).toUpperCase();
}

type MobileNavContextValue = {
  isMobileOpen: boolean;
  toggleMobileNav: () => void;
  closeMobileNav: () => void;
};

const MobileNavContext = createContext<MobileNavContextValue | null>(null);

function useMobileNav() {
  const ctx = useContext(MobileNavContext);
  if (!ctx) {
    throw new Error('useMobileNav must be used within MobileNavProvider');
  }
  return ctx;
}

export function MobileNavProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  useEffect(() => {
    setIsMobileOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!isMobileOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [isMobileOpen]);

  const value = useMemo<MobileNavContextValue>(
    () => ({
      isMobileOpen,
      toggleMobileNav: () => setIsMobileOpen((open) => !open),
      closeMobileNav: () => setIsMobileOpen(false),
    }),
    [isMobileOpen],
  );

  return <MobileNavContext.Provider value={value}>{children}</MobileNavContext.Provider>;
}

function NavButton({
  item,
  active,
  locked,
  onClick,
}: {
  item: NavItem;
  active: boolean;
  locked: boolean;
  onClick: () => void;
}) {
  const Icon = item.icon;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={locked}
      className={`nav-item ${active ? 'active' : ''}`}
      style={locked ? { opacity: 0.5, cursor: 'not-allowed' } : undefined}
    >
      <span className="nav-ico">
        <Icon size={16} strokeWidth={active ? 2.25 : 1.75} />
      </span>
      <span>{item.name}</span>
      {item.badge && (
        <span className={`nav-pill ${item.pillClass || ''}`}>{item.badge}</span>
      )}
    </button>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout, isAuthenticated } = useAuth();
  const { isMobileOpen, closeMobileNav } = useMobileNav();

  const handleNavClick = (item: NavItem) => {
    if (item.requiresAuth && !isAuthenticated) {
      router.push('/?login=true');
      return;
    }
    closeMobileNav();
    router.push(item.href);
  };

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  const renderNavGroup = (items: NavItem[]) =>
    items.map((item) => (
      <NavButton
        key={item.name}
        item={item}
        active={isActive(item.href)}
        locked={Boolean(item.requiresAuth && !isAuthenticated)}
        onClick={() => handleNavClick(item)}
      />
    ));

  return (
    <>
      <button
        type="button"
        className={`nav-mobile-backdrop ${isMobileOpen ? 'is-visible' : ''}`}
        onClick={closeMobileNav}
        aria-label="Close menu"
        tabIndex={isMobileOpen ? 0 : -1}
      />

      <aside className={`sidebar ${isMobileOpen ? 'sidebar--open' : ''}`}>
        <div className="brand">
          <div className="brand-mark">
            <img src="/logo.png" alt="" width={20} height={20} style={{ borderRadius: 4 }} />
          </div>
          <div>
            <div className="brand-name">YetAI</div>
            <div className="brand-tag">Smart Sports</div>
          </div>
        </div>

        <div className="nav-section">Main</div>
        {renderNavGroup(mainNavigation)}

        <div className="nav-section">Tools</div>
        {renderNavGroup(toolsNavigation)}

        {isAuthenticated && (
          <>
            <button
              type="button"
              className={`nav-item ${isActive('/profile') ? 'active' : ''}`}
              onClick={() => router.push('/profile')}
            >
              <span className="nav-ico">
                <User size={16} />
              </span>
              <span>Profile</span>
            </button>
            {user?.is_admin && (
              <button
                type="button"
                className={`nav-item ${isActive('/admin') ? 'active' : ''}`}
                onClick={() => router.push('/admin')}
              >
                <span className="nav-ico">
                  <Shield size={16} />
                </span>
                <span>Admin</span>
                <span className="nav-pill pill-live">ADMIN</span>
              </button>
            )}
          </>
        )}

        <div className="sidebar-footer">
          {isAuthenticated && user?.subscription_tier === 'free' && (
            <div className="card card-tight" style={{ marginBottom: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <Sparkles size={16} style={{ color: 'var(--gold)' }} />
                <span style={{ fontSize: 13, fontWeight: 600 }}>Upgrade to Pro</span>
              </div>
              <p className="dim" style={{ fontSize: 11.5, margin: '0 0 10px' }}>
                AI insights, unlimited bets & more
              </p>
              <button type="button" className="btn btn-primary btn-sm btn-block" onClick={() => router.push('/upgrade')}>
                Upgrade Now
              </button>
            </div>
          )}

          {isAuthenticated && user ? (
            <div className="user-card">
              <div className="user-avatar">{getUserInitials(user)}</div>
              <div className="user-meta">
                <div className="user-name">{user.first_name || user.username}</div>
                <div className="user-tier">
                  {user.subscription_tier !== 'free' && <Crown size={10} style={{ color: 'var(--gold)' }} />}
                  <span className="tier-dot" />
                  <span className="capitalize">{user.subscription_tier} member</span>
                </div>
              </div>
              <button
                type="button"
                className="btn-ghost"
                style={{ padding: 4, color: 'var(--text-3)' }}
                onClick={() => router.push('/profile')}
                aria-label="Profile"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          ) : null}

          {isAuthenticated && (
            <button
              type="button"
              className="nav-item"
              onClick={logout}
              style={{ color: 'var(--loss)' }}
            >
              <span className="nav-ico">
                <LogOut size={16} />
              </span>
              <span>Sign Out</span>
            </button>
          )}
        </div>
      </aside>
    </>
  );
}

function MobileMenuToggle() {
  const { isMobileOpen, toggleMobileNav } = useMobileNav();
  return (
    <button
      type="button"
      onClick={toggleMobileNav}
      className="nav-mobile-toggle icon-btn"
      aria-label={isMobileOpen ? 'Close menu' : 'Open menu'}
      aria-expanded={isMobileOpen}
    >
      {isMobileOpen ? <X size={18} /> : <Menu size={18} />}
    </button>
  );
}

export function Header() {
  const { isAuthenticated } = useAuth();
  const { unreadCount } = useNotifications();
  const router = useRouter();
  const pathname = usePathname();
  const [showNotifications, setShowNotifications] = useState(false);
  const pageLabel = getRouteLabel(pathname);

  return (
    <header className="topbar">
      <MobileMenuToggle />
      <div className="crumb">
        <span>YetAI</span>
        <ChevronRight size={12} style={{ opacity: 0.5 }} />
        <b>{pageLabel}</b>
      </div>
      <div className="topbar-spacer" />

      <WebSocketIndicator />

      {isAuthenticated && (
        <button type="button" className="btn btn-primary btn-sm hidden sm:inline-flex" onClick={() => router.push('/bet')}>
          <Target size={14} />
          Place Bet
        </button>
      )}

      {isAuthenticated && (
        <>
          <button type="button" className="icon-btn hidden md:grid" aria-label="Search">
            <Search size={14} />
          </button>
          <div className="relative">
            <button
              type="button"
              className={`icon-btn ${unreadCount > 0 ? 'notif-dot' : ''}`}
              onClick={() => setShowNotifications(!showNotifications)}
              aria-label="Notifications"
            >
              <Bell size={14} />
            </button>
            <NotificationPanel isOpen={showNotifications} onClose={() => setShowNotifications(false)} />
          </div>
        </>
      )}

      {!isAuthenticated && (
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => router.push('/?login=true')}>
            Sign In
          </button>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => router.push('/?signup=true')}>
            Get Started
          </button>
        </div>
      )}
    </header>
  );
}

export function MobileBottomNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated } = useAuth();

  const mobileNav = [
    { name: 'Home', href: '/dashboard', icon: Home },
    { name: 'AI', href: '/predictions', icon: Brain },
    { name: 'Live', href: '/live-betting', icon: Activity },
    { name: 'Bet', href: '/bet', icon: Target },
    { name: 'More', href: '/profile', icon: Menu },
  ];

  return (
    <nav
      className="lg:hidden"
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 40,
        background: 'var(--bg-elev)',
        borderTop: '1px solid var(--border)',
      }}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', height: 56 }}>
        {mobileNav.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          const needsAuth =
            item.href === '/bet' ||
            item.href === '/dashboard' ||
            item.href === '/live-betting' ||
            item.href === '/profile';

          return (
            <button
              key={item.name}
              type="button"
              onClick={() => {
                if (needsAuth && !isAuthenticated) {
                  router.push('/?login=true');
                } else {
                  router.push(item.href);
                }
              }}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 2,
                fontSize: 10,
                fontWeight: 500,
                color: active ? 'var(--accent)' : 'var(--text-3)',
                background: 'transparent',
              }}
            >
              <Icon size={18} strokeWidth={active ? 2.25 : 1.75} />
              <span>{item.name}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
