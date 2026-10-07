import { OFFICIAL_HELP_GUIDES } from '@miy/official-suite-web';
import { RealtimeProvider } from '@miy/platform-web/realtime';
import { FeedbackProvider } from '@miy/ui';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { BrowserRouter } from 'react-router-dom';
import {
  AppContent,
  createDefaultHelpRoutes,
} from '@miy/web-official-suite-bridge';
import {
  OFFICIAL_APP_IDS,
  officialLauncherPaths,
  officialRegistry,
  resolveOfficialShellState,
} from './registry';

const helpGuides = OFFICIAL_HELP_GUIDES;
const helpRoutes = createDefaultHelpRoutes(new Set<string>(), helpGuides);

// Stage-zero keeps realtime traffic disabled, but app hooks still require the
// platform's actual context. A no-op shell wrapper does not provide that context.
function OfflineOfficialRealtimeProvider({
  children,
}: {
  children: ReactNode;
}) {
  return <RealtimeProvider token={null}>{children}</RealtimeProvider>;
}

/** Stage-zero UI composition. Backend traffic and data writers still use the legacy API. */
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
          personalWidgetsEnabled={false}
          realtimeEnabled={false}
          realtimeProvider={OfflineOfficialRealtimeProvider}
          resolveShellStateForPath={resolveOfficialShellState}
          shellProviders={officialRegistry.APP_SHELL_PROVIDERS}
        />
      </BrowserRouter>
    </FeedbackProvider>
  );
}
