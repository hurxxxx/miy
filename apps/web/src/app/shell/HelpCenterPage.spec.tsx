import { fireEvent, render, screen } from '@testing-library/react';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { pmsHelpGuideRegistration } from '../../app-modules/pms';
import { resources } from '../../platform/i18n/resources';
import { HelpCenterModal, HelpCenterPage } from './HelpCenterPage';
import { createDefaultHelpRoutes } from './static-route-elements';

async function localeInstance(locale: string) {
  const instance = createInstance();
  await instance.init({
    lng: locale,
    resources,
    defaultNS: 'shell',
    interpolation: { escapeValue: false },
  });
  return instance;
}

describe('composed help guides', () => {
  it('keeps an unconfigured shell free of implicit app guides', () => {
    render(<HelpCenterPage />);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(document.querySelector('iframe')).toBeNull();
  });

  it.each([
    { locale: 'ko-KR', title: 'PMS 사용 가이드', hash: '' },
    { locale: 'en-US', title: 'PMS user guide', hash: '#english' },
  ])(
    'preserves $locale guide cards, direct routes and modal navigation',
    async ({ locale, title, hash }) => {
      const i18n = await localeInstance(locale);
      const guides = [pmsHelpGuideRegistration];
      const src = `/help/pms/user-guide.html${hash}`;
      const wrap = (children: React.ReactNode) => (
        <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
      );

      const page = render(wrap(<HelpCenterPage guides={guides} />));
      fireEvent.click(screen.getByRole('button', { name: new RegExp(title) }));
      expect(screen.getByTitle(title).getAttribute('src')).toBe(src);
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(screen.queryByRole('dialog')).toBeNull();
      page.unmount();

      const direct = render(
        wrap(
          <MemoryRouter initialEntries={['/help/pms']}>
            <Routes>
              {createDefaultHelpRoutes(new Set(), guides).map((route) => (
                <Route
                  key={route.path}
                  path={route.path}
                  element={route.element}
                />
              ))}
            </Routes>
          </MemoryRouter>,
        ),
      );
      expect(screen.getByTitle(title).getAttribute('src')).toBe(src);
      direct.unmount();

      const close = vi.fn();
      render(
        wrap(
          <HelpCenterModal
            guides={guides}
            closeLabel={i18n.t('common:actions.close')}
            onClose={close}
          />,
        ),
      );
      fireEvent.click(screen.getByRole('button', { name: new RegExp(title) }));
      expect(screen.getByTitle(title).getAttribute('src')).toBe(src);
      fireEvent.click(
        screen.getByRole('button', {
          name: i18n.t('shell:helpCenter.backToHelpCenter'),
        }),
      );
      expect(document.querySelector('iframe')).toBeNull();
      expect(
        screen.getByRole('button', { name: new RegExp(title) }),
      ).toBeTruthy();
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(close).toHaveBeenCalledOnce();
    },
  );

  it('opens an arbitrary registration without applying another app locale rules', async () => {
    const i18n = await localeInstance('en-US');
    const guide = {
      ...pmsHelpGuideRegistration,
      key: 'handbook',
      routePath: '/help/handbook',
      src: '/manual/handbook.html',
      getSrc: undefined,
    };
    render(
      <I18nextProvider i18n={i18n}>
        <HelpCenterPage guides={[guide]} />
      </I18nextProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: /PMS user guide/ }));
    expect(screen.getByTitle('PMS user guide').getAttribute('src')).toBe(
      '/manual/handbook.html',
    );
  });
});
