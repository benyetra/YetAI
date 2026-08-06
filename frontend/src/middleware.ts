import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { vaultSlugFromHost } from './lib/vault-host';

const RETIRED_HOSTS = new Set([
  'yetimonstah.com',
  'www.yetimonstah.com',
]);

export { vaultSlugFromHost, VAULT_RESERVED_SUBDOMAINS } from './lib/vault-host';

export function middleware(req: NextRequest) {
  const host = req.headers.get('host')?.toLowerCase() ?? '';
  if (RETIRED_HOSTS.has(host.split(':')[0])) {
    const url = req.nextUrl.clone();
    url.protocol = 'https:';
    url.host = 'yetai.app';
    if (url.pathname === '/' || url.pathname === '') {
      url.pathname = '/predictions';
    } else {
      url.pathname = `/predictions${url.pathname}`;
    }
    return NextResponse.redirect(url, 301);
  }

  const slug = vaultSlugFromHost(host);
  if (slug) {
    const url = req.nextUrl.clone();
    if (
      url.pathname === `/vault/${slug}` ||
      url.pathname.startsWith(`/vault/${slug}/`)
    ) {
      return NextResponse.next();
    }
    const suffix = url.pathname === '/' ? '' : url.pathname;
    url.pathname = `/vault/${slug}${suffix}`;
    return NextResponse.rewrite(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|gif|svg|webp|ico|css|js|woff2?)$).*)',
  ],
};
