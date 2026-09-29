import { afterEach, expect, it } from 'vitest';
import { consumeMTYSessionHandoff } from './api';

afterEach(() => window.history.replaceState(null, '', '/'));

it('consumes a valid MTY handoff without retaining it in the URL', () => {
  const code = `cc1_${'a'.repeat(32)}`;
  window.history.replaceState(
    { preserved: true },
    '',
    `/?task=1#${new URLSearchParams({
      mty_issuer: 'https://dev.example.test',
      mty_code: code,
    })}`,
  );

  expect(consumeMTYSessionHandoff()).toEqual({
    issuer: 'https://dev.example.test',
    code,
  });
  expect(window.location.href).toBe('http://localhost:3000/?task=1');
  expect(window.history.state).toEqual({ preserved: true });
});

it('removes an invalid handoff and refuses to exchange it', () => {
  window.history.replaceState(null, '', '/#mty_issuer=x&mty_code=bad');
  expect(consumeMTYSessionHandoff()).toBeNull();
  expect(window.location.hash).toBe('');
});
