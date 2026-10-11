import { APP_CONTRACTS, OFFICIAL_APP_IDS } from '@miy/contracts/app-contracts';
import { getAppRoutePattern } from '@miy/contracts/app-routes';
import { createCoreAppModuleRegistry } from '@miy/core-web/app-registry';
import { describe, expect, it } from 'vitest';
import {
  OFFICIAL_APP_MANIFESTS,
  OFFICIAL_HELP_GUIDES,
  getPmsHelpGuideSrc,
} from './index';

describe('official UI metadata', () => {
  it('preserves the official contract order without admitting unregistered route implementations', () => {
    expect(
      OFFICIAL_APP_MANIFESTS.map((manifest) => manifest.appBarItem.id),
    ).toEqual(OFFICIAL_APP_IDS);
    expect(() => createCoreAppModuleRegistry(OFFICIAL_APP_MANIFESTS)).toThrow(
      'but not registered',
    );
  });

  it.each(OFFICIAL_APP_MANIFESTS)(
    'keeps $appBarItem.id declared routes inside its canonical contract',
    (manifest) => {
      const contract = APP_CONTRACTS.find(
        (app) => app.app_id === manifest.appBarItem.id,
      );
      if (!contract)
        throw new Error(`Missing app contract: ${manifest.appBarItem.id}`);
      const paths = new Set(
        contract.routes.map((route) => getAppRoutePattern(route.route_id)),
      );
      for (const path of [
        ...manifest.appRoutePaths,
        ...(manifest.globalRoutePaths ?? []),
      ]) {
        expect(paths.has(path), `${manifest.appBarItem.id}: ${path}`).toBe(
          true,
        );
      }
    },
  );

  it('preserves suite help selection, document path and locale section', () => {
    expect(OFFICIAL_HELP_GUIDES.map((guide) => guide.key)).toEqual(['pms']);
    expect(OFFICIAL_HELP_GUIDES[0]).toMatchObject({
      routePath: '/help/pms',
      src: '/help/pms/user-guide.html',
    });
    expect(getPmsHelpGuideSrc('ko-KR')).toBe('/help/pms/user-guide.html');
    expect(getPmsHelpGuideSrc('en-US')).toBe(
      '/help/pms/user-guide.html#english',
    );
    expect(getPmsHelpGuideSrc(undefined)).toBe('/help/pms/user-guide.html');
  });
});
