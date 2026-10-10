import { describe, expect, it } from 'vitest';
import { OFFICIAL_APP_MANIFESTS } from '@miy/official-suite-web';
import { communityModule } from '@miy/official-suite-web/community/module';
import ownership from '../ownership.json';
import type { AuthUser } from '@miy/web-official-suite-bridge';
import {
  OFFICIAL_APP_IDS,
  officialRegistry,
  resolveOfficialShellState,
} from './registry';

const member: AuthUser = {
  id: 'member',
  login_id: 'member',
  email: 'member@example.test',
  full_name: 'Member',
  display_name: 'Member',
  employee_code: null,
  job_title: null,
  primary_organization_unit: null,
  status: 'active',
  login_blocked: false,
  theme_preference: 'system',
  locale: 'ko-KR',
  time_zone: 'Asia/Seoul',
  date_format: 'korean',
  app_bar_layout: { pinned_app_ids: [] },
  system_roles: [],
  group_ids: [],
  managed_organization_unit_ids: [],
  is_department_head: false,
  must_change_password: false,
  last_login_at: null,
  created_at: '2026-10-06T00:00:00Z',
  updated_at: '2026-10-06T00:00:00Z',
};

describe('official suite composition', () => {
  it('composes precisely the owned public business modules', () => {
    expect(officialRegistry.APP_MODULE_MANIFESTS).toEqual(
      OFFICIAL_APP_MANIFESTS,
    );
    expect(OFFICIAL_APP_IDS).toEqual(ownership.ui_app_ids);
    expect(
      officialRegistry.APP_MODULE_MANIFESTS.map((item) => item.appBarItem.id),
    ).toEqual(OFFICIAL_APP_IDS);
    expect(officialRegistry.APP_BACKGROUND_WORK_SOURCES).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          appId: 'bento',
          id: 'bento-ai',
          requiredNavItemId: 'bento-all',
        }),
      ]),
    );
    expect(officialRegistry.APP_ROUTES.length).toBeGreaterThan(0);
    expect(officialRegistry.getAppModuleGlobalRoutes('community')).toEqual(
      communityModule.globalRoutes.map((route) => ({
        ...route,
        appId: 'community',
      })),
    );
    expect(
      officialRegistry.APP_ROUTES.every((route) =>
        ownership.ui_app_ids.includes(route.appId),
      ),
    ).toBe(true);
  });
  it('preserves admitted application deep links and selected navigation', () => {
    expect(
      resolveOfficialShellState('/apps/docs?view=mine', member, ['docs']),
    ).toEqual({ activeAppId: 'docs', activeNavItemId: 'docs-my' });
    expect(
      resolveOfficialShellState('/apps/pms/assigned', member, ['pms']),
    ).toEqual({ activeAppId: 'pms', activeNavItemId: 'pms-tasks-assigned' });
  });
  it.each([
    ['/apps/pms/lists/demo', 'pms-list-demo'],
    ['/apps/pms/lists/list-1', 'pms-list-list-1'],
    ['/apps/pms/spaces/space-1/docs/doc-1', 'pms-space-space-1-docs-doc-1'],
  ])(
    'preserves official PMS deep-link navigation for %s',
    (path, activeNavItemId) => {
      expect(resolveOfficialShellState(path, member, ['pms'])).toEqual({
        activeAppId: 'pms',
        activeNavItemId,
      });
    },
  );
  it('does not turn platform admission into registration in another UI root', () => {
    for (const path of [
      '/apps/agent-terminal',
      '/apps/codex-console',
      '/apps/tetris',
      '/admin/people',
    ]) {
      expect(
        resolveOfficialShellState(path, member, [
          'agent-terminal',
          'codex-console',
          'tetris',
        ]),
      ).toEqual({ activeAppId: 'launcher', activeNavItemId: '' });
    }
    expect(resolveOfficialShellState('/apps/docs', member, [])).toEqual({
      activeAppId: 'launcher',
      activeNavItemId: '',
    });
    expect(resolveOfficialShellState('/apps/docs', null, ['docs'])).toEqual({
      activeAppId: 'launcher',
      activeNavItemId: '',
    });
  });
});
