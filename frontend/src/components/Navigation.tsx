'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  Home,
  TrendingUp,
  History,
  Trophy,
  Brain,
  MessageSquare,
  HelpCircle,
  Menu,
  X,
  ChevronLeft,
  DollarSign,
  BarChart3,
  Users,
  Zap,
  Activity,
  Calendar,
  Bell,
  LogOut,
  User,
  Crown,
  Layers,
  Target,
  Sparkles,
  ChevronDown,
  Shield
} from 'lucide-react';
import { useAuth } from './Auth';
import { useNotifications } from './NotificationProvider';
import { WebSocketIndicator } from './WebSocketIndicator';
import { NotificationPanel } from './NotificationPanel';
import Avatar from './Avatar';

interface NavItem {
  name: string;
  href: string;
  icon: React.ElementType;
  badge?: string;
  requiresAuth?: boolean;
  requiresPro?: boolean;
}

const navigation: NavItem[] = [
  { name: 'Dashboard', href: '/dashboard', icon: Home, requiresAuth: true },
  { name: 'Live Betting', href: '/live-betting', icon: Activity, requiresAuth: true, badge: 'LIVE' },
  { name: 'YetAI Bets', href: '/predictions', icon: Brain, badge: 'AI' },
  { name: 'Place Bet', href: '/bet', icon: Target, requiresAuth: true },
  { name: 'Bet History', href: '/bets', icon: History, requiresAuth: true },
  { name: 'Parlays', href: '/parlays', icon: Layers, requiresAuth: true, badge: 'NEW' },
  { name: 'Fantasy', href: '/fantasy', icon: Trophy, requiresAuth: true },
  { name: 'Performance', href: '/performance', icon: BarChart3, requiresAuth: true },
  { name: 'AI Chat', href: '/chat', icon: MessageSquare, badge: 'BETA' },
  { name: 'Leaderboard', href: '/leaderboard', icon: Users },
];

const bottomNavigation: NavItem[] = [
  { name: 'Help & Support', href: '/help', icon: HelpCircle },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout, isAuthenticated } = useAuth();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  // Close mobile menu on route change
  useEffect(() => {
    setIsMobileOpen(false);
  }, [pathname]);

  const handleNavClick = (item: NavItem) => {
    if (item.requiresAuth && !isAuthenticated) {
      // Open login modal or redirect to login
      router.push('/?login=true');
      return;
    }
    router.push(item.href);
  };

  const isActive = (href: string) => pathname === href || pathname.startsWith(href + '/');

  return (
    <>
      {/* Mobile menu button */}
      <button
        onClick={() => setIsMobileOpen(!isMobileOpen)}
        className="lg:hidden fixed top-4 left-4 z-50 p-2 bg-white rounded-lg shadow-lg"
      >
        {isMobileOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
      </button>

      {/* Mobile overlay */}
      {isMobileOpen && (
        <div
          className="lg:hidden fixed inset-0 bg-black bg-opacity-50 z-40"
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div
        className={`
          fixed top-0 left-0 h-full bg-white border-r border-gray-200 z-40
          transition-all duration-300 ease-in-out
          ${isCollapsed ? 'w-20' : 'w-64'}
          ${isMobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}
      >
        {/* Logo Section */}
        <div className="flex items-center justify-between h-16 px-4 border-b border-gray-200">
          {!isCollapsed && (
            <div className="flex items-center space-x-2">
              <div className="w-8 h-8 rounded-lg overflow-hidden">
                <img 
                  src="/logo.png" 
                  alt="YetAI Logo" 
                  className="w-full h-full object-cover"
                />
              </div>
              <span className="text-xl font-bold bg-gradient-to-r from-[#A855F7] to-[#F59E0B] bg-clip-text text-transparent">
                YetAI
              </span>
            </div>
          )}
          {isCollapsed && (
            <div className="w-8 h-8 rounded-lg overflow-hidden">
              <img 
                src="/logo.png" 
                alt="YetAI Logo" 
                className="w-full h-full object-cover"
              />
            </div>
          )}
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="hidden lg:block p-1 hover:bg-gray-100 rounded"
          >
            <ChevronLeft className={`w-5 h-5 transition-transform ${isCollapsed ? 'rotate-180' : ''}`} />
          </button>
        </div>

        {/* User Section */}
        {isAuthenticated && user && (
          <div className={`px-4 py-4 border-b border-gray-200 ${isCollapsed ? 'px-2' : ''}`}>
            {isCollapsed ? (
              <div className="flex justify-center">
                <Avatar user={user} size="md" />
              </div>
            ) : (
              <div className="flex items-center space-x-3">
                <Avatar user={user} size="md" className="flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-900 truncate">
                    {user.first_name || user.username}
                  </p>
                  <div className="flex items-center space-x-1">
                    {user.subscription_tier !== 'free' && (
                      <Crown className={`w-3 h-3 ${
                        user.subscription_tier === 'elite' ? 'text-purple-600' : 'text-yellow-600'
                      }`} />
                    )}
                    <p className="text-xs text-gray-600 capitalize font-medium">
                      {user.subscription_tier} Member
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Navigation Items */}
        <nav className="flex-1 px-4 py-4 space-y-1 overflow-y-auto">
          {navigation.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            const locked = item.requiresAuth && !isAuthenticated;
            
            return (
              <button
                key={item.name}
                onClick={() => handleNavClick(item)}
                disabled={locked}
                className={`
                  w-full flex items-center justify-between px-3 py-2 rounded-lg
                  transition-all duration-200 group nav-item sidebar-nav
                  ${active
                    ? 'bg-[#A855F7]/10 text-[#A855F7] active'
                    : locked
                    ? 'text-gray-400 cursor-not-allowed opacity-60'
                    : 'text-gray-800 hover:bg-gray-50 hover:text-gray-900'
                  }
                  ${isCollapsed ? 'justify-center' : ''}
                `}
              >
                <div className="flex items-center space-x-3">
                  <Icon className={`w-5 h-5 ${active ? 'text-[#A855F7]' : ''}`} />
                  {!isCollapsed && (
                    <span className="text-sm font-medium">{item.name}</span>
                  )}
                </div>
                {!isCollapsed && item.badge && (
                  <span className={`
                    text-xs px-2 py-0.5 rounded-full font-medium
                    ${item.badge === 'AI' ? 'bg-[#A855F7]/10 text-[#A855F7]' :
                      item.badge === 'NEW' ? 'bg-[#FCD34D]/20 text-[#F59E0B]' :
                      item.badge === 'BETA' ? 'bg-[#FCD34D]/20 text-[#F59E0B]' :
                      'bg-gray-100 text-gray-700'}
                  `}>
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
          
          {/* Profile Navigation Item - Show for authenticated users */}
          {isAuthenticated && (
            <button
              onClick={() => router.push('/profile')}
              className={`
                w-full flex items-center justify-between px-3 py-2 rounded-lg
                transition-all duration-200 group nav-item sidebar-nav
                ${isActive('/profile')
                  ? 'bg-[#A855F7]/10 text-[#A855F7] active'
                  : 'text-gray-800 hover:bg-gray-50 hover:text-gray-900'
                }
                ${isCollapsed ? 'justify-center' : ''}
              `}
            >
              <div className="flex items-center space-x-3">
                <User className={`w-5 h-5 ${isActive('/profile') ? 'text-[#A855F7]' : ''}`} />
                {!isCollapsed && (
                  <span className="text-sm font-medium">Profile</span>
                )}
              </div>
            </button>
          )}
          
          {/* Admin Navigation Item - Only show for admin users */}
          {isAuthenticated && user?.is_admin && (
            <button
              onClick={() => router.push('/admin')}
              className={`
                w-full flex items-center justify-between px-3 py-2 rounded-lg
                transition-all duration-200 group nav-item sidebar-nav
                ${isActive('/admin')
                  ? 'bg-[#A855F7]/10 text-[#A855F7] active'
                  : 'text-gray-800 hover:bg-gray-50 hover:text-gray-900'
                }
                ${isCollapsed ? 'justify-center' : ''}
              `}
            >
              <div className="flex items-center space-x-3">
                <Shield className={`w-5 h-5 ${isActive('/admin') ? 'text-[#A855F7]' : ''}`} />
                {!isCollapsed && (
                  <span className="text-sm font-medium">Admin</span>
                )}
              </div>
              {!isCollapsed && (
                <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-red-100 text-red-600">
                  ADMIN
                </span>
              )}
            </button>
          )}
        </nav>

        {/* Bottom Section */}
        <div className="px-4 py-4 border-t border-gray-200 space-y-1">
          {bottomNavigation.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            const locked = item.requiresAuth && !isAuthenticated;
            
            return (
              <button
                key={item.name}
                onClick={() => handleNavClick(item)}
                disabled={locked}
                className={`
                  w-full flex items-center px-3 py-2 rounded-lg
                  transition-all duration-200
                  ${active
                    ? 'bg-[#A855F7]/10 text-[#A855F7]'
                    : locked
                    ? 'text-gray-400 cursor-not-allowed opacity-60'
                    : 'text-gray-800 hover:bg-gray-50 hover:text-gray-900'
                  }
                  ${isCollapsed ? 'justify-center' : ''}
                `}
              >
                <Icon className="w-5 h-5" />
                {!isCollapsed && (
                  <span className="ml-3 text-sm font-medium">{item.name}</span>
                )}
              </button>
            );
          })}
          
          {/* Logout Button */}
          {isAuthenticated && (
            <button
              onClick={logout}
              className={`
                w-full flex items-center px-3 py-2 rounded-lg
                text-red-600 hover:bg-red-50 transition-all duration-200
                ${isCollapsed ? 'justify-center' : ''}
              `}
            >
              <LogOut className="w-5 h-5" />
              {!isCollapsed && (
                <span className="ml-3 text-sm font-medium">Sign Out</span>
              )}
            </button>
          )}
        </div>

        {/* Upgrade Banner (for free users) */}
        {!isCollapsed && isAuthenticated && user?.subscription_tier === 'free' && (
          <div className="p-4 border-t border-gray-200">
            <div className="bg-gradient-to-r from-[#A855F7] to-[#F59E0B] rounded-lg p-4 text-white">
              <div className="flex items-center space-x-2 mb-2">
                <Sparkles className="w-5 h-5" />
                <span className="font-bold">Upgrade to Pro</span>
              </div>
              <p className="text-xs mb-3 opacity-90">
                Get AI insights, unlimited bets & more
              </p>
              <button
                onClick={() => router.push('/upgrade')}
                className="w-full bg-white text-[#A855F7] text-sm font-medium py-2 rounded-lg hover:bg-[#A855F7]/5 transition-colors"
              >
                Upgrade Now
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

export function Header() {
  const { user, isAuthenticated } = useAuth();
  const { unreadCount } = useNotifications();
  const router = useRouter();
  const [showNotifications, setShowNotifications] = useState(false);

  return (
    <header className="fixed top-0 right-0 left-0 lg:left-64 h-16 bg-white border-b border-gray-200 z-30">
      <div className="h-full px-4 flex items-center justify-between">
        {/* Left Section - Page Context */}
        <div className="flex items-center space-x-4">
          <div className="hidden lg:block">
            <h2 className="text-lg font-bold text-gray-900">
              AI Sports Betting Platform
            </h2>
            <p className="text-xs text-gray-600 font-medium">
              Real-time odds • AI predictions • Smart betting
            </p>
          </div>
        </div>

        {/* Right Section - Actions */}
        <div className="flex items-center space-x-4">
          {/* WebSocket Status Indicator */}
          <WebSocketIndicator />

          {/* Quick Bet Button */}
          {isAuthenticated && (
            <button
              onClick={() => router.push('/bet')}
              className="hidden sm:flex items-center space-x-2 px-4 py-2 bg-[#A855F7] text-white rounded-lg hover:bg-[#A855F7]/90 transition-colors"
            >
              <DollarSign className="w-4 h-4" />
              <span className="text-sm font-medium">Quick Bet</span>
            </button>
          )}

          {/* Notifications */}
          {isAuthenticated && (
            <div className="relative">
              <button
                onClick={() => setShowNotifications(!showNotifications)}
                className="relative p-2 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <Bell className="w-5 h-5 text-gray-600" />
                {unreadCount > 0 && (
                  <span className="absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white text-xs rounded-full flex items-center justify-center">
                    {unreadCount > 9 ? '9+' : unreadCount}
                  </span>
                )}
              </button>
              
              <NotificationPanel 
                isOpen={showNotifications}
                onClose={() => setShowNotifications(false)}
              />
            </div>
          )}

          {/* Login/Signup for non-authenticated users */}
          {!isAuthenticated && (
            <div className="flex items-center space-x-2">
              <button
                onClick={() => router.push('/?login=true')}
                className="px-4 py-2 text-gray-800 font-medium hover:bg-gray-100 rounded-lg transition-colors"
              >
                Sign In
              </button>
              <button
                onClick={() => router.push('/?signup=true')}
                className="px-4 py-2 bg-[#A855F7] text-white rounded-lg hover:bg-[#A855F7]/90 transition-colors"
              >
                Get Started
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

export function MobileBottomNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated } = useAuth();

  const mobileNav = [
    { name: 'Home', href: '/dashboard', icon: Home },
    { name: 'Live', href: '/live-betting', icon: Activity },
    { name: 'Bet', href: '/bet', icon: Target },
    { name: 'History', href: '/bets', icon: History },
    { name: 'More', href: '/profile', icon: Menu },
  ];

  return (
    <div className="lg:hidden fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 z-40">
      <div className="grid grid-cols-5 h-16">
        {mobileNav.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || pathname.startsWith(item.href + '/');
          
          return (
            <button
              key={item.name}
              onClick={() => {
                if ((item.href === '/bet' || item.href === '/bets' || item.href === '/dashboard' || item.href === '/live-betting' || item.href === '/profile') && !isAuthenticated) {
                  router.push('/?login=true');
                } else {
                  router.push(item.href);
                }
              }}
              className={`
                flex flex-col items-center justify-center space-y-1 font-medium
                ${active ? 'text-[#A855F7]' : 'text-gray-700'}
              `}
            >
              <Icon className="w-5 h-5" />
              <span className="text-xs">{item.name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}