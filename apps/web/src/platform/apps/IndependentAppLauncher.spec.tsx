import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import type { IndependentApp } from './independent-apps-api';
import { IndependentAppLauncher } from './IndependentAppLauncher';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'ko-KR' },
  }),
}));

const item = {
  definition: {
    definition: {
      app_id: 'candidate-review',
      display: {
        name: 'Candidate review',
        translations: { 'ko-KR': '지원서 검토' },
        icon: 'clipboard-check',
      },
    },
  },
  installations: [
    { id: 'dev-install', environment: 'development', launchable: true },
    { id: 'not-admitted', environment: 'production', launchable: false },
  ],
} as unknown as IndependentApp;

it('renders arbitrary admitted installations with manifest labels and no static app import', () => {
  const view = render(
    <MemoryRouter>
      <IndependentAppLauncher items={[item]} loading={false} failed={false} />
    </MemoryRouter>,
  );
  const link = screen.getByRole('link', {
    name: '지원서 검토 independentApps.development',
  });
  expect(link.getAttribute('href')).toBe(
    '/apps/candidate-review/installed/dev-install',
  );
  expect(
    link.querySelector('svg')?.classList.contains('lucide-clipboard-check'),
  ).toBe(true);
  expect(screen.getAllByRole('link')).toHaveLength(1);
  view.rerender(
    <MemoryRouter>
      <IndependentAppLauncher
        items={[
          {
            ...item,
            installations: item.installations.map((installation) => ({
              ...installation,
              launchable: false,
            })),
          },
        ]}
        loading={false}
        failed={false}
      />
    </MemoryRouter>,
  );
  expect(screen.queryAllByRole('link')).toHaveLength(0);
});

it('links only the current owner to their unlaunchable personal development setup', () => {
  const owned = {
    ...item,
    definition: {
      ...item.definition,
      owner_user_id: 'current-owner',
      definition: {
        ...item.definition.definition,
        ownership: 'personal' as const,
      },
    },
    installations: item.installations.map((installation) => ({
      ...installation,
      launchable: false,
    })),
  };
  const rendered = render(
    <MemoryRouter>
      <IndependentAppLauncher
        items={[owned]}
        loading={false}
        failed={false}
        ownerUserId="current-owner"
      />
    </MemoryRouter>,
  );
  expect(
    screen
      .getByRole('link', { name: 'independentApps.previewSetup.title' })
      .getAttribute('href'),
  ).toBe('/apps/candidate-review/installed/dev-install/setup');
  expect(screen.getAllByRole('link')).toHaveLength(1);
  rendered.rerender(
    <MemoryRouter>
      <IndependentAppLauncher
        items={[owned]}
        loading={false}
        failed={false}
        ownerUserId="another-owner"
      />
    </MemoryRouter>,
  );
  expect(screen.queryAllByRole('link')).toHaveLength(0);
});
