export const COMMUNITY_CHANNELS_CHANGED_EVENT =
  'miy:community-channels-changed';

export function emitCommunityChannelsChanged(): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.dispatchEvent(new Event(COMMUNITY_CHANNELS_CHANGED_EVENT));
}
