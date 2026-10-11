import { OFFICIAL_APP_MODULES } from './official-app-modules';
import { codexConsoleModule } from '@/src/app-modules/codex-console';
import { tetrisModule } from '@/src/app-modules/tetris';
import { agentTerminalModule } from '@/src/app-modules/agent-terminal';
import { chatbotModule } from '@miy/platform-web/chatbot/module';
import { homeModule } from '@/src/app-modules/home';
import { retrievalSearchModule } from '@/src/app-modules/retrieval-search';
import { settingsModule } from '@/src/app-modules/settings';
import {
  tetrisManifest,
  agentTerminalManifest,
  codexConsoleManifest,
  announcementsManifest,
  bentoManifest,
  chatbotManifest,
  communityManifest,
  diagramsManifest,
  docsManifest,
  filesManifest,
  homeManifest,
  mailManifest,
  meetingManifest,
  plannerManifest,
  pmsManifest,
  recordingManifest,
  retrievalSearchManifest,
  settingsManifest,
  videoChatManifest,
  whiteboardManifest,
} from './app-contract-manifests';
import type { FeatureModuleRegistryInput } from './feature-module-registry';

export {
  tetrisManifest,
  agentTerminalManifest,
  codexConsoleManifest,
  announcementsManifest,
  bentoManifest,
  chatbotManifest,
  communityManifest,
  diagramsManifest,
  docsManifest,
  filesManifest,
  homeManifest,
  mailManifest,
  meetingManifest,
  plannerManifest,
  pmsManifest,
  recordingManifest,
  retrievalSearchManifest,
  settingsManifest,
  videoChatManifest,
  whiteboardManifest,
};

/** Executable identities are leaf apps. Categories never own routes. */
export const DEFAULT_APP_MODULES = [
  homeModule,
  agentTerminalModule,
  codexConsoleModule,
  chatbotModule,
  ...OFFICIAL_APP_MODULES,
  retrievalSearchModule,
  tetrisModule,
] as const;

/** Shell-owned navigation surfaces are not executable app identities. */
export const DEFAULT_SHELL_MODULES = [settingsModule] as const;

export const DEFAULT_APP_MODULE_MANIFESTS = DEFAULT_APP_MODULES.map(
  (module) => module.manifest,
);

export const DEFAULT_SHELL_MODULE_MANIFESTS = DEFAULT_SHELL_MODULES.map(
  (module) => module.manifest,
);

export const DEFAULT_FEATURE_MODULES: readonly FeatureModuleRegistryInput[] = [
  announcementsManifest,
] as const;

export const DEFAULT_FEATURE_MODULE_MANIFESTS = DEFAULT_FEATURE_MODULES.map(
  (module) => ('manifest' in module ? module.manifest : module),
);

export const DEFAULT_PLATFORM_MODULE_MANIFESTS = [
  ...DEFAULT_APP_MODULE_MANIFESTS,
  ...DEFAULT_FEATURE_MODULE_MANIFESTS,
] as const;
