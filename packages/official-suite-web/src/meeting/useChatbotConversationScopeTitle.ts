import { useEffect } from 'react';

import { getMeeting } from './index';
import type {
  ChatbotViewState,
  ChatbotViewStateUpdater,
} from '@miy/platform-web/chatbot/state-types';

export function useChatbotConversationScopeTitle({
  scopeInfo,
  setScopeInfo,
  token,
}: {
  scopeInfo: ChatbotViewState['scopeInfo'];
  setScopeInfo: (
    value: ChatbotViewStateUpdater<ChatbotViewState['scopeInfo']>,
  ) => void;
  token: string | null;
}) {
  useEffect(() => {
    if (!token) return;
    if (!scopeInfo || scopeInfo.ref !== 'meeting' || scopeInfo.title !== null) {
      return;
    }
    let cancelled = false;
    const resourceId = scopeInfo.resourceId;
    getMeeting(token, resourceId)
      .then((meeting) => {
        if (cancelled) return;
        setScopeInfo((prev) =>
          prev &&
          prev.ref === 'meeting' &&
          prev.resourceId === resourceId &&
          prev.title === null
            ? { ...prev, title: meeting.title }
            : prev,
        );
      })
      .catch(() => {
        // Silent fallback: the chip still renders with the generic label.
      });
    return () => {
      cancelled = true;
    };
  }, [setScopeInfo, token, scopeInfo]);
}
