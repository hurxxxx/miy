// Test-only host locale composition; production libraries never initialize i18next.
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { platformMessages } from '@miy/platform-web/i18n/resources';
import { pmsMessages } from '../src/pms/messages';

await i18n.use(initReactI18next).init({
  lng: 'ko-KR',
  fallbackLng: 'ko-KR',
  defaultNS: 'apps',
  interpolation: { escapeValue: false },
  resources: Object.fromEntries(
    (['ko-KR', 'en-US'] as const).map((locale) => [
      locale,
      { ...platformMessages[locale], apps: { pms: pmsMessages[locale] } },
    ]),
  ),
});
export { i18n };
