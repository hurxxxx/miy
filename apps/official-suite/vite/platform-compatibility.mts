import type { Plugin } from 'vite';

/** One build input owns both immutable JavaScript identity and server metadata. */
export function officialPlatformCompatibility(buildId = ''): Plugin {
  const fixedBuildId = buildId.trim();
  if (fixedBuildId && !/^[A-Za-z0-9._-]{1,128}$/.test(fixedBuildId))
    throw new Error('official_platform_compatibility_invalid');
  return {
    name: 'miy-official-platform-compatibility',
    config() {
      return {
        define: {
          __MIY_OFFICIAL_PLATFORM_BUILD_ID__: JSON.stringify(fixedBuildId),
        },
      };
    },
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: '.miy-platform-build-id',
        source: `${fixedBuildId}\n`,
      });
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const pathname = request.url?.split('?', 1)[0];
        if (
          pathname !== '/official-suite/platform-build.json' &&
          pathname !== '/platform-build.json'
        )
          return next();
        response.writeHead(200, {
          'Content-Type': 'application/json',
          'Cache-Control': 'no-store',
        });
        response.end(
          JSON.stringify({ platform_build_id: fixedBuildId || null }),
        );
      });
    },
  };
}
