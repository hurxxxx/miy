import { OFFICIAL_HELP_GUIDES } from '@miy/official-suite-web';
import { NOTIFICATION_REALTIME_EVENT_TYPE_VALUES } from '@miy/contracts/notifications';
import { FeedbackProvider } from '@miy/ui';
import { lazy } from 'react';
import { useTranslation } from 'react-i18next';
import { BrowserRouter as Router } from 'react-router-dom';

import { pmsManifest } from '@miy/official-suite-web/manifests/pms';
import { resolveShellState } from '../app-shell';
import { NotificationPanel } from '../components/layout/NotificationPanel';
import { getUnreadNotificationCount } from '../platform/notifications/notifications-api';
import {
  AI_TOOL_APP_IDS,
  APP_BACKGROUND_WORK_SOURCES,
  APP_BAR_FIXED_APP_IDS,
  APP_BAR_ITEMS,
  APP_BAR_PINNED_BY_DEFAULT_APP_IDS,
  APP_FEATURE_GUIDE_TOOL_IDS,
  APP_GLOBAL_ROUTES,
  APP_LAUNCHER_GLOBAL_PATHS,
  APP_ROUTES,
  APP_SHELL_PROVIDERS,
  getAppModuleManifest,
  getAppModuleSidebarConfig,
  NAV_ITEMS,
} from './shell/app-registry';
import {
  staticAdminLandingRoute,
  staticAdminRedirectRoutes,
  staticAdminSectionRoutes,
} from './shell/app-route-definitions';
import { AppContent } from './shell/AppContent';
import { DefaultShellRealtimeProvider } from './shell/shell-realtime-provider';
import { createDefaultHelpRoutes } from './shell/static-route-elements';
import { FirstPartyDocumentBoundary } from '../platform/deployment/FirstPartyDocumentBoundary';

type RegisteredAppId = Parameters<typeof getAppModuleManifest>[0];
const helpGuides = OFFICIAL_HELP_GUIDES;
const helpRoutes = createDefaultHelpRoutes(
  APP_FEATURE_GUIDE_TOOL_IDS,
  helpGuides,
);

const DefaultShellPersonalWidgetHost = lazy(() =>
  import('../platform/embedded-official/OfficialWidgetFrame').then(
    (module) => ({
      default: module.OfficialWidgetFrame,
    }),
  ),
);

const getDefaultAppModuleManifest = (appId: string) =>
  getAppModuleManifest(appId as RegisteredAppId);

const NOTIFICATION_REALTIME_EVENT_TYPE_SET = new Set<string>(
  NOTIFICATION_REALTIME_EVENT_TYPE_VALUES,
);

export default function AppRoot() {
  const { t } = useTranslation('common');

  return (
    <FeedbackProvider
      labels={{
        close: t('actions.close'),
        item: t('feedback.itemLabel'),
        region: t('feedback.regionLabel'),
      }}
    >
      <Router>
        <FirstPartyDocumentBoundary owner="platform">
          <AppContent
            adminLandingRoute={staticAdminLandingRoute}
            adminRedirectRoutes={staticAdminRedirectRoutes}
            adminSectionRoutes={staticAdminSectionRoutes}
            appBarItems={APP_BAR_ITEMS}
            appBarFixedAppIds={APP_BAR_FIXED_APP_IDS}
            appBarPinnedByDefaultAppIds={APP_BAR_PINNED_BY_DEFAULT_APP_IDS}
            appGlobalRoutes={APP_GLOBAL_ROUTES}
            backgroundWorkSources={APP_BACKGROUND_WORK_SOURCES}
            featureGuideToolIds={APP_FEATURE_GUIDE_TOOL_IDS}
            getAppModuleManifest={getDefaultAppModuleManifest}
            getAppSidebarConfig={getAppModuleSidebarConfig}
            helpGuides={helpGuides}
            helpRoutes={helpRoutes}
            launcherGlobalPaths={APP_LAUNCHER_GLOBAL_PATHS}
            navItems={NAV_ITEMS}
            notificationIssueAppId={pmsManifest.appBarItem.id}
            notificationPanel={NotificationPanel}
            notificationRealtimeEventTypes={
              NOTIFICATION_REALTIME_EVENT_TYPE_SET
            }
            notificationUnreadCountLoader={getUnreadNotificationCount}
            personalWidgetHost={DefaultShellPersonalWidgetHost}
            realtimeProvider={DefaultShellRealtimeProvider}
            resolveShellStateForPath={resolveShellState}
            shellProviders={APP_SHELL_PROVIDERS}
            appRoutes={APP_ROUTES}
            aiToolAppIds={AI_TOOL_APP_IDS}
          />
        </FirstPartyDocumentBoundary>
      </Router>
    </FeedbackProvider>
  );
}
