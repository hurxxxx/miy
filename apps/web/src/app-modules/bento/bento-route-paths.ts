import { buildAppHref } from '@mty/contracts/app-routes';

export function buildBentoHubPath(): string {
  return buildAppHref({ routeId: 'bento.root' });
}

export function buildBentoPresentationPath(documentId: string): string {
  return buildAppHref({
    routeId: 'bento.presentation',
    pathParams: { documentId },
  });
}
