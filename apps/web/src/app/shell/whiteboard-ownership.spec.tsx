import { expect, it } from 'vitest';
import * as publicWhiteboard from '@miy/official-suite-web/whiteboard';
import * as oldWhiteboard from '@/src/app-modules/whiteboard/public-api';
import * as realtime from '@miy/platform-web/realtime';
import * as oldRealtime from '@/src/platform/realtime/realtime-provider';
import { createRealtimeRuntime } from '@/src/platform/realtime/realtime-runtime';
import {
  DirectoryPicker,
  listDirectoryOptions,
} from '@miy/platform-web/directory';
import { DirectoryPicker as oldDirectory } from '@/src/platform/directory/DirectoryPicker';
import { listDirectoryOptions as oldListDirectory } from '@/src/platform/directory/directory-api';
import * as users from '@miy/platform-web/users';
import { UserSearchMultiSelect as oldUsers } from '@/src/platform/users/UserSearchMultiSelect';
import * as oldUserModel from '@/src/platform/users/user-option-picker-model';

it('retains the same public Whiteboard API and lazy integration component objects', () => {
  expect(Object.keys(oldWhiteboard)).toEqual(Object.keys(publicWhiteboard));
  for (const [key, value] of Object.entries(oldWhiteboard))
    expect(publicWhiteboard[key as keyof typeof publicWhiteboard]).toBe(value);
});

it('keeps root realtime initialization and cross-app consumers on one provider and runtime', () => {
  for (const [key, value] of Object.entries(oldRealtime))
    expect(realtime[key as keyof typeof realtime]).toBe(value);
  expect(createRealtimeRuntime).toBe(realtime.createRealtimeRuntime);
  expect(oldDirectory).toBe(DirectoryPicker);
  expect(oldListDirectory).toBe(listDirectoryOptions);
  expect(oldUsers).toBe(users.UserSearchMultiSelect);
  for (const [key, value] of Object.entries(oldUserModel))
    expect(users[key as keyof typeof users]).toBe(value);
});
