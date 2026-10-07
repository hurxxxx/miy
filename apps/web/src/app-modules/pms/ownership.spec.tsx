import { expect, it, vi } from 'vitest';
import * as oldModule from './index';
import * as module from '@miy/official-suite-web/pms/module';
import * as oldPublic from './public-api';
import * as publicApi from '@miy/official-suite-web/pms';
import * as oldNavigation from '@/src/app-shell-navigation-model';
import * as navigation from '@miy/platform-web/routing/shell-navigation-model';
import { pmsMessages } from '@miy/official-suite-web/pms/messages';
import { resources } from '@/src/platform/i18n/resources';
import { pmsSidebarConfig } from './sidebar/config';
import { FloatingPmsWidget } from './views/FloatingPmsWidget';

vi.mock('@miy/official-suite-web/pms/views/PMSView', () => {
  throw new Error('eager PMS screen');
});
vi.mock('@miy/official-suite-web/pms/views/AssignedToMeView', () => {
  throw new Error('eager assigned tasks screen');
});
vi.mock('@miy/official-suite-web/pms/views/TodayOverdueView', () => {
  throw new Error('eager today tasks screen');
});

it('keeps the module, narrow public API and common navigation objects identical', () => {
  for (const [old, owner] of [
    [oldModule, module],
    [oldPublic, publicApi],
    [oldNavigation, navigation],
  ] as const) {
    expect(Object.keys(old).sort()).toEqual(Object.keys(owner).sort());
    for (const [key, value] of Object.entries(old))
      expect((owner as Record<string, unknown>)[key]).toBe(value);
  }
  expect(pmsSidebarConfig).toBe(module.pmsModule.sidebarConfig);
  expect(FloatingPmsWidget).toBe(module.FloatingPmsWidget);
  expect(oldModule.pmsToolElement).toBe(module.pmsToolElement);
});

it('composes identical owned PMS catalogs at both roots', () => {
  for (const locale of ['ko-KR', 'en-US'] as const)
    expect(resources[locale].apps.pms).toBe(pmsMessages[locale]);
});
