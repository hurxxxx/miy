import { matchAppRoute } from '@miy/contracts/app-routes';
import {
  getShellPathname,
  resolveGlobalRouteAppId,
  resolveManifestNavItemId,
} from '@miy/platform-web/routing/shell-navigation-model';
import type {
  AppModuleId,
  AppModuleManifest,
  AppShellNavResolver,
  NavItem,
} from './app/shell/navigation-types';
import { canAccessApp } from './platform/apps/app-access';
import { hasAdminConsoleAccess, type AuthUser } from './platform/auth/auth-api';

export type ShellAppId = AppModuleId | 'launcher' | 'profile';
export type ShellState = { activeAppId: ShellAppId; activeNavItemId: string };

type Registry = {
  navItems: readonly NavItem[];
  shellManifests: readonly AppModuleManifest[];
  getManifest: (appId: AppModuleId) => AppModuleManifest | null;
  getNavResolver: (appId: AppModuleId) => AppShellNavResolver | null;
  requireRegisteredApps?: boolean;
  unknownAppId?: 'home' | 'launcher';
};

/** A composition root supplies its registry; this helper never imports app code. */
export function createShellStateResolver(registry: Registry) {
  return (
    path: string,
    user: AuthUser | null | undefined,
    enabledAppIds?: readonly string[],
  ): ShellState => {
    const launcher: ShellState = {
      activeAppId: 'launcher',
      activeNavItemId: '',
    };
    const pathname = getShellPathname(path);
    if (pathname === '/') return launcher;
    const appId =
      matchAppRoute(pathname)?.appId ??
      resolveGlobalRouteAppId({ manifests: registry.shellManifests, pathname });
    if (!appId)
      return {
        activeAppId: registry.unknownAppId ?? 'home',
        activeNavItemId: '',
      };
    const manifest = registry.getManifest(appId);
    if (registry.requireRegisteredApps && !manifest) return launcher;
    const admitted =
      appId === 'settings'
        ? hasAdminConsoleAccess(user)
        : canAccessApp({ appId, enabledAppIds, user });
    if (!admitted) return launcher;
    if (!manifest) return { activeAppId: appId, activeNavItemId: '' };
    const resolved = registry.getNavResolver(appId)?.({
      appId,
      manifest,
      navItems: registry.navItems,
      path,
      pathname,
    });
    return {
      activeAppId: appId,
      activeNavItemId:
        typeof resolved === 'string'
          ? resolved
          : resolveManifestNavItemId({
              appId,
              fallbackNavItemId: manifest.defaultActiveNavItemId,
              navItems: registry.navItems,
              path,
            }),
    };
  };
}
