import type { AppId, AppRouteId } from '@mty/contracts/app-contracts';
import { matchAppRoute } from '@mty/contracts/app-routes';

export type AppRouteContext =
  | { kind: 'launcher' | 'shell'; appId: null }
  | { kind: 'app'; appId: AppId; routeId: AppRouteId };

export function resolveAppRouteContext(pathname: string): AppRouteContext {
  if (pathname === '/') return { kind: 'launcher', appId: null };
  const route = matchAppRoute(pathname);
  return route
    ? { kind: 'app', appId: route.appId, routeId: route.routeId }
    : { kind: 'shell', appId: null };
}
