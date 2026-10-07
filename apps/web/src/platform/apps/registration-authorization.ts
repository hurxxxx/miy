import type {
  ApiJsonRequestBody,
  ApiJsonResponse,
} from '@/src/platform/api/types';
import { registrationOperation } from './independent-app-registration';
import { independentAppPermissions } from './independent-app-permissions';

export const REGISTRATION_AUTHORIZATION_ROUTE = '/apps/authorize-registration';
export const REGISTRATION_AUTHORIZATION_API =
  '/api/v1/independent-apps/bootstrap-authorizations';

export type RegistrationAuthorizationInput = ApiJsonRequestBody<
  typeof REGISTRATION_AUTHORIZATION_API,
  'post'
>;
export type RegistrationAuthorizationResponse = ApiJsonResponse<
  typeof REGISTRATION_AUTHORIZATION_API,
  'post'
>;

const queryFields = [
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
const supportedPermissions: readonly string[] = independentAppPermissions;
const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

function exactAddress(value: string, audience: boolean): string {
  const url = new URL(value);
  const path = url.pathname === '/' ? '' : url.pathname;
  if (
    value.length > (audience ? 500 : 300) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    (url.protocol !== 'https:' &&
      !(
        url.protocol === 'http:' &&
        ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      )) ||
    value !== url.origin + path ||
    (audience ? !/^(?:\/[A-Za-z0-9_-]+)*$/.test(path) : path !== '')
  )
    throw new TypeError('Invalid authorization address');
  return value;
}

/** The URL contains only a bounded proposal; the Core independently authorizes it. */
export function parseRegistrationAuthorizationQuery(
  search: string,
): RegistrationAuthorizationInput {
  if (search.length > 4096) throw new TypeError('Invalid authorization query');
  const query = new URLSearchParams(search);
  if (
    query.size !== queryFields.length ||
    queryFields.some((key) => query.getAll(key).length !== 1) ||
    query.get('v') !== '1'
  )
    throw new TypeError('Invalid authorization query');
  const requestId = registrationOperation(query.get('request_id'));
  const operationId = registrationOperation(query.get('operation_id'));
  const appId = query.get('app_id') ?? '';
  const challenge = query.get('code_challenge') ?? '';
  const profile = query.get('runtime_profile');
  const rawPermissions = query.get('requested_permissions') ?? '';
  const permissions = rawPermissions ? rawPermissions.split(',') : [];
  if (
    !requestId ||
    !operationId ||
    !/^[a-z][a-z0-9-]{1,63}$/.test(appId) ||
    !/^[A-Za-z0-9_-]{43}$/.test(challenge) ||
    !['web-api-v1', 'web-api-postgres-v1'].includes(profile ?? '') ||
    permissions.length > supportedPermissions.length ||
    (profile !== 'web-api-postgres-v1' &&
      permissions.some((permission) => permission.startsWith('data:'))) ||
    new Set(permissions).size !== permissions.length ||
    permissions.some((permission) => !supportedPermissions.includes(permission))
  )
    throw new TypeError('Invalid authorization proposal');
  return {
    schema_version: 1,
    request_id: requestId,
    operation_id: operationId,
    audience: exactAddress(query.get('audience') ?? '', true),
    code_challenge: challenge,
    policy: {
      app_id: appId,
      origin: exactAddress(query.get('development_origin') ?? '', false),
      runtime_profile: profile,
      requested_permissions: permissions.sort(),
    },
  } as RegistrationAuthorizationInput;
}

function expiry(value: unknown): number {
  if (
    typeof value !== 'string' ||
    value.length > 64 ||
    !/(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  )
    return NaN;
  return Date.parse(value);
}

/** A code may be posted only for the exact request and still-current owner. */
export function parseRegistrationAuthorizationResponse(
  value: unknown,
  expected: RegistrationAuthorizationInput,
  actorUserId: string,
): RegistrationAuthorizationResponse {
  if (!object(value) || !object(value.policy))
    throw new TypeError('Invalid authorization response');
  const codeExpiry = expiry(value.code_expires_at);
  const grantExpiry = expiry(value.expires_at);
  if (
    value.schema_version !== 1 ||
    typeof value.id !== 'string' ||
    registrationOperation(value.id) !== value.id ||
    value.request_id !== expected.request_id ||
    value.operation_id !== expected.operation_id ||
    value.actor_user_id !== actorUserId ||
    value.audience !== expected.audience ||
    value.callback_url !==
      `${expected.audience}/api/registration-authorizations/callback` ||
    value.policy.app_id !== expected.policy.app_id ||
    value.policy.origin !== expected.policy.origin ||
    value.policy.runtime_profile !== expected.policy.runtime_profile ||
    JSON.stringify(value.policy.requested_permissions) !==
      JSON.stringify(expected.policy.requested_permissions) ||
    typeof value.code !== 'string' ||
    !/^miyrc_[A-Za-z0-9_-]{43}$/.test(value.code) ||
    !Number.isFinite(codeExpiry) ||
    !Number.isFinite(grantExpiry) ||
    codeExpiry <= Date.now() ||
    codeExpiry > grantExpiry
  )
    throw new TypeError('Invalid authorization response');
  return value as RegistrationAuthorizationResponse;
}

/** Code transport is a form body; credentials never enter the callback URL. */
export function postRegistrationAuthorization(
  response: RegistrationAuthorizationResponse,
): () => void {
  // A document-local policy preserves Origin on HTTPS → HTTP loopback POSTs.
  // The parent's referrer policy, CSP, and authentication cookies are unchanged.
  const frame = document.createElement('iframe');
  frame.hidden = true;
  frame.setAttribute(
    'sandbox',
    'allow-forms allow-top-navigation allow-same-origin',
  );
  document.body.append(frame);
  const cleanup = () => {
    window.removeEventListener('pagehide', cleanup);
    frame.remove();
  };
  const child = frame.contentDocument;
  if (!child) {
    cleanup();
    throw new TypeError('Authorization return unavailable');
  }
  const policy = child.createElement('meta');
  policy.name = 'referrer';
  policy.content = 'origin';
  child.head.append(policy);
  const form = child.createElement('form');
  form.method = 'POST';
  form.action = response.callback_url;
  form.target = '_top';
  form.enctype = 'application/x-www-form-urlencoded';
  for (const [name, value] of Object.entries({
    request_id: response.request_id,
    code: response.code,
  })) {
    const field = child.createElement('input');
    field.type = 'hidden';
    field.name = name;
    field.value = value;
    form.append(field);
  }
  child.body.append(form);
  window.addEventListener('pagehide', cleanup, { once: true });
  try {
    HTMLFormElement.prototype.submit.call(form);
  } catch (error) {
    cleanup();
    throw error;
  }
  // Immediate removal can cancel the queued top-level navigation.
  return cleanup;
}
