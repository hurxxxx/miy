import { mailManifest } from '../manifests/mail';
import { mailGlobalRoutes } from './routes';

export { mailGlobalRoutes, mailManifest };

export const mailModule = {
  globalRoutes: mailGlobalRoutes,
  manifest: mailManifest,
} as const;
