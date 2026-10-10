/** Temporary one-way public bridge; remove after shared UI/business source extraction. */
export { AppContent } from './app/shell/AppContent';
export { createDefaultHelpRoutes } from './app/shell/static-route-elements';
export { createAppModuleRegistryApi } from './app/shell/app-registry-factory';
export { createShellStateResolver } from './app-shell-state';
export { DefaultShellRealtimeProvider } from './app/shell/shell-realtime-provider';
export { NotificationPanel } from './components/layout/NotificationPanel';
export { getUnreadNotificationCount } from './platform/notifications/notifications-api';
export { AuthProvider, RequireAuth } from './platform/auth/auth-provider';
export { useAppsBootstrap } from './platform/apps/apps-api';
export type { AuthUser } from './platform/auth/auth-api';

export {
  dmManifest,
  FloatingDmWidget,
  useFloatingDmUnreadCount,
  type DmThreadScrollSnapshots,
} from './app-modules/dm';
export {
  PersonalWidgetHost,
  type PersonalWidgetSecondaryPanelAdapter,
} from './platform/personal-widgets/PersonalWidgetHost';
export type { PersonalTodoItem } from './platform/personal-widgets/personal-widgets-api';
export { resolvePersonalWidgetDockPanels } from './app/shell/personal-widget-registry-model';
