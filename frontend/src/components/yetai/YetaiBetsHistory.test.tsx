import React from 'react';
import { render, screen } from '@testing-library/react';
import YetaiBetsHistory, { type YetaiHistoryBet } from './YetaiBetsHistory';

const base = { odds: -110, confidence: 70, sport: 'nba', game: 'A @ B' };
const stats = { period_days: 90, total: 1, won: 1, lost: 0, pushed: 0, win_rate: 100, units: 0.9 };

function renderBets(bets: YetaiHistoryBet[]) {
  return render(<YetaiBetsHistory bets={bets} stats={stats} />);
}

test('void row shows Void and its reason, record unchanged', () => {
  renderBets([{ ...base, id: '1', pick: 'Lakers -3', status: 'void', result: 'Game postponed' }]);
  expect(screen.getByText('Void')).toBeTruthy();
  expect(screen.getByText('Game postponed')).toBeTruthy();
  expect(screen.getByText('1W · 0L')).toBeTruthy();
  expect(screen.queryByText('pending')).toBeNull();
});

test('parlay row lists legs with statuses', () => {
  renderBets([
    {
      ...base,
      id: '2',
      pick: '2-leg parlay',
      status: 'lost',
      parlay_legs: [
        { pick: 'Celtics ML', odds: -150, leg_status: 'won' },
        { pick: 'Over 220.5', odds: -110, leg_status: 'void', leg_result: 'Postponed' },
      ],
    },
  ]);
  const legs = screen.getAllByTestId('parlay-leg');
  expect(legs).toHaveLength(2);
  expect(legs[0].textContent).toContain('won');
  expect(legs[1].textContent).toContain('void');
  expect(legs[1].textContent).toContain('Postponed');
});

test('win rate null renders em dash, 0 renders 0%', () => {
  const { rerender } = render(
    <YetaiBetsHistory bets={[]} stats={{ ...stats, total: 1, won: 0, lost: 0, win_rate: null }} />,
  );
  expect(screen.getByText('—')).toBeTruthy();
  rerender(<YetaiBetsHistory bets={[]} stats={{ ...stats, win_rate: 0 }} />);
  expect(screen.getByText('0%')).toBeTruthy();
});
