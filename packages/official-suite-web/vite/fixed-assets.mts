import { readFile } from 'node:fs/promises';
import type { Plugin } from 'vite';

// Only these two canonical app assets have fixed, existing public URLs.
const assets = [
  {
    fileName: 'recording-sync-sw.js',
    source: new URL('../public/recording-sync-sw.js', import.meta.url),
    contentType: 'text/javascript; charset=utf-8',
  },
  {
    fileName: 'help/pms/user-guide.html',
    source: new URL('../public/help/pms/user-guide.html', import.meta.url),
    contentType: 'text/html; charset=utf-8',
  },
] as const;

/** Preserve fixed app asset URLs in both development and production roots. */
export function officialFixedAssets(): Plugin {
  return {
    name: 'miy-official-fixed-assets',
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const asset = assets.find(
          (candidate) =>
            request.url?.split('?', 1)[0] === `/${candidate.fileName}`,
        );
        if (!asset) {
          next();
          return;
        }
        if (request.method !== 'GET' && request.method !== 'HEAD') {
          response.writeHead(405, { Allow: 'GET, HEAD' });
          response.end();
          return;
        }
        try {
          const bytes = await readFile(asset.source);
          response.writeHead(200, {
            'Content-Type': asset.contentType,
            'Content-Length': bytes.length,
            'Cache-Control': 'no-cache',
            'X-Content-Type-Options': 'nosniff',
          });
          response.end(request.method === 'HEAD' ? undefined : bytes);
        } catch {
          response.writeHead(500, {
            'Content-Type': 'text/plain; charset=utf-8',
            'Cache-Control': 'no-store',
          });
          response.end(
            request.method === 'HEAD' ? undefined : 'Asset unavailable',
          );
        }
      });
    },
    async generateBundle() {
      for (const asset of assets) {
        this.emitFile({
          type: 'asset',
          fileName: asset.fileName,
          source: await readFile(asset.source),
        });
      }
    },
  };
}
