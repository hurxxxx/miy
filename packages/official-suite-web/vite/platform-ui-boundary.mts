import type { Plugin } from 'vite';

/** Independence means official business components cannot ship inside the portal. */
export function platformUiBoundary(): Plugin {
  return {
    name: 'miy-platform-ui-boundary',
    generateBundle(_options, output) {
      for (const chunk of Object.values(output)) {
        if (chunk.type !== 'chunk') continue;
        for (const [id, module] of Object.entries(chunk.modules)) {
          if (
            module.renderedLength > 0 &&
            /packages\/official-suite-web\/src\/(?:modules\.|[^/]+\/(?:views\/|sidebar(?:\/|\.)|module\.|routes\.|UnifiedCalendar\.|unified-calendar-adapter\.))/.test(
              id.replaceAll('\\', '/'),
            )
          ) {
            this.error(
              'Official business UI must run in the official artifact. Use manifests, summary clients or document navigation in the portal.',
            );
          }
        }
      }
    },
  };
}
