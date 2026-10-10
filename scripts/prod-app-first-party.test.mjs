import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const script = readFileSync(new URL('./prod-app.sh', import.meta.url), 'utf8');
const functions = script.slice(script.indexOf('usage()'), script.indexOf('COMMAND='));
const dispatcher = script.slice(script.indexOf('COMMAND='));
const defaults = script.slice(script.indexOf('COMPOSE_PROJECT_NAME='), script.indexOf('usage()'));
const id = (value) => `sha256:${value.repeat(64)}`;
const containerId = (value) => value.repeat(64);
const shellQuote = (value) => `'${value.replaceAll("'", "'\\''")}'`;

function run(body) {
  return spawnSync('bash', ['-c', `set -euo pipefail\n${functions}\n${body}`], {
    encoding: 'utf8', env: { PATH: process.env.PATH },
  });
}

function runCli(body, args) {
  return spawnSync('bash', ['-c', `set -euo pipefail
ROOT_DIR=/synthetic/prod ENV_FILE=/synthetic/prod/.env
COMPOSE_FILE=/synthetic/prod/ops/compose/miy-prod.app.yml
${defaults}
${functions}
${body}
${dispatcher}`, 'test', ...args], {
    encoding: 'utf8', env: { PATH: process.env.PATH },
  });
}

// Exercise the real topology detector against only native read-only Docker
// metadata. Any service/image/database path becomes an observable mutation.
function nativeTopology({
  worker = 'legacy', orphan = '', multipleWorker = false,
  multipleOrphan = false, shortWorker = false, metadataFailure = false,
} = {}) {
  const workerId = worker === 'none' ? '' : shortWorker ? '1234' : containerId('1');
  const workerIds = multipleWorker ? [workerId, containerId('2')] : [workerId];
  const workerCommand = worker === 'legacy'
    ? '["celery","-A","miy_worker.celery_app:celery_app"]'
    : worker === 'first-party'
      ? '["celery","-A","miy_worker.first_party_platform:celery_app"]'
      : '["celery","-A","unowned_worker:app"]';
  const orphanIds = multipleOrphan ? [containerId('3'), containerId('4')] : [containerId('3')];
  return `
COMPOSE_PROJECT_NAME=miy-prod-app
compose() {
  if [[ "$*" != 'ps --all --quiet worker' || "\${TOPOLOGY:-legacy}" != legacy ]]; then
    printf 'MUTATION compose %s\\n' "$*"; return 97
  fi
  printf '%s\\n' ${workerIds.map(shellQuote).join(' ')}
}
docker() {
  if [[ "$1" == ps ]]; then
    [[ "$#" == 8 && "$2 $3 $4" == '--all --quiet --no-trunc' && "$5" == --filter
      && "$6" == 'label=com.docker.compose.project=miy-prod-app' && "$7" == --filter ]] || {
      printf 'MUTATION unowned-metadata\\n'; return 97;
    }
    ${metadataFailure ? 'return 7' : ''}
    case "$8" in
      label=com.docker.compose.service=official-api|label=com.docker.compose.service=official-worker|label=com.docker.compose.service=gateway)
        if [[ "$8" == ${shellQuote(`label=com.docker.compose.service=${orphan}`)} ]]; then
          printf '%s\\n' ${orphanIds.map(shellQuote).join(' ')}
        fi
        return 0;;
      *) printf 'MUTATION unowned-service\\n'; return 97;;
    esac
  fi
  if [[ "$1" == inspect && "$#" == 4 && "$2" == --format && "$3" == '{{json .Config.Cmd}}' && "$4" == ${shellQuote(workerId)} ]]; then
    printf '%s\\n' ${shellQuote(workerCommand)}; return 0
  fi
  printf 'MUTATION docker %s\\n' "$*"; return 97
}
`;
}

const rejectMutation = `
require_prod_checkout() { printf 'checkout\\n'; }
require_release_source() { printf 'release\\n'; }
acquire_operation_lock() { printf 'lock\\n'; }
validate_environment() { printf 'MUTATION validation-after-hold\\n'; return 97; }
prepare_rollback_runtime() { printf 'MUTATION rollback-bundle\\n'; return 97; }
load_release_contract() { printf 'MUTATION release-after-hold\\n'; return 97; }
prepare_candidate_image() { printf 'MUTATION build\\n'; return 97; }
promote_image() { printf 'MUTATION tag\\n'; return 97; }
run_migrations() { printf 'MUTATION database\\n'; return 97; }
start_forward_runtime() { printf 'MUTATION start\\n'; return 97; }
start_runtime() { printf 'MUTATION start\\n'; return 97; }
capture_prior_runtime() { printf 'MUTATION capture-after-hold\\n'; return 97; }
node() { printf 'MUTATION node %s\\n' "$*"; return 97; }
`;

for (const command of ['prepare', 'deploy', 'migrate', 'rollback', 'up']) {
  test(`${command} without first-party selection holds an existing split runtime before mutation`, () => {
    const args = [command];
    if (command === 'prepare' || command === 'deploy') args.push('--release-mr', '49');
    if (command === 'deploy') args.push('--image', id('a'));
    const result = runCli(`${nativeTopology({ worker: 'first-party', orphan: 'gateway' })}\n${rejectMutation}`, args);
    assert.equal(result.status, 1, result.stderr);
    assert.equal(result.stdout, 'checkout\nrelease\nlock\n');
    assert.match(result.stderr, /Requested topology differs/);
    assert.doesNotMatch(result.stdout + result.stderr, /MUTATION/);
  });
}

for (const operation of ['deploy', 'restore']) {
  test(`direct ${operation} also holds an existing split runtime before mutation`, () => {
    const result = run(`
TOPOLOGY=legacy CURRENT_IMAGE=miy-app:prod PREVIOUS_IMAGE=miy-app:prod-previous
ROLLBACK_IMAGE='${id('a')}' ROLLBACK_BUNDLE=/synthetic/rollback
${nativeTopology({ worker: 'first-party', orphan: 'official-api' })}
${rejectMutation}
if ${operation === 'deploy' ? `deploy '${id('b')}'` : 'restore_previous_runtime'}; then printf 'accepted\\n'; else printf 'held\\n'; fi
`);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, 'held\n');
    assert.match(result.stderr, /Requested topology differs/);
    assert.doesNotMatch(result.stdout + result.stderr, /MUTATION/);
  });
}

for (const command of ['up', 'migrate']) {
  test(`${command} cannot switch a legacy namespace through first-party selection`, () => {
    const result = runCli(`${nativeTopology()}\n${rejectMutation}`, [command, '--topology', 'first-party']);
    assert.equal(result.status, 1, result.stderr);
    assert.equal(result.stdout, 'checkout\nrelease\nlock\n');
    assert.match(result.stderr, /Requested topology differs/);
    assert.doesNotMatch(result.stdout + result.stderr, /MUTATION/);
  });
}

test('native topology metadata rejects split orphans, ambiguous IDs, unknown profiles and failed inspection', () => {
  const cases = [
    ...['official-api', 'official-worker', 'gateway'].flatMap((orphan) => [
      { worker: 'none', orphan }, { worker: 'legacy', orphan },
    ]),
    { multipleWorker: true }, { shortWorker: true }, { worker: 'unknown' },
    { worker: 'first-party', orphan: 'gateway', multipleOrphan: true },
    { metadataFailure: true },
  ];
  for (const fixture of cases) {
    const result = run(`
${nativeTopology(fixture)}
if current_runtime_topology; then printf 'accepted\\n'; else printf 'held\\n'; fi
`);
    assert.equal(result.status, 0, `${JSON.stringify(fixture)}: ${result.stderr}`);
    assert.equal(result.stdout, 'held\n', JSON.stringify(fixture));
    assert.doesNotMatch(result.stdout + result.stderr, /MUTATION/);
  }
});

test('known owned legacy, split and empty metadata retain their exact topology', () => {
  for (const worker of ['legacy', 'first-party', 'none']) {
    const result = run(`${nativeTopology({ worker })}\ncurrent_runtime_topology`);
    assert.equal(result.status, 0, `${worker}: ${result.stderr}`);
    assert.equal(result.stdout, `${worker}\n`);
  }
});

test('existing legacy topology still permits all five legacy operations', () => {
  const result = run(`
TOPOLOGY=legacy
${nativeTopology()}
for action in prepare deploy migrate rollback up; do require_runtime_topology "$action"; printf '%s\\n' "$action"; done
`);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, 'prepare\ndeploy\nmigrate\nrollback\nup\n');
});

test('explicit full split release and paired recovery retain legacy transition admission', () => {
  const result = run(`
TOPOLOGY=first-party RELEASE_SLICE=full ROLLBACK_IMAGE='${id('a')}'
${nativeTopology()}
for action in prepare deploy rollback; do require_runtime_topology "$action"; printf '%s\\n' "$action"; done
`);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, 'prepare\ndeploy\nrollback\n');
});

test('official-only release cannot admit a legacy transition as a full split release', () => {
  for (const worker of ['legacy', 'none']) {
    for (const action of ['prepare', 'deploy']) {
      const result = run(`
TOPOLOGY=first-party RELEASE_SLICE=official
${nativeTopology({ worker })}
if require_runtime_topology '${action}'; then printf 'accepted\\n'; else printf 'held\\n'; fi
`);
      assert.equal(result.status, 0, result.stderr);
      assert.equal(result.stdout, 'held\n', `${worker}/${action}`);
    }
  }
});

for (const refused of [false, true]) {
  test(`legacy-to-first-party ${refused ? 'holds at a refused drain' : 'drains before stopping the consumer'}`, () => {
    const result = run(`
TOPOLOGY=first-party
current_runtime_topology() { printf 'legacy\\n'; }
compose() { printf 'compose %s\\n' "$*"; }
drain_current_workers() { printf 'drain %s\\n' "$*"; ${refused ? 'return 1' : 'return 0'}; }
run_migrations() { printf 'migrate\\n'; }
check_files_content_cutover() { printf 'files-gate\\n'; }
start_runtime() { printf 'start-six\\n'; }
run_smoke() { printf 'smoke\\n'; }
if start_forward_runtime; then printf 'accepted\\n'; else printf 'held\\n'; fi
`);
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(result.stdout.trim().split('\n'), refused
      ? ['compose stop api beat', 'drain legacy', 'held']
      : ['compose stop api beat', 'drain legacy', 'compose stop worker', 'migrate', 'files-gate', 'start-six', 'smoke', 'accepted']);
  });
}

test('split inventory attests the exact six containers against their three images', () => {
  const result = run(`
TOPOLOGY=first-party COMPOSE_PROJECT_NAME=miy-prod-app
OFFICIAL_API_REPOSITORY=miy-official-api OFFICIAL_WORKER_REPOSITORY=miy-official-worker
image_id() { case "$1" in miy-official-api:prod) printf '${id('b')}\\n';; miy-official-worker:prod) printf '${id('d')}\\n';; *) return 1;; esac; }
compose() { case "$*" in
  'ps --all --quiet api') printf '${'1'.repeat(64)}\\n';; 'ps --all --quiet worker') printf '${'2'.repeat(64)}\\n';;
  'ps --all --quiet beat') printf '${'3'.repeat(64)}\\n';; 'ps --all --quiet official-api') printf '${'4'.repeat(64)}\\n';;
  'ps --all --quiet official-worker') printf '${'5'.repeat(64)}\\n';; 'ps --all --quiet gateway') printf '${'6'.repeat(64)}\\n';; *) return 1;; esac; }
prior_runtime_definition() { case "$1" in
  ${'1'.repeat(64)}) printf '${id('a')}|miy-prod-app|api|${'c'.repeat(64)}\\n';;
  ${'2'.repeat(64)}) printf '${id('a')}|miy-prod-app|worker|${'c'.repeat(64)}\\n';;
  ${'3'.repeat(64)}) printf '${id('a')}|miy-prod-app|beat|${'c'.repeat(64)}\\n';;
  ${'4'.repeat(64)}) printf '${id('b')}|miy-prod-app|official-api|${'c'.repeat(64)}\\n';;
  ${'5'.repeat(64)}) printf '${id('d')}|miy-prod-app|official-worker|${'c'.repeat(64)}\\n';;
  ${'6'.repeat(64)}) printf '${id('a')}|miy-prod-app|gateway|${'c'.repeat(64)}\\n';; esac; }
docker() { printf 'running|true|healthy\\n'; }
capture_prior_runtime '${id('a')}'
printf '%s\\n' "${'$'}{#UP_PRIOR_IDS[@]}" "${'$'}{#UP_PRIOR_DEFINITIONS[@]}"
`);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), '6\n6');
});

test('official paired update never recreates platform or Beat', () => {
  const result = run(`
TOPOLOGY=first-party RELEASE_SLICE=official ROLLBACK_TOPOLOGY=first-party
CURRENT_IMAGE=miy-app:prod PREVIOUS_IMAGE=miy-app:prod-previous
OFFICIAL_API_REPOSITORY=miy-official-api OFFICIAL_WORKER_REPOSITORY=miy-official-worker
OFFICIAL_API_IMAGE='${id('b')}' OFFICIAL_WORKER_IMAGE='${id('d')}'
current_runtime_topology() { printf 'first-party\\n'; }
require_official_slice() { printf 'ownership-compatibility-gate\\n'; }
slice_platform_identity() { return 0; }
promote_image() { printf 'promote %s\\n' "$2"; }
compose() { printf 'compose %s\\n' "$*"; }
run_smoke() { printf 'smoke\\n'; }
deploy miy-app:prod
`);
  assert.equal(result.status, 0, result.stderr);
  const lines = result.stdout.trim().split('\n');
  assert.deepEqual(lines.slice(0, 6), [
    'ownership-compatibility-gate', 'promote miy-official-api:prod', 'promote miy-official-worker:prod',
    'compose stop official-api official-worker',
    'compose up -d --no-deps --force-recreate --wait --wait-timeout 600 official-api official-worker', 'smoke',
  ]);
  assert.doesNotMatch(result.stdout, /compose stop api|compose stop beat|compose stop gateway|promote miy-app:prod|migrate/);
});

test('official slice refuses a replaced Core gateway while retaining healthy platform containers', () => {
  const result = run(`
CURRENT_IMAGE=miy-app:prod COMPOSE_PROJECT_NAME=miy-prod-app CHANGED=0
image_id() { printf '${id('a')}\\n'; }
compose() { case "$*" in
  'ps --all --quiet api') printf '${'1'.repeat(64)}\\n';; 'ps --all --quiet worker') printf '${'2'.repeat(64)}\\n';;
  'ps --all --quiet beat') printf '${'3'.repeat(64)}\\n';;
  'ps --all --quiet gateway') if [[ "$CHANGED" == 1 ]]; then printf '${'7'.repeat(64)}\\n'; else printf '${'6'.repeat(64)}\\n'; fi;;
  *) return 1;; esac; }
prior_runtime_definition() { local service; case "$1" in
  ${'1'.repeat(64)}) service=api;; ${'2'.repeat(64)}) service=worker;; ${'3'.repeat(64)}) service=beat;; *) service=gateway;; esac
  printf '${id('a')}|miy-prod-app|%s|${'c'.repeat(64)}\\n' "$service"; }
docker() { printf 'running|healthy\\n'; }
slice_platform_identity
CHANGED=1
if slice_platform_identity; then printf 'accepted\\n'; else printf 'held\\n'; fi
`);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), 'held');
});

for (const changed of [false, true]) {
  test(`official slice ${changed ? 'requires full release for a changed API route projection' : 'retains matching native gateway routes'}`, () => {
    const result = run(`
ROOT_DIR=/owned ENV_FILE=/owned/.env
node() { printf '/api/v1'; }
docker() { if [[ "$*" == *'${id('b')}'* ]]; then
  printf '%s\\n' '{"api_prefix":"/api/v1","official_patterns":["${changed ? '^/api/v1/new$' : '^/api/v1/owned$'}"]}';
  else printf '%s\\n' '{"api_prefix":"/api/v1","official_patterns":["^/api/v1/owned$"]}'; fi; }
if require_official_gateway_compatibility '${id('a')}' '${id('b')}'; then printf 'accepted\\n'; else printf 'held\\n'; fi
`);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), changed ? 'held' : 'accepted');
  });
}

for (const occupied of [false, true]) {
  test(`first-party internal listener preflight ${occupied ? 'holds an unowned listener' : 'accepts free reserved ports'}`, () => {
    const result = run(`
ss() { ${occupied ? "printf 'unowned-listener\\n';" : 'return 0;'} }
compose() { return 0; }
if require_first_party_ports_available; then printf 'accepted\\n'; else printf 'held\\n'; fi
`);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), occupied ? 'held' : 'accepted');
  });
}

test('full transition restores first-party selection after attesting a legacy prior runtime', () => {
  const result = run(`
TOPOLOGY=first-party RELEASE_SLICE=full ROLLBACK_TOPOLOGY=legacy
CURRENT_IMAGE=miy-app:prod PREVIOUS_IMAGE=miy-app:prod-previous ROOT_DIR=/source
OFFICIAL_API_REPOSITORY=miy-official-api OFFICIAL_WORKER_REPOSITORY=miy-official-worker
OFFICIAL_API_IMAGE='${id('b')}' OFFICIAL_WORKER_IMAGE='${id('d')}'
current_runtime_topology() { printf 'legacy\\n'; }
image_id() { printf '${id('a')}\\n'; }
capture_prior_runtime() { printf 'attest %s\\n' "$TOPOLOGY"; }
promote_image() { printf 'promote %s %s\\n' "${'$'}{2:-$CURRENT_IMAGE}" "$TOPOLOGY"; }
start_forward_runtime() { printf 'forward %s\\n' "$TOPOLOGY"; }
node() { return 0; }
deploy '${id('e')}'
`);
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(result.stdout.trim().split('\n').slice(0, 5), [
    'attest legacy', 'promote miy-official-api:prod first-party', 'promote miy-official-worker:prod first-party',
    'promote miy-app:prod first-party', 'forward first-party',
  ]);
});

for (const activation of ['inactive', 'first-party-runtime']) {
  test(`official service image ${activation === 'inactive' ? 'rejects inactive artifact' : 'uses the isolated runtime content probe'}`, () => {
    const result = run(`
image_revision() { printf 'reviewed-revision\\n'; }
image_label() { case "$2" in *activation) printf '${activation}\\n';; *source-dirty) printf 'false\\n';; esac; }
docker() { [[ "$*" == 'run --rm --network none --entrypoint /bin/sh '* ]] || return 1; printf 'offline-probe\\n'; }
if verify_release_image '${id('b')}' reviewed-revision official-api; then printf 'accepted\\n'; else printf 'held\\n'; fi
`);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), activation === 'inactive' ? 'held' : 'offline-probe\naccepted');
  });
}
