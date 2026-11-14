import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import AdminYetaiBetsManage from './AdminYetaiBetsManage';

const mk = (id: string, status: string) => ({
  id, sport: 'nba', game: 'A @ B', pick: `pick-${id}`, odds: '-110',
  bet_type: 'spread', bet_category: 'straight', status,
});

const bets = [mk('a', 'active'), mk('w', 'won'), mk('p', 'pending_approval')];

let fetchMock: jest.Mock;
beforeEach(() => {
  fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST' || init?.method === 'DELETE') {
      return { ok: false, status: 409, json: async () => ({ detail: 'Nope, shown to users' }) };
    }
    return { ok: true, json: async () => ({ bets }) };
  });
  (global as unknown as { fetch: unknown }).fetch = fetchMock;
  window.confirm = jest.fn(() => true);
});

const rowOf = (pick: string) => screen.getByText(pick).closest('tr') as HTMLElement;

test('action depends on status', async () => {
  render(<AdminYetaiBetsManage />);
  await screen.findByText('pick-a');
  expect(rowOf('pick-a').textContent).toContain('Pull');
  expect(rowOf('pick-a').textContent).not.toContain('Delete');
  expect(rowOf('pick-w').textContent).not.toMatch(/Pull|Delete/);
  expect(rowOf('pick-p').textContent).toContain('Delete');
});

test('pull posts to /reject and shows backend detail', async () => {
  render(<AdminYetaiBetsManage />);
  await screen.findByText('pick-a');
  fireEvent.click(rowOf('pick-a').querySelector('button')!);
  await waitFor(() => expect(screen.getByText('Nope, shown to users')).toBeTruthy());
  const call = fetchMock.mock.calls.find(([, i]) => i?.method === 'POST')!;
  expect(call[0]).toContain('/api/admin/yetai-picks/a/reject');
});
