import { diagramsManifest } from '../manifests/diagrams';
import { diagramsAppRoutes } from './routes';
import { diagramsSidebarConfig } from './sidebar';

export { diagramsAppRoutes, diagramsToolElement } from './routes';
export { diagramsSidebarConfig } from './sidebar';
export { diagramsManifest };

export const diagramsModule = {
  manifest: diagramsManifest,
  sidebarConfig: diagramsSidebarConfig,
  appRoutes: diagramsAppRoutes,
} as const;
