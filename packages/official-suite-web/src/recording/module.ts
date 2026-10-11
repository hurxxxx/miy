import { recordingManifest } from '../manifests/recording';
import { recordingAppRoutes } from './routes';
import { recordingShellNavResolver } from './shell-nav';

export { recordingAppRoutes, recordingManifest, recordingShellNavResolver };

export const recordingModule = {
  manifest: recordingManifest,
  shellNavResolver: recordingShellNavResolver,
  appRoutes: recordingAppRoutes,
} as const;
