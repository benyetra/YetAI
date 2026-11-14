import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import YetaiBetsScreen from './YetaiBetsScreen';

test('0% today renders 0%, null renders em dash', () => {
  const { rerender } = render(<YetaiBetsScreen picks={[]} hitRate={0} />);
  expect(screen.getByText('0%')).toBeTruthy();
  rerender(<YetaiBetsScreen picks={[]} hitRate={null} />);
  expect(screen.queryByText('0%')).toBeNull();
});

test('failed fetch shows error with retry, not "no picks"', () => {
  const onRetry = jest.fn();
  render(<YetaiBetsScreen picks={[]} error="down" onRetry={onRetry} />);
  expect(screen.getByRole('alert').textContent).toContain('down');
  expect(screen.queryByText(/No picks available/)).toBeNull();
  fireEvent.click(screen.getByText('Retry'));
  expect(onRetry).toHaveBeenCalled();
});
