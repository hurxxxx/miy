import { expect, it } from 'vitest';
import * as suite from '@miy/official-suite-web/video-chat';
import * as legacy from './api/video-chat-api';
import { VideoChatView } from './views/VideoChatView';

it('keeps the legacy room API/error and lobby on the exact same public implementations', () => {
  expect(VideoChatView).toBe(suite.VideoChatView);
  for (const key of Object.keys(legacy) as (keyof typeof legacy)[]) {
    expect(legacy[key], key).toBe(suite[key]);
  }
  expect(new legacy.VideoChatApiError(401, 'Expired')).toBeInstanceOf(
    suite.VideoChatApiError,
  );
});
