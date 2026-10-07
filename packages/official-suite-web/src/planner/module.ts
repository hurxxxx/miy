import { plannerManifest } from '../manifests/planner';
import { plannerGlobalRoutes } from './routes';
import { plannerSidebarConfig } from './sidebar';

export {
  FloatingTodayPlannerWidget,
  useFloatingTodayPlannerCount,
} from './views/FloatingTodayPlannerWidget';
export { plannerGlobalRoutes, plannerManifest, plannerSidebarConfig };

export const plannerModule = {
  globalRoutes: plannerGlobalRoutes,
  manifest: plannerManifest,
  sidebarConfig: plannerSidebarConfig,
} as const;
