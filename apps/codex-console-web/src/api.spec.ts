import { afterEach, expect, it } from 'vitest';
import { consumeMIYSessionHandoff } from './api';

afterEach(() => window.history.replaceState(null, '', '/'));

it('consumes a valid miy handoff without retaining it in the URL', () => {
  const code = `cc1_${'a'.repeat(32)}`;
  window.history.replaceState(
    { preserved: true },
    '',
    `/?task=1#${new URLSearchParams({
      miy_issuer: 'https://dev.example.test',
      miy_code: code,
    })}`,
  );

  expect(consumeMIYSessionHandoff()).toEqual({
    issuer: 'https://dev.example.test',
    code,
  });
  expect(window.location.href).toBe('http://localhost:3000/?task=1');
  expect(window.history.state).toEqual({ preserved: true });
});

it('removes an invalid handoff and refuses to exchange it', () => {
  window.history.replaceState(null, '', '/#miy_issuer=x&miy_code=bad');
  expect(consumeMIYSessionHandoff()).toBeNull();
  expect(window.location.hash).toBe('');
});

it('consumes the existing portal handoff during separate console deployment', () => {
  const code = `cc1_${'a'.repeat(32)}`;
  window.history.replaceState(null, '', `/#mty_issuer=https://dev.example.test&mty_code=${code}`);
  expect(consumeMIYSessionHandoff()).toEqual({ issuer: 'https://dev.example.test', code });
  expect(window.location.hash).toBe('');
});

it('clears and refuses a handoff that mixes brands', () => {
  window.history.replaceState(null, '', `/#miy_issuer=https://dev.example.test&mty_code=cc1_${'a'.repeat(32)}`);
  expect(consumeMIYSessionHandoff()).toBeNull();
  expect(window.location.hash).toBe('');
});
