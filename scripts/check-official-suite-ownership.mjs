import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8');
const owner = JSON.parse(read('apps/official-suite/ownership.json'));
const sourceContracts = JSON.parse(
  read('packages/contracts/app-contracts.json'),
);
const contracts = sourceContracts.apps;
assert.deepEqual(owner.ui_app_ids, sourceContracts.official_app_ids);
assert.equal(owner.schema_version, 1);
assert.equal(owner.stage, 'composition');
assert.equal(
  owner.current_writer,
  'legacy-miy',
  'Source composition cannot activate a second writer',
);
assert.equal(owner.migration_owner, 'legacy-platform-alembic');
assert.equal(owner.ui_metadata_source, 'packages/official-suite-web/src');
const implementations = [
  owner.ui_implementation_sources,
  owner.ui_partial_implementation_sources,
];
const implementationIds = implementations.flatMap((entries) =>
  Object.keys(entries),
);
assert.equal(
  new Set(implementationIds).size,
  implementationIds.length,
  'Duplicate full/partial UI source owner',
);
for (const [appId, source] of implementations.flatMap((entries) =>
  Object.entries(entries),
)) {
  assert.ok(
    owner.ui_app_ids.includes(appId),
    `Unknown implementation owner: ${appId}`,
  );
  assert.equal(source, `packages/official-suite-web/src/${appId}`);
  assert.ok(
    fs.existsSync(path.join(root, source, 'index.ts')),
    `Missing official UI implementation: ${appId}`,
  );
}
for (const key of [
  'ui_app_ids',
  'api_modules',
  'model_modules',
  'worker_modules',
]) {
  assert.ok(
    Array.isArray(owner[key]) && owner[key].length > 0,
    `Missing ${key}`,
  );
  assert.equal(new Set(owner[key]).size, owner[key].length, `Duplicate ${key}`);
}
for (const id of owner.ui_app_ids) {
  assert.ok(
    contracts.some((app) => app.app_id === id),
    `Unknown UI app: ${id}`,
  );
  assert.ok(
    fs.existsSync(path.join(root, 'apps/web/src/app-modules', id, 'index.ts')),
    `Missing public UI entry: ${id}`,
  );
  assert.ok(
    fs.existsSync(
      path.join(root, owner.ui_metadata_source, 'manifests', `${id}.ts`),
    ),
    `Missing official-owned UI metadata: ${id}`,
  );
}
assert.equal(
  owner.ui_business_composition_source,
  'packages/official-suite-web/src/modules.ts',
);
assert.equal(
  owner.portal_official_descriptor_source,
  'apps/web/src/app/shell/official-app-modules.ts',
);
const uiComposition = read(owner.ui_business_composition_source);
const portalDescriptors = read(owner.portal_official_descriptor_source);
assert.ok(uiComposition.includes('OFFICIAL_APP_IDS.map'));
assert.ok(portalDescriptors.includes('OFFICIAL_APP_MANIFESTS.map'));
assert.ok(
  !/official-suite-web\/[^'"]+\/module/.test(portalDescriptors),
  'The portal must not compile official business modules',
);
const registry = read('apps/api/src/miy_api/official_api_registry.py');
assert.deepEqual(
  Object.keys(owner.worker_implementation_sources),
  owner.worker_modules,
  'Official task implementations must have one source owner',
);
for (const [module, source] of Object.entries(
  owner.worker_implementation_sources,
)) {
  const leaf = module.split('.').at(-1);
  assert.equal(
    source,
    `apps/official-suite/worker/src/miy_official_worker/tasks/${leaf}.py`,
  );
  assert.ok(
    read(source).includes(`task_app("${module}")`),
    `Owned task registration has drifted: ${module}`,
  );
  assert.ok(
    read(`apps/worker/src/${module.replaceAll('.', '/')}.py`).includes(
      `import_module("miy_official_worker.tasks.${leaf}")`,
    ),
    `Missing same-module compatibility entry: ${module}`,
  );
}
const tableOwners = new Map();
for (const [key, sourceRoot] of [
  ['api_modules', 'apps/api/src'],
  ['model_modules', 'apps/api/src'],
  ['worker_modules', 'apps/worker/src'],
]) {
  for (const module of owner[key]) {
    assert.match(module, /^miy_(api|worker)\.[a-z_.]+$/);
    const source = read(`${sourceRoot}/${module.replaceAll('.', '/')}.py`);
    if (key === 'api_modules')
      assert.ok(
        registry.includes(module),
        `Router ownership has drifted: ${module}`,
      );
    if (key === 'model_modules') {
      for (const [, table] of source.matchAll(
        /__tablename__\s*=\s*['"]([^'"]+)['"]/g,
      )) {
        assert.ok(!tableOwners.has(table), `Duplicate table owner: ${table}`);
        tableOwners.set(table, module);
      }
    }
  }
}
assert.ok(tableOwners.size > 0, 'Ownership has no concrete model tables');
console.log(
  `Official suite composition: ${owner.ui_app_ids.length} UI apps, ${owner.api_modules.length} API modules, ${tableOwners.size} table declarations, ${owner.worker_modules.length} worker modules. Runtime writer remains ${owner.current_writer}.`,
);
