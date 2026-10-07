import { ApiError, apiBasePath } from './api';
import type { components } from './api.generated';

type Status = components['schemas']['Status'];
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const revision = /^[0-9a-f]{40}$/;
const digest = /^sha256:[0-9a-f]{64}$/;
const appId = /^[a-z][a-z0-9-]{1,63}$/;
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const matches = (value: unknown, pattern: RegExp) =>
  typeof value === 'string' && pattern.test(value);
const date = (value: unknown) =>
  typeof value === 'string' &&
  /(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
  Number.isFinite(Date.parse(value));
const fail = (): never => {
  throw new ApiError('registration_invalid_response');
};
function origin(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  try {
    const parsed = new URL(value);
    return (
      parsed.origin === value &&
      !parsed.username &&
      !parsed.password &&
      (parsed.protocol === 'https:' ||
        (parsed.protocol === 'http:' &&
          ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)))
    );
  } catch {
    return false;
  }
}
export function checkedRegistrationStatus(
  value: unknown,
  taskId: string,
  prior?: Status | null,
): Status {
  if (
    !object(value) ||
    value.task_id !== taskId ||
    !matches(value.operation_id, uuid) ||
    (prior && value.operation_id !== prior.operation_id) ||
    typeof value.enabled !== 'boolean' ||
    (value.authorization_origin !== null &&
      !origin(value.authorization_origin)) ||
    ![
      'required',
      'pending',
      'exchanging',
      'ready',
      'failed',
      'expired',
      'other_session',
    ].includes(String(value.authorization_state)) ||
    !['unsubmitted', 'unknown', 'registered', 'rejected'].includes(
      String(value.state),
    ) ||
    (value.expires_at !== null && !date(value.expires_at)) ||
    (value.source_revision !== null &&
      !matches(value.source_revision, revision)) ||
    (value.failure_code !== null &&
      (typeof value.failure_code !== 'string' ||
        value.failure_code.length > 80))
  )
    return fail();
  if (value.policy !== null) {
    const p = value.policy;
    if (
      !object(p) ||
      !matches(p.app_id, appId) ||
      !origin(p.origin) ||
      !['web-api-v1', 'web-api-postgres-v1'].includes(
        String(p.runtime_profile),
      ) ||
      !Array.isArray(p.requested_permissions) ||
      p.requested_permissions.length > 4 ||
      p.requested_permissions.some(
        (permission) =>
          ![
            'identity:read',
            'data:read',
            'data:write',
            'files:read-selected',
          ].includes(permission),
      ) ||
      new Set(p.requested_permissions).size !== p.requested_permissions.length
    )
      return fail();
  }
  if (
    value.authorization_state === 'ready' &&
    (value.policy === null || value.expires_at === null)
  )
    return fail();
  if (value.receipt !== null) {
    const r = value.receipt;
    if (
      !object(r) ||
      r.operation_id !== value.operation_id ||
      !matches(r.app_id, appId) ||
      !matches(r.installation_id, uuid) ||
      !matches(r.definition_digest, digest) ||
      !matches(r.source_revision, revision) ||
      !date(r.created_at) ||
      (object(value.policy) && r.app_id !== value.policy.app_id) ||
      (value.source_revision !== null &&
        r.source_revision !== value.source_revision)
    )
      return fail();
  }
  if (value.state === 'registered' && value.receipt === null) return fail();
  return value as Status;
}
export function checkedAuthorizationUrl(
  value: unknown,
  status: Status,
  prior?: Status | null,
): string {
  if (
    typeof value !== 'string' ||
    !status.policy ||
    !status.authorization_origin ||
    (prior?.authorization_origin &&
      prior.authorization_origin !== status.authorization_origin)
  )
    return fail();
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return fail();
  }
  const keys = [
    'v',
    'request_id',
    'operation_id',
    'audience',
    'code_challenge',
    'app_id',
    'development_origin',
    'runtime_profile',
    'requested_permissions',
  ];
  const q = url.searchParams;
  if (
    url.origin !== status.authorization_origin ||
    url.pathname !== '/apps/authorize-registration' ||
    url.username ||
    url.password ||
    url.hash ||
    q.size !== keys.length ||
    keys.some((key) => q.getAll(key).length !== 1) ||
    q.get('v') !== '1' ||
    !matches(q.get('request_id'), uuid) ||
    q.get('operation_id') !== status.operation_id ||
    q.get('audience') !==
      window.location.origin + apiBasePath.replace(/\/api$/, '') ||
    !matches(q.get('code_challenge'), /^[A-Za-z0-9_-]{43}$/) ||
    q.get('app_id') !== status.policy.app_id ||
    q.get('development_origin') !== status.policy.origin ||
    q.get('runtime_profile') !== status.policy.runtime_profile ||
    q.get('requested_permissions') !==
      [...status.policy.requested_permissions].sort().join(',')
  )
    return fail();
  return url.toString();
}
