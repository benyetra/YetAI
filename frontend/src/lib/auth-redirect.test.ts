import {
  isSafeReturnPath,
  resolvePostLoginRedirect,
  buildLoginUrl,
  stashOAuthReturnPath,
  consumeOAuthReturnPath,
  OAUTH_RETURN_PATH_KEY,
} from './auth-redirect';

describe('isSafeReturnPath', () => {
  it('allows relative app paths with query', () => {
    expect(isSafeReturnPath('/bets')).toBe(true);
    expect(isSafeReturnPath('/predictions?sport=mlb')).toBe(true);
  });

  it('rejects open redirects and auth pages', () => {
    expect(isSafeReturnPath('https://evil.com')).toBe(false);
    expect(isSafeReturnPath('//evil.com')).toBe(false);
    expect(isSafeReturnPath('/\\evil')).toBe(false);
    expect(isSafeReturnPath('/login')).toBe(false);
    expect(isSafeReturnPath('/signup')).toBe(false);
    expect(isSafeReturnPath('/')).toBe(false);
    expect(isSafeReturnPath('/auth/callback')).toBe(false);
    expect(isSafeReturnPath('/verify-email')).toBe(false);
    expect(isSafeReturnPath('/forgot-password')).toBe(false);
    expect(isSafeReturnPath('/reset-password')).toBe(false);
  });
});

describe('resolvePostLoginRedirect', () => {
  it('returns next when safe, else /dashboard', () => {
    expect(resolvePostLoginRedirect('/bets')).toBe('/bets');
    expect(resolvePostLoginRedirect('/login')).toBe('/dashboard');
    expect(resolvePostLoginRedirect(null)).toBe('/dashboard');
  });
});

describe('buildLoginUrl', () => {
  it('encodes next and optional reason', () => {
    expect(buildLoginUrl('/predictions?sport=mlb')).toBe(
      '/login?next=%2Fpredictions%3Fsport%3Dmlb',
    );
    expect(buildLoginUrl('/bets', { reason: 'expired' })).toBe(
      '/login?next=%2Fbets&reason=expired',
    );
  });

  it('omits next when path is unsafe', () => {
    expect(buildLoginUrl('/login')).toBe('/login');
  });
});

describe('oauth return path stash', () => {
  beforeEach(() => sessionStorage.clear());

  it('stashes safe paths and consume clears', () => {
    stashOAuthReturnPath('/bets');
    expect(sessionStorage.getItem(OAUTH_RETURN_PATH_KEY)).toBe('/bets');
    expect(consumeOAuthReturnPath()).toBe('/bets');
    expect(consumeOAuthReturnPath()).toBeNull();
  });

  it('does not stash unsafe paths', () => {
    stashOAuthReturnPath('/login');
    expect(consumeOAuthReturnPath()).toBeNull();
  });
});
