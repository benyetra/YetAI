'use client';

import { useEffect, useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { Activity, TrendingUp, Users } from 'lucide-react';

export interface PlatformStats {
  total_users: number;
  total_winnings: number;
  performance_30d: {
    win_rate: number;
    profit: number;
    total_bets: number;
    wins: number;
    losses: number;
  };
  performance_7d: {
    win_rate: number;
    profit: number;
    wow_change: number;
  };
  user_avatars: Array<{ url: string; name: string }>;
}

export function usePlatformStats() {
  const [stats, setStats] = useState<PlatformStats | null>(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const response = await fetch(getApiUrl('/api/platform/stats'));
        const data = await response.json();
        if (data.status === 'success') setStats(data.data);
      } catch {
        /* optional panel */
      }
    };
    fetchStats();
  }, []);

  return stats;
}

export default function AuthPlatformStats() {
  const stats = usePlatformStats();

  return (
    <div className="auth-hero-inner">
      <div className="auth-stat-card">
        <h3>Total Winnings</h3>
        <div className="auth-stat-val">
          ${stats ? stats.total_winnings.toLocaleString() : '0'}
        </div>
        <p className="auth-stat-sub">From YetAI Bets</p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12, fontSize: 12, color: 'var(--text-2)' }}>
          <TrendingUp size={14} style={{ color: 'var(--win)' }} />
          <span>{stats ? stats.performance_30d.win_rate.toFixed(1) : '0'}% win rate (30d)</span>
        </div>
      </div>

      <div className="auth-stat-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Activity size={18} style={{ color: 'var(--accent)' }} />
            <h3 style={{ margin: 0 }}>30-day performance</h3>
          </div>
          <span className="auth-stat-val" style={{ fontSize: 22 }}>
            {stats && stats.performance_30d.profit >= 0 ? '+' : ''}
            ${stats ? stats.performance_30d.profit.toLocaleString() : '0'}
          </span>
        </div>
        <p className="auth-stat-sub">
          {stats ? stats.performance_30d.total_bets : 0} bets · WoW{' '}
          {stats && stats.performance_7d.wow_change >= 0 ? '+' : ''}
          {stats ? stats.performance_7d.wow_change.toFixed(1) : '0'}%
        </p>
        <div
          style={{
            marginTop: 12,
            height: 4,
            borderRadius: 999,
            background: 'var(--surface-3)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${stats ? Math.min(stats.performance_30d.win_rate, 100) : 0}%`,
              background: 'linear-gradient(90deg, var(--accent), var(--win))',
              borderRadius: 999,
            }}
          />
        </div>
      </div>

      <div className="auth-stat-card">
        <Users size={18} style={{ color: 'var(--accent)', marginBottom: 8 }} />
        <div className="auth-stat-val" style={{ fontSize: 20 }}>
          {stats ? stats.total_users.toLocaleString() : '0'}
        </div>
        <p className="auth-stat-sub">Registered users</p>
      </div>

      {stats && stats.user_avatars.length > 0 ? (
        <div style={{ display: 'flex', justifyContent: 'center', gap: 0 }}>
          <div style={{ display: 'flex' }}>
            {stats.user_avatars.slice(0, 5).map((u, i) => (
              <img
                key={i}
                src={u.url}
                alt={u.name}
                title={u.name}
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: '50%',
                  border: '2px solid var(--bg)',
                  marginLeft: i > 0 ? -10 : 0,
                  objectFit: 'cover',
                }}
              />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
