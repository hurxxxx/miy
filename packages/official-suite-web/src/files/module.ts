import { FileUploadProvider } from './index';
import { filesManifest } from '../manifests/files';
import { filesAppRoutes } from './routes';
import { filesSidebarConfig } from './sidebar';

export {
  filesAppRoutes,
  filesManifest,
  filesSidebarConfig,
  FileUploadProvider,
};

export const filesModule = {
  manifest: filesManifest,
  shellProviders: [FileUploadProvider],
  sidebarConfig: filesSidebarConfig,
  appRoutes: filesAppRoutes,
} as const;
