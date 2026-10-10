import { expect, it, vi } from 'vitest';
import { readPlatformCompatibilityBuild } from './platform-build';

it('uses only the fixed reviewed official metadata and does not discover current core identity', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ platform_build_id: 'reviewed-core-id' })),
    );
  expect(await readPlatformCompatibilityBuild(fetcher)).toBe(
    'reviewed-core-id',
  );
  expect(fetcher.mock.calls).toHaveLength(1);
  expect(fetcher.mock.calls[0][0]).toBe('/official-suite/platform-build.json');
  for (const metadata of [
    {},
    { platform_build_id: '../invalid' },
    { platform_build_id: 123 },
  ]) {
    const invalid = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(metadata)));
    await expect(readPlatformCompatibilityBuild(invalid)).rejects.toThrow(
      'compatibility_invalid',
    );
  }
  expect(
    await readPlatformCompatibilityBuild(
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ platform_build_id: null })),
        ),
    ),
  ).toBe('');
});
