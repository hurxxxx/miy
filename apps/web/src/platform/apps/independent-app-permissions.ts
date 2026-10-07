import type { ApiSchema } from '@miy/contracts/api';

export type IndependentAppPermission = NonNullable<
  ApiSchema<'AppDefinition'>['requested_permissions']
>[number];

/** Adding a server capability must also add a distinct, explicit consent label. */
export const independentPermissionCopy = {
  'identity:read': 'profileRead',
  'data:read': 'dataRead',
  'data:write': 'dataWrite',
  'files:read-selected': 'selectedFileRead',
} as const satisfies Record<IndependentAppPermission, string>;

export const independentAppPermissions = Object.keys(
  independentPermissionCopy,
) as IndependentAppPermission[];

export function isIndependentPermissionList(
  value: unknown,
): value is IndependentAppPermission[] {
  return (
    Array.isArray(value) &&
    value.length <= independentAppPermissions.length &&
    new Set(value).size === value.length &&
    value.every((item) => independentAppPermissions.includes(item))
  );
}
