import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  clearMatomoUser,
  identifyMatomoUser,
  installMatomoTracking,
  resolveMatomoTrackingConfig,
  trackMatomoPageView,
  type InstalledMatomoTracking,
} from './matomo';

let installedTracking: InstalledMatomoTracking | null = null;

afterEach(() => {
  installedTracking?.cleanup();
  installedTracking = null;
  vi.useRealTimers();
  document.head.innerHTML = '';
  document.body.innerHTML = '';
  delete (window as typeof window & { _paq?: unknown })._paq;
  window.history.replaceState({}, '', '/');
});

describe('Matomo tracking configuration', () => {
  it('uses the miy Matomo server for production hosts', () => {
    expect(
      resolveMatomoTrackingConfig({}, { hostname: 'miy.example' }),
    ).toMatchObject({
      siteId: '1',
      trackerBaseUrl: 'https://matomo.miy.example/',
    });
  });

  it('does not track dev or localhost by default', () => {
    expect(
      resolveMatomoTrackingConfig(
        {},
        { hostname: 'dev.miy.example' },
      ),
    ).toBeNull();
    expect(
      resolveMatomoTrackingConfig({}, { hostname: 'localhost' }),
    ).toBeNull();
  });

  it('can be disabled explicitly', () => {
    expect(
      resolveMatomoTrackingConfig(
        { VITE_MIY_MATOMO_ENABLED: 'false' },
        { hostname: 'miy.example' },
      ),
    ).toBeNull();
  });
});

describe('Matomo tracker installation', () => {
  it('installs the Matomo script and queues the base tracker settings', () => {
    window.history.replaceState({}, '', '/apps/home');
    document.title = 'miy Home';

    installedTracking = installMatomoTracking(
      { VITE_MIY_MATOMO_ALLOWED_HOSTS: 'localhost' },
      window,
    );

    expect(installedTracking).not.toBeNull();
    expect(window._paq).toEqual([
      ['setTrackerUrl', 'https://matomo.miy.example/matomo.php'],
      ['setSiteId', '1'],
      ['enableLinkTracking'],
    ]);
    expect(
      document
        .querySelector('script#miy-matomo-tracker')
        ?.getAttribute('src'),
    ).toBe('https://matomo.miy.example/matomo.js');
  });

  it('tracks shell route context once per page key', () => {
    window.history.replaceState({}, '', '/apps/home');

    installedTracking = installMatomoTracking(
      { VITE_MIY_MATOMO_ALLOWED_HOSTS: 'localhost' },
      window,
    );
    window._paq?.splice(0);

    window.history.pushState({}, '', '/apps/docs');
    trackMatomoPageView(
      {
        appId: 'collaboration:docs-main',
        appRoute: '/apps/docs',
      },
      window,
    );
    trackMatomoPageView(
      {
        appId: 'collaboration:docs-main',
        appRoute: '/apps/docs',
      },
      window,
    );

    expect(window._paq).toEqual([
      ['setCustomUrl', 'http://localhost:3000/apps/docs'],
      ['setDocumentTitle', document.title],
      ['setCustomDimension', 2, 'collaboration:docs-main'],
      ['setCustomDimension', 3, '/apps/docs'],
      ['trackPageView'],
    ]);
  });

  it('sets the logged-in user id, login id, and name for later page views', () => {
    installedTracking = installMatomoTracking(
      { VITE_MIY_MATOMO_ALLOWED_HOSTS: 'localhost' },
      window,
    );
    window._paq?.splice(0);

    identifyMatomoUser(
      {
        userId: 'member',
        userLoginId: 'member',
        userName: 'miy Member',
      },
      window,
    );
    clearMatomoUser(window);

    expect(window._paq).toEqual([
      ['setUserId', 'member'],
      ['setCustomDimension', 4, 'member'],
      ['setCustomDimension', 1, 'miy Member'],
      ['resetUserId'],
      ['deleteCustomDimension', 1],
      ['deleteCustomDimension', 4],
    ]);
  });

  it('does not install twice', () => {
    const env = { VITE_MIY_MATOMO_ALLOWED_HOSTS: 'localhost' };

    installedTracking = installMatomoTracking(env, window);

    expect(installMatomoTracking(env, window)).toBeNull();
    expect(
      document.querySelectorAll('script#miy-matomo-tracker'),
    ).toHaveLength(1);
  });
});
