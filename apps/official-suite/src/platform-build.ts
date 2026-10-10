/** This value is fixed in the reviewed official artifact, never discovered from core. */
export async function readPlatformCompatibilityBuild(
  fetcher: typeof fetch = fetch,
): Promise<string> {
  const response = await fetcher('/official-suite/platform-build.json', {
    cache: 'no-store',
    credentials: 'same-origin',
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok)
    throw new Error('official_platform_compatibility_unavailable');
  const metadata: unknown = await response.json();
  if (
    !metadata ||
    typeof metadata !== 'object' ||
    !('platform_build_id' in metadata)
  )
    throw new Error('official_platform_compatibility_invalid');
  const value = metadata.platform_build_id;
  if (value === null) return '';
  if (typeof value !== 'string' || !/^[A-Za-z0-9._-]{1,128}$/.test(value)) {
    throw new Error('official_platform_compatibility_invalid');
  }
  return value;
}
