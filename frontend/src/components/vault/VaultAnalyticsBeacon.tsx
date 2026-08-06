'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';

/**
 * Fires an anonymous page-view beacon attributed to the vault slug.
 * Used for pilot go/no-go metrics (reach / depth).
 */
export function VaultAnalyticsBeacon({ slug }: { slug: string }) {
  const pathname = usePathname() || '/';

  useEffect(() => {
    const base =
      process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '') ||
      (process.env.NODE_ENV === 'production'
        ? 'https://api.yetai.app'
        : 'http://localhost:8000');

    const body = JSON.stringify({
      path: pathname,
      event_type: 'page_view',
      referrer: typeof document !== 'undefined' ? document.referrer || null : null,
    });

    const url = `${base}/api/vault/${encodeURIComponent(slug)}/events`;
    try {
      if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
        const blob = new Blob([body], { type: 'application/json' });
        navigator.sendBeacon(url, blob);
        return;
      }
    } catch {
      /* fall through to fetch */
    }
    void fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {
      /* ignore beacon failures */
    });
  }, [slug, pathname]);

  return null;
}
