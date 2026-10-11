import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';

import { useAuth } from '@/src/platform/auth/auth-context';
import { normalizeLocale } from '@/src/platform/i18n/locales';
import { useEffectiveTheme } from '@/src/platform/theme/use-effective-theme';
import {
  independentAppName,
  issueIndependentLaunch,
  useIndependentApps,
} from './independent-apps-api';
import {
  independentAppOrigin,
  listenForIndependentApp,
} from './independent-app-host';
import { useIndependentAppNavigation } from './use-independent-app-navigation';
import { useIndependentAppFiles } from './use-independent-app-files';
import { IndependentFilePicker } from './IndependentFilePicker';

export function IndependentAppHost() {
  const { token, user } = useAuth();
  const navigate = useNavigate();
  const { appId, installationId } = useParams();
  const [params] = useSearchParams();
  const popup = params.get('connect') === 'popup';
  const { t, i18n } = useTranslation('shell');
  const theme = useEffectiveTheme();
  const locale = normalizeLocale(i18n.resolvedLanguage ?? i18n.language);
  const uiContext = useRef({ theme, locale });
  uiContext.current = { theme, locale };
  const updateUIContext = useRef<(() => void) | null>(null);
  const catalog = useIndependentApps(token);
  const item = catalog.items.find(
    (candidate) => candidate.definition.definition.app_id === appId,
  );
  const installation = item?.installations.find(
    (candidate) => candidate.id === installationId && candidate.launchable,
  );
  const origin =
    installation &&
    independentAppOrigin(installation.origin, window.location.origin);
  const title = item
    ? independentAppName(item, i18n.resolvedLanguage ?? i18n.language)
    : t('independentApps.title');
  const entry = installation?.ui_entrypoint;
  const url =
    origin && entry && entry.startsWith('/') && !entry.startsWith('//')
      ? origin + entry
      : null;
  const frame = useRef<HTMLIFrameElement>(null);
  const [reload, setReload] = useState(0);
  const [documentVersion, setDocumentVersion] = useState(0);
  const [connection, setConnection] = useState<
    'waiting' | 'connected' | 'failed'
  >('waiting');
  const source =
    !catalog.failed && appId && installation && origin && entry
      ? {
          appId,
          installationId: installation.id,
          origin,
          generation: installation.generation,
          entrypoint: entry,
        }
      : null;
  const hostDocument = `${popup}:${reload}:${documentVersion}`;
  const navigation = useIndependentAppNavigation({
    token,
    actorId: user?.id ?? null,
    source,
    documentVersion: hostDocument,
    locale,
    navigate,
  });
  const offerNavigation = useRef(navigation.offerNavigation);
  offerNavigation.current = navigation.offerNavigation;
  const files = useIndependentAppFiles({
    token,
    actorId: user?.id ?? null,
    source,
    documentVersion: hostDocument,
  });
  const selectFile = useRef(files.selectFile);
  selectFile.current = files.selectFile;

  useEffect(() => {
    const target = popup
      ? (window.opener as Window | null)
      : frame.current?.contentWindow;
    if (!token || !origin || !installation) return;
    if (!target) {
      setConnection('failed');
      return;
    }
    const controller = new AbortController();
    const onOffer = offerNavigation.current;
    const onSelectFile = selectFile.current;
    setConnection('waiting');
    const timeout = window.setTimeout(() => {
      controller.abort();
      setConnection('failed');
    }, 20000);
    const cleanup = listenForIndependentApp({
      frame: target,
      origin,
      installationId: installation.id,
      signal: controller.signal,
      issueLaunch: (challenge, signal) =>
        issueIndependentLaunch(token, installation.id, challenge, signal),
      onConnected: () => {
        window.clearTimeout(timeout);
        setConnection('connected');
      },
      onFailure: () => {
        window.clearTimeout(timeout);
        setConnection('failed');
      },
      getUIContext: () => uiContext.current,
      offerNavigation: onOffer,
      selectFile: onSelectFile,
    });
    updateUIContext.current = cleanup.updateUIContext;
    return () => {
      updateUIContext.current = null;
      window.clearTimeout(timeout);
      controller.abort();
      cleanup();
    };
  }, [
    token,
    user?.id,
    appId,
    origin,
    installation?.id,
    installation?.generation,
    entry,
    catalog.failed,
    popup,
    reload,
    documentVersion,
  ]);

  useEffect(() => updateUIContext.current?.(), [theme, locale]);

  return (
    <section className="flex h-full min-h-64 flex-col" aria-label={title}>
      <header className="flex flex-wrap items-center gap-3 border-b border-app-border p-4">
        <Link to="/" className="app-text-body text-app-accent">
          {t('launcher.title')}
        </Link>
        <h1 className="app-text-title-md flex-1">{title}</h1>
        {url && !popup && (
          <>
            <button
              className="app-text-body text-app-accent"
              onClick={() => setReload((value) => value + 1)}
            >
              {t('common:actions.reload')}
            </button>
            <a
              className="app-text-body text-app-accent"
              href={url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t('independentApps.openStandalone')}
            </a>
          </>
        )}
      </header>
      {navigation.offer && (
        <div
          className="flex flex-wrap items-center gap-3 border-b border-app-border p-4"
          role="status"
        >
          <p className="app-text-body flex-1">
            {t('independentApps.navigation.offer', {
              app: navigation.offer.destination.label,
            })}
          </p>
          <button
            className="app-text-body text-app-accent"
            disabled={navigation.offer.checking}
            onClick={() => void navigation.accept()}
          >
            {t(
              navigation.offer.checking
                ? 'independentApps.navigation.checking'
                : 'independentApps.navigation.open',
            )}
          </button>
          <button
            className="app-text-body text-app-muted"
            onClick={navigation.dismiss}
          >
            {t('independentApps.navigation.dismiss')}
          </button>
        </div>
      )}
      {files.view && (
        <IndependentFilePicker
          key={files.view.requestId}
          picker={files}
          appName={title}
        />
      )}
      {catalog.loading && (
        <p role="status" className="p-4">
          {t('common:feedback.loading')}
        </p>
      )}
      {!catalog.loading && (!url || catalog.failed) && (
        <p role="alert" className="p-4 text-app-danger">
          {t(
            catalog.failed
              ? 'independentApps.catalogFailed'
              : 'independentApps.unavailable',
          )}
        </p>
      )}
      {url && !catalog.failed && (
        <>
          {connection === 'waiting' && (
            <p role="status" className="p-4">
              {t('independentApps.connecting')}
            </p>
          )}
          {connection === 'failed' && (
            <p role="alert" className="p-4 text-app-danger">
              {t('independentApps.connectionFailed')}
            </p>
          )}
          {popup ? (
            <p className="p-4">
              {t(
                connection === 'connected'
                  ? 'independentApps.returnToApp'
                  : 'independentApps.popupDescription',
              )}
            </p>
          ) : (
            <iframe
              key={`${installation?.id}:${installation?.generation}:${reload}`}
              ref={frame}
              src={url}
              title={title}
              sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
              referrerPolicy="no-referrer"
              className="min-h-64 w-full flex-1 border-0"
              onLoad={() => setDocumentVersion((value) => value + 1)}
            />
          )}
        </>
      )}
    </section>
  );
}
