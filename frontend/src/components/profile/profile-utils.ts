export type AuthUser = {
  id?: number;
  email?: string;
  username?: string;
  first_name?: string;
  last_name?: string;
  avatar_url?: string;
  subscription_tier?: string;
  subscription_status?: string;
  subscription_current_period_end?: string;
  is_verified?: boolean;
  is_admin?: boolean;
  created_at?: string;
};

export function profileInitials(user: AuthUser | null | undefined): string {
  const first = user?.first_name?.trim()?.[0] ?? '';
  const last = user?.last_name?.trim()?.[0] ?? '';
  const fromName = `${first}${last}`.toUpperCase();
  if (fromName) return fromName;
  const fromUsername = user?.username?.slice(0, 2).toUpperCase();
  if (fromUsername) return fromUsername;
  return '??';
}

export function subscriptionTierLabel(tier?: string): string {
  if (!tier) return 'Member';
  const normalized = tier.toLowerCase();
  if (normalized === 'pro') return 'Pro Member';
  if (normalized === 'elite') return 'Elite Member';
  if (normalized === 'free') return 'Free Member';
  return `${tier.charAt(0).toUpperCase()}${tier.slice(1)} Member`;
}

export function formatMemberSince(user: AuthUser | null | undefined): string {
  const raw = user?.created_at;
  if (!raw) return '—';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
}

export function planDisplayName(tier?: string): string {
  if (!tier) return '—';
  const normalized = tier.toLowerCase();
  if (normalized === 'free') return 'Free';
  if (normalized === 'pro') return 'Pro';
  if (normalized === 'elite') return 'Elite';
  return tier.charAt(0).toUpperCase() + tier.slice(1);
}
