'use client';

import { fmtMoney } from '@/lib/yetai-format';

export type BreakdownItem = {
  key: string;
  label: string;
  sublabel?: string;
  profit: number;
};

export default function BreakdownBars({ items }: { items: BreakdownItem[] }) {
  if (!items.length) {
    return <p className="dim" style={{ fontSize: 13 }}>No data for this period yet.</p>;
  }

  const total = items.reduce((sum, item) => sum + Math.abs(item.profit), 0) || 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {items.map((item) => {
        const pct = (Math.abs(item.profit) / total) * 100;
        return (
          <div key={item.key}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: 12.5,
                marginBottom: 5,
              }}
            >
              <span>
                {item.label}
                {item.sublabel ? (
                  <span className="dim mono" style={{ marginLeft: 6, fontSize: 11 }}>
                    {item.sublabel}
                  </span>
                ) : null}
              </span>
              <span
                className="mono"
                style={{
                  color:
                    item.profit > 0
                      ? 'var(--win)'
                      : item.profit < 0
                        ? 'var(--loss)'
                        : 'var(--text-3)',
                }}
              >
                {fmtMoney(item.profit, { signed: true })}
              </span>
            </div>
            <div style={{ height: 4, background: 'var(--surface-3)', borderRadius: 999 }}>
              <div
                style={{
                  height: '100%',
                  width: `${pct}%`,
                  background: 'var(--accent)',
                  borderRadius: 999,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
