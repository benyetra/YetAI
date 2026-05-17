import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Hosts that should be permanently redirected to yetai.app/predictions.
// Added in Development-5ly as part of the YetiBets domain retirement —
// once yetimonstah.com is pointed at this Vercel project (as a secondary
// custom domain), any incoming request with that host gets a 301 to the
// new predictions surface.
const RETIRED_HOSTS = new Set([
  'yetimonstah.com',
  'www.yetimonstah.com',
]);

export function middleware(req: NextRequest) {
  const host = req.headers.get('host')?.toLowerCase() ?? '';
  if (RETIRED_HOSTS.has(host)) {
    const url = req.nextUrl.clone();
    url.protocol = 'https:';
    url.host = 'yetai.app';
    // Preserve the path so legacy deep links (e.g. /mlb, /nfl/kickers) still
    // resolve to something useful on the new site rather than dumping users
    // on the home page. Map root → /predictions; anything else → /predictions/<path>.
    if (url.pathname === '/' || url.pathname === '') {
      url.pathname = '/predictions';
    } else {
      url.pathname = `/predictions${url.pathname}`;
    }
    return NextResponse.redirect(url, 301);
  }
  return NextResponse.next();
}

export const config = {
  // Run on all paths except Next internals and static assets so the redirect
  // catches every legacy link.
  matcher: ['/((?!_next/|favicon.ico|.*\\..*).*)'],
};
