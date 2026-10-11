import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAppsBootstrap, type AppsBootstrapResponse } from './apps-api';
import {
  getIndependentApps,
  type IndependentApp,
} from './independent-apps-api';
import { resolveIndependentNavigation } from './independent-app-navigation';
import type { IndependentNavigationTarget } from './independent-app-host';
vi.mock('./apps-api', () => ({ getAppsBootstrap: vi.fn() }));
vi.mock('./independent-apps-api', () => ({
  getIndependentApps: vi.fn(),
  independentAppName: (item: IndependentApp) =>
    item.definition.definition.display.name,
}));
const installationId = '11111111-1111-4111-8111-111111111111';
const targetId = '22222222-2222-4222-8222-222222222222';
const source = {
  appId: 'private-app',
  installationId,
  origin: 'https://private.test',
  generation: 3,
  entrypoint: '/',
};
const catalog = () =>
  [
    {
      definition: {
        definition: { app_id: source.appId, display: { name: 'Private' } },
      },
      installations: [
        {
          id: installationId,
          origin: source.origin,
          generation: 3,
          ui_entrypoint: '/',
          launchable: true,
        },
      ],
    },
    {
      definition: {
        definition: { app_id: 'another-app', display: { name: 'Another' } },
      },
      installations: [
        {
          id: targetId,
          origin: 'https://another.test',
          generation: 4,
          ui_entrypoint: '/old-release',
          release_id: 'release-1',
          launchable: true,
        },
      ],
    },
  ] as unknown as IndependentApp[];
const bootstrap = () =>
  ({
    principal: { kind: 'user', user_id: 'actor-1' },
    apps: [
      {
        app_id: 'planner',
        enabled: true,
        coming_soon: false,
        entry_route_id: 'planner.root',
        title: 'Planner',
        launch_url: 'https://evil.test',
        route_base: '//evil.test',
      },
    ],
  }) as unknown as AppsBootstrapResponse;
const run = (target: IndependentNavigationTarget = { app_id: 'planner' }) =>
  resolveIndependentNavigation({
    token: 'token',
    actorId: 'actor-1',
    source,
    target,
    locale: 'en-US',
    signal: new AbortController().signal,
  });
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAppsBootstrap).mockResolvedValue(bootstrap());
  vi.mocked(getIndependentApps).mockResolvedValue(catalog());
});

describe('independent app navigation targets', () => {
  it('uses the canonical route, ignoring arbitrary bootstrap URL fields', async () => {
    expect(await run()).toMatchObject({
      path: '/apps/planner',
      identity: '/apps/planner',
      label: 'Planner',
    });
    expect(getAppsBootstrap).toHaveBeenCalledOnce();
    expect(getIndependentApps).toHaveBeenCalledOnce();
    await run();
    expect(getAppsBootstrap).toHaveBeenCalledTimes(2);
  });
  it.each([
    'actor',
    'source-missing',
    'source-disabled',
    'source-generation',
    'source-entry',
    'source-origin',
    'target-disabled',
    'target-coming',
    'target-route',
    'target-duplicate',
  ])('rejects current %s drift', async (mode) => {
    const apps = catalog(),
      boot = bootstrap();
    if (mode === 'actor') boot.principal.user_id = 'other';
    if (mode === 'source-missing') apps.shift();
    if (mode === 'source-disabled') apps[0].installations[0].launchable = false;
    if (mode === 'source-generation') apps[0].installations[0].generation++;
    if (mode === 'source-entry')
      apps[0].installations[0].ui_entrypoint = '/changed';
    if (mode === 'source-origin')
      apps[0].installations[0].origin = 'https://changed.test';
    if (mode === 'target-disabled') boot.apps[0].enabled = false;
    if (mode === 'target-coming') boot.apps[0].coming_soon = true;
    if (mode === 'target-route') boot.apps[0].entry_route_id = 'files.index';
    if (mode === 'target-duplicate') boot.apps.push(boot.apps[0]);
    vi.mocked(getIndependentApps).mockResolvedValue(apps);
    vi.mocked(getAppsBootstrap).mockResolvedValue(boot);
    expect(await run()).toBeNull();
  });
  it('requires an exact admitted independent installation and preserves its immutable fingerprint', async () => {
    expect(await run({ app_id: 'another-app' })).toBeNull();
    const target = { app_id: 'another-app', installation_id: targetId };
    const result = await run(target);
    expect(result?.path).toBe(`/apps/another-app/installed/${targetId}`);
    const apps = catalog();
    apps[1].installations[0].generation++;
    vi.mocked(getIndependentApps).mockResolvedValue(apps);
    expect((await run(target))?.identity).not.toBe(result?.identity);
    apps[1].installations[0].launchable = false;
    expect(await run(target)).toBeNull();
    expect(
      await run({ app_id: 'planner', installation_id: targetId }),
    ).toBeNull();
  });
  it('fails closed on incomplete catalog, malformed target and cancellation', async () => {
    vi.mocked(getIndependentApps).mockRejectedValue(
      new Error('catalog-incomplete'),
    );
    await expect(run()).rejects.toThrow('catalog-incomplete');
    expect(await run({ app_id: '//evil.test' })).toBeNull();
    expect(
      await resolveIndependentNavigation({
        token: 'token',
        actorId: 'actor-1',
        source,
        target: { app_id: 'planner' },
        locale: 'en-US',
        signal: AbortSignal.abort(),
      }),
    ).toBeNull();
  });
});
