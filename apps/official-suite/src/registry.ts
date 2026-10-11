import { APP_CONTRACTS } from '@miy/contracts/app-contracts';
import { OFFICIAL_APP_MODULES } from '@miy/official-suite-web/modules';
import {
  createAppModuleRegistryApi,
  createShellStateResolver,
} from '@miy/web-official-suite-bridge';

export const officialRegistry =
  createAppModuleRegistryApi(OFFICIAL_APP_MODULES);
export const OFFICIAL_APP_IDS = OFFICIAL_APP_MODULES.map(
  (module) => module.manifest.appBarItem.id,
);
const ids = new Set<string>(OFFICIAL_APP_IDS);
export const officialLauncherPaths = new Map(
  APP_CONTRACTS.filter((app) => ids.has(app.app_id)).map(
    (app) => [app.app_id, app.route_base] as const,
  ),
);
export const resolveOfficialShellState = createShellStateResolver({
  navItems: officialRegistry.NAV_ITEMS,
  shellManifests: [],
  getManifest: officialRegistry.getAppModuleManifest,
  getNavResolver: officialRegistry.getAppShellNavResolver,
  requireRegisteredApps: true,
  unknownAppId: 'launcher',
});
