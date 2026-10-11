import {
  getAppRouteChrome,
  getAppRoutePattern,
} from '@miy/contracts/app-routes';
import { createElement, lazy } from 'react';

import { lazyRoute } from '@miy/platform-web/routing';
import type { StaticRouteDefinition } from '@miy/core-web/navigation-types';

const PlannerView = lazy(() =>
  import('./views/PlannerView').then((module) => ({
    default: module.PlannerView,
  })),
);

export const plannerGlobalRoutes: StaticRouteDefinition[] = [
  {
    chrome: getAppRouteChrome('planner.root'),
    path: getAppRoutePattern('planner.root'),
    element: lazyRoute(createElement(PlannerView)),
  },
];
