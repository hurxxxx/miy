import i18n from 'i18next';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  listMailAccounts,
  listMailMessages,
  syncMailAccount,
} from './mail-api';

const clientMocks = vi.hoisted(() => ({
  apiFetchJson: vi.fn(),
  apiFetchJsonWithMappedError: vi.fn(),
}));

vi.mock('@miy/platform-web/api-client', () => clientMocks);
beforeAll(async () => {
  await i18n.init({
    lng: 'en',
    fallbackLng: 'en',
    resources: {
      en: { apps: { mail: { errors: { loadFailed: 'Mail load failed' } } } },
      ko: { apps: { mail: { errors: { loadFailed: '메일 조회 실패' } } } },
    },
  });
});

describe('personal Mail API paths', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clientMocks.apiFetchJsonWithMappedError.mockResolvedValue({});
  });

  it('consumes the host initialized i18next singleton after locale changes', async () => {
    clientMocks.apiFetchJsonWithMappedError.mockImplementation(
      async (_path, _token, _options, mapError) => {
        throw mapError({});
      },
    );
    await i18n.changeLanguage('en');
    await expect(listMailAccounts('token-1')).rejects.toThrow(
      'Mail load failed',
    );
    await i18n.changeLanguage('ko');
    await expect(listMailAccounts('token-1')).rejects.toThrow('메일 조회 실패');
  });

  it('uses the global API prefix without a workspace slug', async () => {
    await listMailAccounts('token-1');
    await listMailMessages('token-1', { unread: true, limit: 25 });
    await syncMailAccount('token-1', 'account/1');

    expect(
      clientMocks.apiFetchJsonWithMappedError.mock.calls.map(([path]) => path),
    ).toEqual([
      '/api/v1/mail/accounts',
      '/api/v1/mail/messages?unread=true&limit=25',
      '/api/v1/mail/accounts/account%2F1/sync',
    ]);
  });
});
