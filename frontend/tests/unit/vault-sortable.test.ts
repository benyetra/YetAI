import { compareVaultSortValues } from '../../src/components/vault/VaultSortableTable';

describe('compareVaultSortValues', () => {
  it('sorts numbers and strings with numeric awareness', () => {
    expect(compareVaultSortValues(2, 10, 'asc')).toBeLessThan(0);
    expect(compareVaultSortValues(2, 10, 'desc')).toBeGreaterThan(0);
    expect(compareVaultSortValues('wk 2', 'wk 10', 'asc')).toBeLessThan(0);
    expect(compareVaultSortValues('Alice', 'Bob', 'asc')).toBeLessThan(0);
  });

  it('pushes empty values to the end in either direction', () => {
    expect(compareVaultSortValues(null, 3, 'asc')).toBeGreaterThan(0);
    expect(compareVaultSortValues(null, 3, 'desc')).toBeGreaterThan(0);
    expect(compareVaultSortValues('', 'A', 'asc')).toBeGreaterThan(0);
  });
});
