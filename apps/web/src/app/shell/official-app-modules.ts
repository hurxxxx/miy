import { OFFICIAL_APP_MANIFESTS } from '@miy/official-suite-web';
import { createElement } from 'react';
import { APP_ROUTE_BY_ID } from '@miy/contracts/app-contracts';
import { DocumentNavigation } from './document-navigation';
import type { AppModuleRegistration } from './app-registry-factory';

const routeChrome = new Map(
  [...APP_ROUTE_BY_ID.values()].map((route) => [
    `${route.route_base}${route.suffix}`,
    route.chrome,
  ]),
);

/** The portal owns launcher metadata, while the official artifact runs business UI. */
export const OFFICIAL_APP_MODULES: readonly AppModuleRegistration[] =
  OFFICIAL_APP_MANIFESTS.map((manifest) => ({
    manifest,
    appRoutes: manifest.appRoutePaths.map((path) => ({
      appId: manifest.appBarItem.id,
      chrome: routeChrome.get(path),
      element: createElement(DocumentNavigation),
      path,
    })),
    globalRoutes: (manifest.globalRoutePaths ?? []).map((path) => ({
      appId: manifest.appBarItem.id,
      chrome: routeChrome.get(path),
      element: createElement(DocumentNavigation),
      path,
    })),
  }));
