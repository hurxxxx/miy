import { AppBootstrapProvider } from '@miy/platform-web/apps';
import { useAuth } from '@miy/platform-web/auth-context';
import { FeedbackProvider } from '@miy/ui';
import {
  AuthProvider,
  DefaultShellRealtimeProvider,
  RequireAuth,
  useAppsBootstrap,
} from '@miy/web-official-suite-bridge';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { BrowserRouter, useLocation } from 'react-router-dom';
import { ShellPersonalWidgetHost } from './OfficialPersonalWidgetHost';

function Widgets() {
  const { token, user } = useAuth();
  const bootstrap = useAppsBootstrap(token, user?.id ?? null);
  return (
    <AppBootstrapProvider value={bootstrap}>
      <DefaultShellRealtimeProvider token={token}>
        <div className="fixed inset-y-0 right-0 flex w-10">
          <ShellPersonalWidgetHost />
        </div>
      </DefaultShellRealtimeProvider>
    </AppBootstrapProvider>
  );
}

function WidgetDocument() {
  const location = useLocation();
  const href = `${location.pathname}${location.search}${location.hash}`;
  const isWidgetRoute = location.pathname === '/official-suite/widgets';
  useEffect(() => {
    if (!isWidgetRoute)
      (window.parent === window ? window : window.parent).location.assign(href);
  }, [href, isWidgetRoute]);
  return isWidgetRoute ? (
    <RequireAuth>
      <Widgets />
    </RequireAuth>
  ) : null;
}

export default function OfficialWidgetRoot() {
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
        <AuthProvider>
          <WidgetDocument />
        </AuthProvider>
      </BrowserRouter>
    </FeedbackProvider>
  );
}
