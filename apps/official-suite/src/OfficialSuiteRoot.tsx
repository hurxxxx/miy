import { OFFICIAL_HELP_GUIDES } from '@miy/official-suite-web';
import { NOTIFICATION_REALTIME_EVENT_TYPE_VALUES } from '@miy/contracts/notifications';
import { pmsManifest } from '@miy/official-suite-web/manifests/pms';
import { FeedbackProvider } from '@miy/ui';
import { ShellPersonalWidgetHost } from './OfficialPersonalWidgetHost';
import { useTranslation } from 'react-i18next';
import { BrowserRouter } from 'react-router-dom';
import { FirstPartyDocumentBoundary } from '@/src/platform/deployment/FirstPartyDocumentBoundary';
import {
  AppContent,
  createDefaultHelpRoutes,
  DefaultShellRealtimeProvider,
  NotificationPanel,
  getUnreadNotificationCount,
} from '@miy/web-official-suite-bridge';
import {
  OFFICIAL_APP_IDS,
  officialLauncherPaths,
  officialRegistry,
  resolveOfficialShellState,
} from './registry';

const helpGuides = OFFICIAL_HELP_GUIDES;
const helpRoutes = createDefaultHelpRoutes(new Set<string>(), helpGuides);

const notificationRealtimeEventTypes = new Set<string>(
  NOTIFICATION_REALTIME_EVENT_TYPE_VALUES,
);

/** Trusted same-origin official UI using the existing platform session and ACL. */
export default function OfficialSuiteRoot() {
  const { t } = useTranslation('common');
  return (
    <FeedbackProvider
      labels={{
        close: t('actions.close'),
        item: t('feedback.itemLabel'),
        region: t('feedback.regionLabel'),
      }}
    >
      <BrowserRouter>
        <FirstPartyDocumentBoundary owner="official">
          <AppContent
            appScope={{ appIds: OFFICIAL_APP_IDS }}
            appBarItems={officialRegistry.APP_BAR_ITEMS}
            appGlobalRoutes={officialRegistry.APP_GLOBAL_ROUTES}
            appRoutes={officialRegistry.APP_ROUTES}
            backgroundWorkSources={officialRegistry.APP_BACKGROUND_WORK_SOURCES}
            getAppModuleManifest={(appId) =>
              officialRegistry.getAppModuleManifest(
                appId as (typeof OFFICIAL_APP_IDS)[number],
              )
            }
            getAppSidebarConfig={officialRegistry.getAppModuleSidebarConfig}
            helpGuides={helpGuides}
            helpRoutes={helpRoutes}
            launcherGlobalPaths={officialLauncherPaths}
            navItems={officialRegistry.NAV_ITEMS}
            notificationIssueAppId={pmsManifest.appBarItem.id}
            notificationPanel={NotificationPanel}
            notificationRealtimeEventTypes={notificationRealtimeEventTypes}
            notificationUnreadCountLoader={getUnreadNotificationCount}
            personalWidgetHost={ShellPersonalWidgetHost}
            realtimeEnabled
            realtimeProvider={DefaultShellRealtimeProvider}
            resolveShellStateForPath={resolveOfficialShellState}
            shellProviders={officialRegistry.APP_SHELL_PROVIDERS}
          />
        </FirstPartyDocumentBoundary>
      </BrowserRouter>
    </FeedbackProvider>
  );
}
