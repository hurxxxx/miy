import * as owned from '@miy/official-suite-web/pms';
import * as legacyApi from './api/pms-api';
import * as legacyPublic from './public-api';
import { taskListRoleAllows } from './api/pms-permissions';
import { applyFlatReorder } from './api/pms-sidebar-reorder';
import { TaskPickerModal } from './views/TaskPickerModal';
import { applyOrderedReorder } from '@/src/platform/ordering/ordered-reorder';
import { applyOrderedReorder as ownedReorder } from '@miy/platform-web/ordering';
import {
  AuthContext,
  type AuthContextValue,
} from '@/src/platform/auth/auth-context';
import {
  AppBootstrapProvider,
  type AppsBootstrapResponse,
} from '@/src/platform/apps/app-bootstrap-context';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
const t = vi.hoisted(() => (key: string) => key);
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }));
afterEach(cleanup);
it('keeps every original API function/error and public object identical', () => {
  for (const [key, value] of Object.entries(legacyApi))
    expect(owned[key as keyof typeof owned]).toBe(value);
  for (const [key, value] of Object.entries(legacyPublic))
    expect(owned[key as keyof typeof owned]).toBe(value);
  expect(taskListRoleAllows).toBe(owned.taskListRoleAllows);
  expect(applyFlatReorder).toBe(owned.applyFlatReorder);
  expect(TaskPickerModal).toBe(owned.TaskPickerModal);
  expect(applyOrderedReorder).toBe(ownedReorder);
});
it('uses the existing host Auth and bootstrap Context with the public picker', () => {
  const fetcher = vi.spyOn(globalThis, 'fetch');
  render(
    <AuthContext.Provider
      value={{ token: 'synthetic', user: { id: 'owner' } } as AuthContextValue}
    >
      <AppBootstrapProvider
        value={{
          data: {
            apps: [{ app_id: 'pms', enabled: false }],
          } as AppsBootstrapResponse,
          loading: false,
          error: null,
          reload: () => undefined,
        }}
      >
        <owned.TaskPickerModal
          isOpen
          onPick={() => undefined}
          onClose={() => undefined}
        />
      </AppBootstrapProvider>
    </AuthContext.Provider>,
  );
  expect(screen.getByRole('alert').textContent).toContain(
    'accessNotice.blockedAction',
  );
  expect(fetcher).not.toHaveBeenCalled();
  fetcher.mockRestore();
});
it('keeps the private mapped error constructor identical through either entry', async () => {
  const fetcher = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(
      async () =>
        new Response(JSON.stringify({ detail: 'Denied' }), { status: 403 }),
    );
  try {
    const previous = await legacyApi
      .listPmsTaskLists('synthetic')
      .catch((error: unknown) => error);
    const current = await owned
      .listPmsTaskLists('synthetic')
      .catch((error: unknown) => error);
    expect(previous).toBeInstanceOf(Error);
    expect(current).toBeInstanceOf(Error);
    expect(Object.getPrototypeOf(current)).toBe(
      Object.getPrototypeOf(previous),
    );
    expect(current).toMatchObject({ status: 403, message: 'Denied' });
  } finally {
    fetcher.mockRestore();
  }
});
