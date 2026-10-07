import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import { DEFAULT_LOCALE, readStoredLocale } from './locales';
import { resources } from './resources';

void i18n.use(initReactI18next).init({
  defaultNS: 'common',
  fallbackLng: DEFAULT_LOCALE,
  interpolation: {
    escapeValue: false,
  },
  lng: readStoredLocale(),
  ns: Object.keys(resources[DEFAULT_LOCALE]),
  react: {
    useSuspense: false,
  },
  resources,
  supportedLngs: Object.keys(resources),
});

export { syncLocale } from '@miy/platform-web/i18n';

export { i18n };
