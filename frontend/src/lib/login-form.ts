/**
 * Read login credentials from the live form DOM.
 *
 * Safari (and other password managers) can autofill inputs without firing React
 * onChange, so controlled state may be empty while the fields look filled.
 * FormData reads the actual input values at submit time.
 */
export function readLoginFormValues(
  form: HTMLFormElement,
  fallback: { emailOrUsername?: string; password?: string } = {},
): { emailOrUsername: string; password: string } {
  const fd = new FormData(form);
  const emailOrUsername = String(
    fd.get('emailOrUsername') || fd.get('email') || fallback.emailOrUsername || '',
  ).trim();
  const password = String(fd.get('password') || fallback.password || '');
  return { emailOrUsername, password };
}
