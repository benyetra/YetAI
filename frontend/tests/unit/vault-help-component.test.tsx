import { fireEvent, render, screen } from '@testing-library/react';
import { VaultHelp, VaultLabelWithHelp } from '../../src/components/vault/VaultHelp';

describe('VaultHelp', () => {
  it('toggles an accessible tooltip', () => {
    render(<VaultHelp text="All-play ignores schedule strength." label="About all-play" />);
    const trigger = screen.getByRole('button', { name: 'About all-play' });
    expect(screen.queryByRole('tooltip')).toBeNull();
    fireEvent.click(trigger);
    expect(screen.getByRole('tooltip')).toHaveTextContent('All-play ignores schedule strength.');
    fireEvent.click(trigger);
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('renders label help only when provided', () => {
    const { rerender } = render(<VaultLabelWithHelp>Luck</VaultLabelWithHelp>);
    expect(screen.queryByRole('button')).toBeNull();
    rerender(
      <VaultLabelWithHelp help="Schedule luck vs all-play." helpLabel="About luck">
        Luck
      </VaultLabelWithHelp>,
    );
    expect(screen.getByRole('button', { name: 'About luck' })).toBeInTheDocument();
  });
});
