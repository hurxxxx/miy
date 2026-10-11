import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import {
  AuthContext,
  type AuthContextValue,
} from '@miy/platform-web/auth-context';
import {
  AppBootstrapProvider,
  type AppsBootstrapResponse,
} from '@miy/platform-web/apps';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { TaskPickerModal } from './TaskPickerModal';
import { listTaskListTasks } from '../api/pms-api';
vi.mock('../api/pms-api', async (original) => ({
  ...(await original<typeof import('../api/pms-api')>()),
  listTaskListTasks: vi.fn(),
}));
beforeEach(async () => {
  await i18n.use(initReactI18next).init({
    lng: 'en',
    fallbackLng: 'en',
    resources: {
      en: {
        apps: {
          pms: {
            taskPicker: {
              title: 'Select task',
              description: 'Choose a task',
              searchPlaceholder: 'Search tasks',
            },
          },
        },
        common: { actions: { close: 'Close', search: 'Search' } },
      },
      ko: {
        apps: {
          pms: {
            taskPicker: {
              title: '업무 선택',
              description: '업무를 선택하세요',
              searchPlaceholder: '업무 검색',
            },
          },
        },
        common: { actions: { close: '닫기', search: '검색' } },
      },
    },
  });
  vi.mocked(listTaskListTasks).mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 50,
  } as Awaited<ReturnType<typeof listTaskListTasks>>);
});
afterEach(cleanup);
it.each([
  ['en', 'Select task', 'Close', 'Search'],
  ['ko', '업무 선택', '닫기', '검색'],
])(
  'uses the host %s catalog and accessible shared Dialog controls',
  async (locale, title, close, search) => {
    await i18n.changeLanguage(locale);
    render(
      <AuthContext.Provider
        value={
          { token: 'synthetic', user: { id: 'owner' } } as AuthContextValue
        }
      >
        <AppBootstrapProvider
          value={{
            data: {
              apps: [{ app_id: 'pms', enabled: true }],
            } as AppsBootstrapResponse,
            error: null,
            loading: false,
            reload: () => undefined,
          }}
        >
          <TaskPickerModal
            isOpen
            fixedTaskListId="list-one"
            onPick={() => undefined}
            onClose={() => undefined}
          />
        </AppBootstrapProvider>
      </AuthContext.Provider>,
    );
    expect(await screen.findByRole('dialog', { name: title })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: close })).toHaveLength(2);
    expect(screen.getByRole('textbox', { name: search })).toBeTruthy();
  },
);
