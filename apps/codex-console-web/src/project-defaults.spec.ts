import { expect, it } from 'vitest';
import { localAppRepository, suggestAppId } from './project-defaults';

it('suggests stable valid identifiers for Korean work names and distinguishes other work', () => {
  const title = '장비·비품 관리';
  const suggested = suggestAppId(title, []);
  expect(suggested).toMatch(/^[a-z][a-z0-9-]{1,63}$/);
  expect(suggestAppId(title, [])).toBe(suggested);
  expect(suggestAppId('장비 반출 신청', [])).not.toBe(suggested);
});

it('keeps numeric and long names valid and chooses an unoccupied identifier', () => {
  const title = '123 equipment '.repeat(30);
  const previous = suggestAppId(title, []);
  const occupied = [previous, `${previous}-2`];
  const next = suggestAppId(title, occupied);
  expect(next).toMatch(/^[a-z][a-z0-9-]{1,63}$/);
  expect(occupied).not.toContain(next);
  expect(suggestAppId(title, occupied)).toBe(next);
});

it('uses a reserved local HTTPS identity without declaring a hosted Git remote', () => {
  const url = new URL(localAppRepository('equipment-app'));
  expect(url.protocol).toBe('https:');
  expect(url.hostname).toBe('miy-apps.invalid');
  expect(url.pathname).toBe('/local/equipment-app.git');
  expect(url.username + url.password + url.search + url.hash).toBe('');
});
