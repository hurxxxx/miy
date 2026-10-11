import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('the starter declares only the implemented identity capability', async () => {
  const definition = JSON.parse(
    await readFile(new URL('../app.manifest.json', import.meta.url), 'utf8'),
  );
  assert.equal(definition.schema_version, 1);
  assert.equal(definition.runtime_profile, 'web-api-v1');
  assert.deepEqual(definition.requested_permissions, ['identity:read']);
});
