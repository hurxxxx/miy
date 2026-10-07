import {
  AuthContext,
  type AuthContextValue,
} from '@miy/platform-web/auth-context';
import { AiReportArtifact, ChatbotView } from '@miy/platform-web/chatbot';
import { chatbotMessages } from '@miy/platform-web/chatbot/messages';
import { chatbotModule } from '@miy/platform-web/chatbot/module';
import { ChatbotSidebarPortal } from '@miy/platform-web/chatbot/sidebar';
import { filesModule as ownedFiles } from '@miy/official-suite-web/files/module';
import { filesMessages } from '@miy/official-suite-web/files/messages';
import { FilesChatView as OwnedFilesChat } from '@miy/official-suite-web/files/views/FilesChatView';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { ChatbotView as LegacyChat } from '@/src/app-modules/chatbot/public-api';
import { chatbotModule as legacyChatModule } from '@/src/app-modules/chatbot';
import { resources } from '../../platform/i18n/resources';
import { filesModule } from './index';
import { FilesChatView } from './views/FilesChatView';
import type { AppSidebarRenderContext } from '@miy/platform-web/routing/sidebar-types';

const legacyChatSidebar = legacyChatModule.sidebarConfig;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it('keeps module/view/route/sidebar/provider objects through old composition', () => {
  expect(filesModule).toBe(ownedFiles);
  expect(filesModule.shellProviders[0]).toBe(ownedFiles.shellProviders[0]);
  expect(filesModule.appRoutes).toBe(ownedFiles.appRoutes);
  expect(filesModule.sidebarConfig).toBe(ownedFiles.sidebarConfig);
  expect(FilesChatView).toBe(OwnedFilesChat);
  expect(LegacyChat).toBe(ChatbotView);
  expect(legacyChatModule).toBe(chatbotModule);
});

it('composes exact canonical common and Files messages for both locales', () => {
  for (const locale of ['ko-KR', 'en-US'] as const) {
    expect(resources[locale].apps.ai).toBe(chatbotMessages[locale].ai);
    expect(resources[locale].apps.hermesWorkspace).toBe(
      chatbotMessages[locale].hermesWorkspace,
    );
    expect(resources[locale].apps.files).toBe(filesMessages[locale]);
  }
});

it('uses one Portal host registry across old shell config and shared route list', () => {
  const close = vi.fn();
  const context = (onNavigate?: () => void): AppSidebarRenderContext => ({
    activeAppId: 'chatbot',
    activeNavItemId: '',
    currentPathname: '/apps/chatbot',
    enabledShellAppIds: ['chatbot'],
    canReadApp: true,
    filteredItems: [],
    user: null,
    navigate: vi.fn(),
    isCategoryExpanded: () => true,
    toggleCategory: vi.fn(),
    onNavigate,
  });
  function Surface({ mobile }: { mobile: boolean }) {
    return (
      <>
        <div data-testid="desktop">
          {legacyChatSidebar.beforeCategories?.(context())}
        </div>
        {mobile && (
          <div data-testid="mobile">
            {legacyChatSidebar.beforeCategories?.(context(close))}
          </div>
        )}
        <ChatbotSidebarPortal>
          {(onNavigate) => (
            <button onClick={onNavigate}>Current conversation</button>
          )}
        </ChatbotSidebarPortal>
      </>
    );
  }
  const view = render(<Surface mobile={false} />);
  expect(screen.getByTestId('desktop').textContent).toBe(
    'Current conversation',
  );
  view.rerender(<Surface mobile />);
  expect(screen.getAllByRole('button')).toHaveLength(1);
  expect(screen.getByTestId('mobile').textContent).toBe('Current conversation');
  fireEvent.click(screen.getByRole('button'));
  expect(close).toHaveBeenCalledOnce();
  view.rerender(<Surface mobile={false} />);
  expect(screen.getByTestId('desktop').textContent).toBe(
    'Current conversation',
  );
  view.unmount();
  render(
    <ChatbotSidebarPortal>
      {() => <button>Detached conversation</button>}
    </ChatbotSidebarPortal>,
  );
  expect(screen.queryByRole('button')).toBeNull();
});

it('reads a shared artifact through the actual host auth Context and common client', async () => {
  const requests: Array<{ path: string; token: string | null }> = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      requests.push({
        path,
        token: new Headers(init?.headers).get('Authorization'),
      });
      if (path.endsWith('/sources'))
        return new Response(JSON.stringify({ items: [] }));
      if (path.endsWith('/artifacts/synthetic-report'))
        return new Response(
          JSON.stringify({
            id: 'synthetic-report',
            artifact_number: 'SYN-1',
            kind: 'report',
            status: 'completed',
            title: 'Synthetic report',
            content_markdown: '# Shared result',
            created_at: null,
          }),
        );
      throw new Error('Unexpected synthetic request');
    }),
  );
  render(
    <AuthContext.Provider
      value={{ token: 'synthetic-host-token' } as AuthContextValue}
    >
      <MemoryRouter>
        <AiReportArtifact
          artifact={{
            id: 'synthetic-report',
            type: 'document',
            title: 'Synthetic report',
            content: 'Waiting',
            status: 'closed',
            kind: 'report',
          }}
        />
      </MemoryRouter>
    </AuthContext.Provider>,
  );
  expect(await screen.findByText('SYN-1')).toBeTruthy();
  expect(
    await screen.findByRole('heading', { name: 'Shared result' }),
  ).toBeTruthy();
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(
    requests.every(
      (request) => request.token === 'Bearer synthetic-host-token',
    ),
  ).toBe(true);
});
