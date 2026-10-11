import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type * as Hermes from '@miy/platform-web/ai/hermes-agent-api';
import type * as Conversations from '@miy/platform-web/ai/conversations-api';
import type * as Tools from '@miy/platform-web/ai/ai-api';
import type * as Chat from '@miy/platform-web/chatbot';
import type * as Client from '@miy/platform-web/api-client';

beforeEach(async () => {
  vi.resetModules();
  window.localStorage.clear();
  const actual = await vi.importActual<typeof import('i18next')>('i18next');
  const singleton = actual.createInstance();
  vi.spyOn(singleton, 'init');
  vi.doMock('i18next', () => ({ ...actual, default: singleton }));
});
afterEach(() => {
  vi.doUnmock('i18next');
  window.localStorage.clear();
  vi.restoreAllMocks();
});
it.each([
  [null, 'ko-KR'],
  ['en-US', 'en-US'],
  ['unsupported', 'ko-KR'],
])(
  'keeps cold shared transports inert and the old initializer single for %s',
  async (storedLocale, expectedLocale) => {
    if (storedLocale) window.localStorage.setItem('miy:locale', storedLocale);
    const hermes = await vi.importActual<typeof Hermes>(
      '@miy/platform-web/ai/hermes-agent-api',
    );
    const conversations = await vi.importActual<typeof Conversations>(
      '@miy/platform-web/ai/conversations-api',
    );
    const tools = await vi.importActual<typeof Tools>(
      '@miy/platform-web/ai/ai-api',
    );
    const commonChat = await vi.importActual<typeof Chat>(
      '@miy/platform-web/chatbot',
    );
    const singleton = (await import('i18next')).default;
    expect(singleton.isInitialized).not.toBe(true);
    expect(singleton.init).not.toHaveBeenCalled();
    const oldChat = await import('../public-api');
    expect(oldChat.ChatbotView).toBe(commonChat.ChatbotView);
    expect(oldChat.ChatComposer).toBe(commonChat.ChatComposer);
    expect(oldChat.AiReportArtifact).toBe(commonChat.AiReportArtifact);
    const oldHermes = await import('./hermes-agent-api');
    const oldConversations = await import('./conversations-api');
    const oldTools = await import('../../../platform/ai/ai-api');
    expect(singleton.isInitialized).toBe(true);
    expect(singleton.init).toHaveBeenCalledTimes(1);
    for (const [old, owner] of [
      [oldHermes, hermes],
      [oldConversations, conversations],
      [oldTools, tools],
    ] as const) {
      expect(Object.keys(old).sort()).toEqual(Object.keys(owner).sort());
      for (const [key, value] of Object.entries(old))
        expect((owner as Record<string, unknown>)[key]).toBe(value);
    }
    const client = await vi.importActual<typeof Client>(
      '@miy/platform-web/api-client',
    );
    expect(client.jsonHeaders('synthetic')).toMatchObject({
      'Accept-Language': expectedLocale,
      'X-MIY-Locale': expectedLocale,
    });
    expect(new oldHermes.HermesAgentApiError(403, 'synthetic')).toBeInstanceOf(
      hermes.HermesAgentApiError,
    );
    expect(
      new oldConversations.ConversationsApiError(403, 'synthetic'),
    ).toBeInstanceOf(conversations.ConversationsApiError);
    expect(new oldTools.AiApiError(403, 'synthetic')).toBeInstanceOf(
      tools.AiApiError,
    );
  },
);
