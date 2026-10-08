import i18n from 'i18next';
import {
  syncLocale as syncLocaleSession,
  type LocaleI18n,
} from './locale-session';
import { LOCALE_SESSION_CONFIG, type AppLocale } from './locales';

export function syncLocale(locale: string | null | undefined): AppLocale {
  return syncLocaleSession<AppLocale>(locale, LOCALE_SESSION_CONFIG, {
    i18n: i18n as LocaleI18n<AppLocale>,
  });
}

export { i18n };
export * from './locales';
