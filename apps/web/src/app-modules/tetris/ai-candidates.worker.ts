import { buildCandidates } from './ai-candidates';
import type { Game } from './engine';

globalThis.onmessage = (event: MessageEvent<Game>) => {
  globalThis.postMessage(buildCandidates(event.data));
};
