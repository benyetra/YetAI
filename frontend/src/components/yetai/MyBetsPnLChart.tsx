'use client';

import { fmtMoney } from '@/lib/yetai-format';

type MyBetsPnLChartProps = {
  data: number[];
  periodLabel?: string;
  dayCount?: number;
};

export default function MyBetsPnLChart({
  data,
  periodLabel = 'last 14 days',
  dayCount = 14,
}: MyBetsPnLChartProps) {
  const history = data.length > 0 ? data : Array(dayCount).fill(0);
  const max = Math.max(...history.map(Math.abs), 1);
  const total = history.reduce((sum, v) => sum + v, 0);
  const totalLabel = `${dayCount}-day P&L`;

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="section-head" style={{ marginBottom: 8 }}>
        <div>
          <div className="section-title">P&L · {periodLabel}</div>
          <div className="section-sub">Daily profit/loss by settlement date</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div
            className="mono"
            style={{
              fontSize: 22,
              fontWeight: 500,
              color: total >= 0 ? 'var(--win)' : 'var(--loss)',
            }}
          >
            {fmtMoney(total, { signed: true })}
          </div>
          <div className="section-sub">{totalLabel}</div>
        </div>
      </div>
      <div className="pnl-chart-bars">
        {history.map((v, i) => {
          const pct = Math.max(2, (Math.abs(v) / max) * 50);
          const barClass =
            v > 0 ? 'win above' : v < 0 ? 'loss below' : 'zero';
          return (
            <div key={i} className="chart-bar-col">
              <div
                className={`chart-bar ${barClass}`}
                style={{ height: `${pct}%` }}
                title={`Day ${i + 1}: ${fmtMoney(v, { signed: true })}`}
              />
            </div>
          );
        })}
      </div>
      <div className="chart-axis">
        <span>Start</span>
        <span>Mid</span>
        <span>Today</span>
      </div>
    </div>
  );
}
