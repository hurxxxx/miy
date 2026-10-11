import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { ScopedIndependentAppHost } from './ScopedIndependentAppHost';

vi.mock('@/src/platform/apps/IndependentAppHost', () => ({
  IndependentAppHost: () => <div>installed app host</div>,
}));
vi.mock('@/src/platform/auth/settings-pages', () => ({
  NotFoundView: () => <div>outside composition scope</div>,
}));

it.each([
  { appIds: undefined, host: true },
  { appIds: ['private-notes'], host: true },
  { appIds: ['pms', 'docs'], host: false },
  { appIds: [], host: false },
])('scopes direct installed-app routes: $appIds', ({ appIds, host }) => {
  render(
    <MemoryRouter initialEntries={['/apps/private-notes/installed/test']}>
      <Routes>
        <Route
          path="/apps/:appId/installed/:installationId"
          element={<ScopedIndependentAppHost appIds={appIds} />}
        />
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.queryByText('installed app host') !== null).toBe(host);
  expect(screen.queryByText('outside composition scope') !== null).toBe(!host);
});
