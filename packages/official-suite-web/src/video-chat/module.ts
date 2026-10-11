import { videoChatManifest } from '../manifests/video-chat';
import { videoChatAppRoutes } from './routes';

export { videoChatAppRoutes, videoChatManifest };

export const videoChatModule = {
  manifest: videoChatManifest,
  appRoutes: videoChatAppRoutes,
} as const;
