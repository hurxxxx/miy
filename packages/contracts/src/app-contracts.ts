export * from './app-contracts.generated.js';

import { APP_CONTRACTS } from './app-contracts.generated.js';

/** The app manifest owns launcher labels for every platform consumer. */
export function appTitles(locale: string): Record<string, string> {
  return Object.fromEntries(
    APP_CONTRACTS.map((app) => {
      const translations: Readonly<Record<string, string>> =
        'title_translations' in app ? app.title_translations : {};
      return [app.app_id, translations[locale] ?? app.title];
    }),
  );
}
