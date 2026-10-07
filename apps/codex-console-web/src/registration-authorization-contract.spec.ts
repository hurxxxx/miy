import { expect, it } from 'vitest';
import { checkedRegistrationStatus } from './registration-authorization-contract';

const taskId = '8234db11-1931-4572-af3b-0fab1f9f7752';
const status = {
  task_id: taskId,
  operation_id: 'dbf4d2eb-a252-4212-b510-95a7a87d2ec7',
  enabled: true,
  authorization_origin: 'https://miy.example.test',
  authorization_state: 'pending',
  state: 'unsubmitted',
  expires_at: null,
  policy: {
    app_id: 'app-one',
    origin: 'https://preview.example.test',
    runtime_profile: 'web-api-v1',
    requested_permissions: [
      'identity:read',
      'data:read',
      'data:write',
      'files:read-selected',
    ],
  },
  receipt: null,
  failure_code: null,
  source_revision: null,
};

it('accepts the explicit selected-file permission without changing older policies', () => {
  expect(checkedRegistrationStatus(status, taskId)).toEqual(status);
  const priorPolicy = {
    ...status,
    policy: { ...status.policy, requested_permissions: ['identity:read'] },
  };
  expect(checkedRegistrationStatus(priorPolicy, taskId)).toEqual(priorPolicy);
});

it.each([
  ['files:read-all'],
  ['files:read-selected', 'files:read-selected'],
  [...status.policy.requested_permissions, 'identity:read'],
])(
  'rejects unknown, duplicate or oversized permissions %j',
  (...requested_permissions) => {
    expect(() =>
      checkedRegistrationStatus(
        { ...status, policy: { ...status.policy, requested_permissions } },
        taskId,
      ),
    ).toThrow('registration_invalid_response');
  },
);
