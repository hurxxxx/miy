import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { appIconForKey } from './app-icons';
import {
  independentAppName,
  type IndependentApp,
} from './independent-apps-api';
import { independentAppPath } from './independent-app-host';
import { ownerPreviewSettingsPath } from './owner-preview';

export function IndependentAppLauncher({
  items,
  loading,
  failed,
  ownerUserId,
}: {
  items: IndependentApp[];
  loading: boolean;
  failed: boolean;
  ownerUserId?: string;
}) {
  const { t, i18n } = useTranslation('shell');
  const launchable = items.flatMap((item) =>
    item.installations
      .filter((installation) => installation.launchable)
      .map((installation) => ({ item, installation })),
  );
  const owned = ownerUserId
    ? items.flatMap((item) =>
        item.definition.owner_user_id === ownerUserId &&
        item.definition.definition.ownership === 'personal'
          ? item.installations
              .filter(
                (installation) => installation.environment === 'development',
              )
              .map((installation) => ({ item, installation }))
          : [],
      )
    : [];
  if (!loading && !failed && launchable.length === 0 && owned.length === 0)
    return null;
  return (
    <section className="mt-8" aria-label={t('independentApps.title')}>
      <h2 className="app-text-title-md text-app-ink">
        {t('independentApps.title')}
      </h2>
      {loading && <p role="status">{t('common:feedback.loading')}</p>}
      {failed && (
        <p role="alert" className="text-app-danger">
          {t('independentApps.catalogFailed')}
        </p>
      )}
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {launchable.map(({ item, installation }) => {
          const definition = item.definition.definition;
          const Icon = appIconForKey(definition.display.icon);
          return (
            <Link
              key={installation.id}
              to={independentAppPath(definition.app_id, installation.id)}
              className="rounded-2xl border border-app-border bg-app-surface p-4 hover:border-app-accent/40"
            >
              <Icon aria-hidden size={21} />
              <h3 className="app-text-title-sm mt-4 text-app-ink">
                {independentAppName(
                  item,
                  i18n.resolvedLanguage ?? i18n.language,
                )}
              </h3>
              <p className="app-text-caption mt-1 text-app-ink/55">
                {t(
                  installation.environment === 'development'
                    ? 'independentApps.development'
                    : 'independentApps.production',
                )}
              </p>
            </Link>
          );
        })}
      </div>
      {!loading && !failed && owned.length > 0 && (
        <section
          className="mt-5 border-t border-app-border pt-4"
          aria-label={t('independentApps.previewSetup.owned')}
        >
          <h3 className="app-text-title-sm">
            {t('independentApps.previewSetup.owned')}
          </h3>
          <ul className="mt-2 space-y-2">
            {owned.map(({ item, installation }) => (
              <li
                key={installation.id}
                className="flex flex-wrap items-center gap-x-4 gap-y-1"
              >
                <span>
                  {independentAppName(
                    item,
                    i18n.resolvedLanguage ?? i18n.language,
                  )}
                </span>
                <span className="app-text-caption break-all text-app-ink/60">
                  {installation.origin}
                </span>
                <Link
                  className="text-app-accent"
                  to={ownerPreviewSettingsPath(
                    item.definition.definition.app_id,
                    installation.id,
                  )}
                >
                  {t('independentApps.previewSetup.title')}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  );
}
