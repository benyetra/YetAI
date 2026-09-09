import { readLoginFormValues } from './login-form';

function makeForm(fields: Record<string, string>): HTMLFormElement {
  const form = document.createElement('form');
  for (const [name, value] of Object.entries(fields)) {
    const input = document.createElement('input');
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }
  return form;
}

describe('readLoginFormValues', () => {
  it('prefers DOM values over stale React state (Safari autofill)', () => {
    const form = makeForm({
      emailOrUsername: 'ben@yetai.app',
      password: 'correct-horse',
    });
    expect(
      readLoginFormValues(form, { emailOrUsername: '', password: '' }),
    ).toEqual({
      emailOrUsername: 'ben@yetai.app',
      password: 'correct-horse',
    });
  });

  it('trims the identifier and accepts an email field name', () => {
    const form = makeForm({
      email: '  Ben@YetAI.app  ',
      password: 'secret',
    });
    expect(readLoginFormValues(form)).toEqual({
      emailOrUsername: 'Ben@YetAI.app',
      password: 'secret',
    });
  });
});
