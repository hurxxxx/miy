import { expect, it } from 'vitest';
import { taskListRoleAllows } from './pms-permissions';
it.each([null, undefined, 'unknown', '', 'VIEWER'])(
  'does not allow unrecognized role %s',
  (role) => {
    expect(taskListRoleAllows(role, 'viewer')).toBe(false);
  },
);
it('preserves member/editor equality and the ordered UI affordance', () => {
  expect(taskListRoleAllows('viewer', 'member')).toBe(false);
  expect(taskListRoleAllows('member', 'editor')).toBe(true);
  expect(taskListRoleAllows('editor', 'member')).toBe(true);
  expect(taskListRoleAllows('admin', 'owner')).toBe(false);
  expect(taskListRoleAllows('owner', 'admin')).toBe(true);
});
