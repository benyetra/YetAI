import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import YetaiBetsView from './YetaiBetsView';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/components/Auth', () => {
  const auth = { isAuthenticated: true, loading: false, user: { id: 1 } }; // stable: the view effect depends on it
  return { useAuth: () => auth };
});
jest.mock('@/components/YetAIBetModal', () => ({ __esModule: true, default: () => null }));

const pick = {
  id: 'p1',
  sport: 'NBA',
  game: 'Celtics @ Lakers',
  bet_type: 'spread',
  pick: 'Celtics -3.5',
  odds: '-110',
  confidence: 72,
  reasoning: 'model likes it',
  status: 'pending',
  is_premium: false,
  game_time: '7:30 PM',
};

function mockFetch(live: { ok: boolean }, history: { ok: boolean }) {
  (global as any).fetch = jest.fn((url: string) => {
    const isHistory = String(url).includes('/history');
    const ok = isHistory ? history.ok : live.ok;
    return Promise.resolve({
      ok,
      status: ok ? 200 : 500,
      json: () => Promise.resolve(isHistory ? { bets: [], stats: null } : { bets: [pick] }),
    });
  });
}

beforeEach(() => {
  jest.spyOn(console, 'error').mockImplementation(() => {});
});

test('history failure still shows live picks; error only on the history tab', async () => {
  mockFetch({ ok: true }, { ok: false });
  render(<YetaiBetsView />);
  await waitFor(() => expect(screen.getAllByText(/Celtics -3\.5/).length).toBeGreaterThan(0));
  expect(screen.queryByRole('alert')).toBeNull();
  fireEvent.click(screen.getByText('History'));
  expect((await screen.findByRole('alert')).textContent).toContain('temporarily unavailable');
});

test('live failure shows the error on the live tab and keeps history reachable', async () => {
  mockFetch({ ok: false }, { ok: true });
  render(<YetaiBetsView />);
  expect((await screen.findByRole('alert')).textContent).toContain('temporarily unavailable');
  fireEvent.click(screen.getByText('History'));
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
});
