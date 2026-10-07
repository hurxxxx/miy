import { beforeEach, expect, it, vi } from 'vitest';
import { apiFetchJson } from '@/src/platform/api/client';
import { getIndependentApps } from './independent-apps-api';

vi.mock('@/src/platform/api/client', () => ({ apiFetchJson: vi.fn() }));
beforeEach(() => vi.clearAllMocks());

function response(page: number, total: number, revision = 'same') {
  return {
    page,
    page_size: 200,
    total,
    catalog_revision: revision,
    items: Array.from(
      { length: Math.min(200, total - (page - 1) * 200) },
      (_, index) => ({
        definition: {
          definition: { app_id: `arbitrary-${(page - 1) * 200 + index}` },
        },
      }),
    ),
  };
}

it('reads every page beyond 200 without dropping registrations', async () => {
  vi.mocked(apiFetchJson)
    .mockResolvedValueOnce(response(1, 405))
    .mockResolvedValueOnce(response(2, 405))
    .mockResolvedValueOnce(response(3, 405));
  const result = await getIndependentApps(
    'test-token',
    new AbortController().signal,
  );
  expect(result).toHaveLength(405);
  expect(result[404].definition.definition.app_id).toBe('arbitrary-404');
  expect(apiFetchJson).toHaveBeenCalledTimes(3);
});

it('does not publish a partial snapshot across changing catalog pages', async () => {
  vi.mocked(apiFetchJson)
    .mockResolvedValueOnce(response(1, 201))
    .mockResolvedValueOnce(response(2, 201, 'changed'));
  await expect(
    getIndependentApps('test-token', new AbortController().signal),
  ).rejects.toThrow('incomplete');
});

it('rejects duplicate definitions even when the total count matches', async () => {
  const data = response(1, 2);
  data.items[1] = data.items[0];
  vi.mocked(apiFetchJson).mockResolvedValueOnce(data);
  await expect(
    getIndependentApps('test-token', new AbortController().signal),
  ).rejects.toThrow('duplicate');
});
