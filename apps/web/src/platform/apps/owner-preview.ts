import type { ApiSchema } from '@/src/platform/api/types';
import { isIndependentPermissionList } from './independent-app-permissions';

export type OwnerPreview = ApiSchema<'OwnerPreviewOut'>;
export type OwnerPreviewInput = ApiSchema<'OwnerPreviewPatch'>;

const appIdPattern = /^[a-z][a-z0-9-]{1,63}$/;
const idPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const reasons = [
  'already_deployed',
  'delivery_in_progress',
  'build_in_progress',
  'already_verified',
  'company_disabled',
  'origin_configuration_required',
  'invalid_origin',
];

export function validOwnerPreviewTarget(appId: string, installationId: string) {
  return appIdPattern.test(appId) && idPattern.test(installationId);
}

export function ownerPreviewSettingsPath(
  appId: string,
  installationId: string,
) {
  return `/apps/${encodeURIComponent(appId)}/installed/${encodeURIComponent(installationId)}/setup`;
}

export function ownerPreviewApiPath(appId: string, installationId: string) {
  if (!validOwnerPreviewTarget(appId, installationId))
    throw new Error('invalid-preview-target');
  return `/api/v1/independent-apps/${appId}/installations/${installationId}/owner-preview`;
}

export function parseOwnerPreview(
  value: unknown,
  expected: { appId: string; installationId: string; userId: string },
): OwnerPreview {
  const fail = () => {
    throw new Error('invalid-preview-response');
  };
  if (!value || typeof value !== 'object' || Array.isArray(value))
    return fail();
  const data = value as Record<string, unknown>;
  if (
    data.schema_version !== 1 ||
    data.app_id !== expected.appId ||
    data.installation_id !== expected.installationId ||
    data.owner_user_id !== expected.userId ||
    typeof data.display_name !== 'string' ||
    !data.display_name.trim() ||
    data.display_name.length > 240 ||
    !Number.isSafeInteger(data.generation) ||
    (data.generation as number) < 1 ||
    typeof data.definition_digest !== 'string' ||
    !/^sha256:[0-9a-f]{64}$/.test(data.definition_digest) ||
    typeof data.source_revision !== 'string' ||
    !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(data.source_revision) ||
    !['web-api-v1', 'web-api-postgres-v1'].includes(
      data.runtime_profile as string,
    ) ||
    typeof data.origin !== 'string' ||
    data.origin.length > 300 ||
    typeof data.enabled !== 'boolean' ||
    typeof data.company_enabled !== 'boolean' ||
    typeof data.can_configure !== 'boolean' ||
    (data.can_configure && !data.company_enabled) ||
    (data.can_configure
      ? data.unavailable_reason !== null
      : !reasons.includes(data.unavailable_reason as string)) ||
    !isIndependentPermissionList(data.requested_permissions) ||
    !isIndependentPermissionList(data.granted_permissions) ||
    !data.granted_permissions.every((permission) =>
      (data.requested_permissions as string[]).includes(permission),
    ) ||
    (data.runtime_profile === 'web-api-v1' &&
      data.requested_permissions.some((permission) =>
        permission.startsWith('data:'),
      ))
  )
    return fail();
  let origin: URL;
  try {
    origin = new URL(data.origin);
  } catch {
    return fail();
  }
  if (
    origin.origin !== data.origin ||
    origin.username ||
    origin.password ||
    (origin.protocol !== 'https:' &&
      !(
        origin.protocol === 'http:' &&
        ['localhost', '127.0.0.1', '[::1]'].includes(origin.hostname)
      ))
  )
    return fail();
  return value as OwnerPreview;
}
