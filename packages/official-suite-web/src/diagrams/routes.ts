import {
  getAppRouteChrome,
  getAppRoutePattern,
} from '@miy/contracts/app-routes';
import { createElement, lazy } from 'react';

import { lazyRoute } from '@miy/platform-web/routing';
import type { AppRouteDefinition } from '@miy/core-web/navigation-types';

const DiagramsView = lazy(() =>
  import('./views/DiagramsView').then((module) => ({
    default: module.DiagramsView,
  })),
);

export const diagramsToolElement = lazyRoute(createElement(DiagramsView));

export const diagramsAppRoutes: AppRouteDefinition[] = [
  {
    appId: 'diagrams',
    chrome: getAppRouteChrome('diagrams.root'),
    path: getAppRoutePattern('diagrams.root'),
    element: diagramsToolElement,
  },
  {
    appId: 'diagrams',
    chrome: getAppRouteChrome('diagrams.diagram'),
    path: getAppRoutePattern('diagrams.diagram'),
    element: diagramsToolElement,
  },
];
