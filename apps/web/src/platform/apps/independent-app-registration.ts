import type { ApiSchema } from '@/src/platform/api/types';
import { isIndependentPermissionList } from './independent-app-permissions';

export const REGISTRATION_ROUTE = '/apps/register';
export const REGISTRATION_FILE_LIMIT = 256 * 1024;
export type RegistrationDraft = {
  schema_version: 1;
  project_id: string;
  binding_version: number;
  app_id: string;
  source_revision: string;
  source_manifest_digest: string;
  definition_digest: string;
  definition: ApiSchema<'AppDefinition'>;
};

const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);
const digest = (value: unknown) =>
  typeof value === 'string' && /^sha256:[a-f0-9]{64}$/.test(value);
export const registrationOperation = (value: string | null) =>
  value &&
  /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value)
    ? value.toLowerCase()
    : null;

export function parseRegistrationReceipt(
  value: unknown,
  expected: {
    operation_id: string;
    app_id?: string;
    source_revision?: string;
    definition_digest?: string;
  },
): ApiSchema<'BootstrapReceipt'> {
  if (
    !object(value) ||
    value.operation_id !== expected.operation_id ||
    typeof value.installation_id !== 'string' ||
    !registrationOperation(value.installation_id) ||
    typeof value.app_id !== 'string' ||
    !/^[a-z][a-z0-9-]{1,63}$/.test(value.app_id) ||
    typeof value.source_revision !== 'string' ||
    !/^[a-f0-9]{40}$/.test(value.source_revision) ||
    !digest(value.definition_digest) ||
    typeof value.created_at !== 'string' ||
    value.created_at.length > 64 ||
    !Number.isFinite(Date.parse(value.created_at)) ||
    Object.entries(expected).some(
      ([key, field]) => field !== undefined && value[key] !== field,
    )
  )
    throw new TypeError();
  return value as ApiSchema<'BootstrapReceipt'>;
}

/** Bound untrusted file rendering. The core independently validates the full definition. */
export function parseRegistrationDraft(text: string): RegistrationDraft {
  if (new TextEncoder().encode(text).length > REGISTRATION_FILE_LIMIT)
    throw new TypeError();
  const value: unknown = JSON.parse(text);
  if (!object(value) || !object(value.definition)) throw new TypeError();
  const definition = value.definition;
  if (
    value.schema_version !== 1 ||
    typeof value.project_id !== 'string' ||
    value.project_id.length > 100 ||
    !Number.isSafeInteger(value.binding_version) ||
    Number(value.binding_version) < 0 ||
    typeof value.app_id !== 'string' ||
    !/^[a-z][a-z0-9-]{1,63}$/.test(value.app_id) ||
    value.app_id !== definition.app_id ||
    definition.ownership !== 'personal' ||
    typeof value.source_revision !== 'string' ||
    !/^[a-f0-9]{40}$/.test(value.source_revision) ||
    !digest(value.source_manifest_digest) ||
    !digest(value.definition_digest) ||
    !object(definition.display) ||
    typeof definition.display.name !== 'string' ||
    !definition.display.name.trim() ||
    definition.display.name.length > 200 ||
    !object(definition.source) ||
    typeof definition.source.repository !== 'string' ||
    definition.source.repository.length > 500 ||
    !isIndependentPermissionList(definition.requested_permissions)
  )
    throw new TypeError();
  // No handoff field is a credential, approval, or attestation of the source.
  return value as RegistrationDraft;
}
