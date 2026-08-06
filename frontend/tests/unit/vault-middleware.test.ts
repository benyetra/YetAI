import { vaultSlugFromHost, VAULT_RESERVED_SUBDOMAINS } from '../../src/lib/vault-host';

describe('vaultSlugFromHost', () => {
  it('extracts slug from yetai.app subdomain', () => {
    expect(vaultSlugFromHost('mikes-hard.yetai.app')).toBe('mikes-hard');
  });

  it('ignores reserved subdomains', () => {
    for (const reserved of ['www', 'api', 'staging', 'staging-api']) {
      expect(VAULT_RESERVED_SUBDOMAINS.has(reserved)).toBe(true);
      expect(vaultSlugFromHost(`${reserved}.yetai.app`)).toBeNull();
    }
  });

  it('supports slug.localhost for local testing', () => {
    expect(vaultSlugFromHost('mikes-hard.localhost:3000')).toBe('mikes-hard');
  });

  it('returns null for apex and bare localhost', () => {
    expect(vaultSlugFromHost('yetai.app')).toBeNull();
    expect(vaultSlugFromHost('localhost:3000')).toBeNull();
  });
});
