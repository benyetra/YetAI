/** Apex / infra hosts that must never be treated as vault slugs. */
export const VAULT_RESERVED_SUBDOMAINS = new Set([
  'www',
  'api',
  'staging',
  'staging-api',
  'app',
  'admin',
  'assets',
  'cdn',
  'localhost',
]);

/**
 * Extract vault slug from Host header.
 * `mikes-hard.yetai.app` → `mikes-hard`
 * `mikes-hard.localhost:3000` → `mikes-hard` (local multi-tenant testing)
 */
export function vaultSlugFromHost(hostHeader: string | null): string | null {
  if (!hostHeader) return null;
  const host = hostHeader.toLowerCase().split(':')[0];
  if (!host || host === 'yetai.app' || host === 'localhost' || host === '127.0.0.1') {
    return null;
  }
  const parts = host.split('.');
  if (parts.length >= 3 && parts.slice(-2).join('.') === 'yetai.app') {
    const slug = parts[0];
    if (!slug || VAULT_RESERVED_SUBDOMAINS.has(slug)) return null;
    return slug;
  }
  if (parts.length === 2 && parts[1] === 'localhost') {
    const slug = parts[0];
    if (!slug || VAULT_RESERVED_SUBDOMAINS.has(slug)) return null;
    return slug;
  }
  return null;
}
