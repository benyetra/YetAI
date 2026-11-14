'use client';

import { useEffect, useState } from 'react';
import { getApiUrl } from '@/lib/api-config';
import { Activity, TrendingUp, Users } from 'lucide-react';

export interface PlatformStats {
  total_users: number;
  total_winnings: number;
  record: {
    label: string;
    stats: {
      win_rate: number | null;
      units: number;
      graded: number;
      won: number;
      lost: number;
    };
  } | null;
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
  const record = stats?.record ?? null;
  const rate = record?.stats.win_rate ?? null;
  const units = record?.stats.units ?? 0;

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
          <span>{rate === null ? '—' : `${rate.toFixed(1)}%`} win rate ({record?.label ?? 'no record yet'})</span>
        </div>
      </div>

      <div className="auth-stat-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Activity size={18} style={{ color: 'var(--accent)' }} />
            <h3 style={{ margin: 0 }}>{record?.label ?? 'Record'}</h3>
          </div>
          <span className="auth-stat-val" style={{ fontSize: 22 }}>
            {units >= 0 ? '+' : ''}
            {units.toLocaleString()}u
          </span>
        </div>
        <p className="auth-stat-sub">
          {record ? record.stats.graded : 0} graded · {record ? `${record.stats.won}W ${record.stats.lost}L` : '—'}
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
              width: `${Math.min(rate ?? 0, 100)}%`,
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
