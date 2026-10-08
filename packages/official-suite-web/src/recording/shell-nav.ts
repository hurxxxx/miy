import { getCoreShellSearchParams as getShellSearchParams } from '@miy/core-web/shell-navigation';
import type { AppShellNavResolver } from '@miy/core-web/navigation-types';

export const recordingShellNavResolver: AppShellNavResolver = ({ path }) => {
  const params = getShellSearchParams(path);
  const view = params.get('view');
  const category = params.get('category');

  if (view === 'archived') return 'recording-archived';
  if (view === 'failed') return 'recording-failed';
  if (view === 'processing') return 'recording-processing';
  if (category === 'meeting') return 'recording-meeting';
  if (category === 'task') return 'recording-task';
  if (category === 'unlinked') return 'recording-unlinked';
  if (view === 'mine' || view === 'needs_review') return 'recording-mine';
  return 'recording-quick';
};
