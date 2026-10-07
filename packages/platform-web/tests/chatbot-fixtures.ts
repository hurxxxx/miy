/** Canonical test-only composition; product imports never initialize a host. */
import { cleanup } from '@testing-library/react';
import i18n from 'i18next';
import { afterEach, beforeAll, vi } from 'vitest';
import { chatbotMessages } from '../src/chatbot/messages';
import { platformMessages } from '../src/i18n/resources';

beforeAll(async () => {
  const { initReactI18next } =
    await vi.importActual<typeof import('react-i18next')>('react-i18next');
  await i18n.use(initReactI18next).init({
    lng: 'ko-KR',
    fallbackLng: 'ko-KR',
    defaultNS: 'apps',
    interpolation: { escapeValue: false },
    resources: Object.fromEntries(
      Object.entries(chatbotMessages).map(([locale, apps]) => [
        locale,
        {
          apps,
          common: platformMessages[locale as 'ko-KR' | 'en-US'].common,
          auth: platformMessages[locale as 'ko-KR' | 'en-US'].auth,
        },
      ]),
    ),
  });
  Object.defineProperty(window, 'scrollTo', {
    configurable: true,
    value: vi.fn(),
  });
});

afterEach(cleanup);
