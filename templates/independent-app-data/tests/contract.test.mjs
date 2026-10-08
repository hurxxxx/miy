import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('private notes explicitly requests the implemented data profile and permissions', async () => {
  const definition = JSON.parse(
    await readFile(new URL('../app.manifest.json', import.meta.url), 'utf8'),
  );
  assert.equal(definition.schema_version, 1);
  assert.equal(definition.runtime_profile, 'web-api-postgres-v1');
  assert.deepEqual(definition.requested_permissions, [
    'identity:read',
    'data:read',
    'data:write',
  ]);
});
