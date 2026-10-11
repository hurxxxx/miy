import { createShellStateResolver } from './app-shell-state';
import {
  NAV_ITEMS,
  SHELL_MODULE_MANIFESTS,
  getAppModuleManifest,
  getAppShellNavResolver,
} from './app/shell/app-registry';

export type { ShellAppId, ShellState } from './app-shell-state';
export const resolveShellState = createShellStateResolver({
  navItems: NAV_ITEMS,
  shellManifests: SHELL_MODULE_MANIFESTS,
  getManifest: getAppModuleManifest,
  getNavResolver: getAppShellNavResolver,
});
