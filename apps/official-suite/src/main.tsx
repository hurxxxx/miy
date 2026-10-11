import '@/src/platform/i18n';
import { installMatomoTracking } from '@/src/platform/analytics/matomo';
import { installClientBuildGuards } from '@/src/platform/deployment/client-build-guard';
import { installFirstPartyNavigation } from '@/src/platform/deployment/first-party-navigation';
import {
  clearStaleAssetReloadMarker,
  installStaleAssetReloadHandler,
} from '@/src/platform/deployment/stale-asset-reload';
import '@miy/ui/styles.css';
import './index.css';
import '@miy/official-suite-web/calendar/fullcalendar-theme.css';
import { StrictMode, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import OfficialSuiteRoot from './OfficialSuiteRoot';
import OfficialWidgetRoot from './OfficialWidgetRoot';
import { PLATFORM_COMPATIBILITY_BUILD_ID } from './platform-build';

const root = document.getElementById('root');
if (!root) throw new Error('Official suite root element is missing');
installStaleAssetReloadHandler();
installFirstPartyNavigation('official');
if (window.parent === window) installMatomoTracking();

function ReloadMarkerCleanup() {
  useEffect(() => {
    clearStaleAssetReloadMarker();
  }, []);
  return null;
}

installClientBuildGuards(window, { buildId: PLATFORM_COMPATIBILITY_BUILD_ID });
const Root =
  window.location.pathname === '/official-suite/widgets'
    ? OfficialWidgetRoot
    : OfficialSuiteRoot;
createRoot(root).render(
  <StrictMode>
    <Root />
    <ReloadMarkerCleanup />
  </StrictMode>,
);
