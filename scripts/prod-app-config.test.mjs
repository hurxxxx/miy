import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { assertProductionAppEnv, parseEnvText } from './prod-app-config.mjs';
import { cleanup, diskHeadroom, retirementPlan } from './docker-storage.mjs';

const oldImage = (id, tags, extra = {}) => ({
  Id: id,
  RepoTags: tags,
  Created: '2020-01-01T00:00:00Z',
  Config: { Labels: { 'org.opencontainers.image.title': 'miy' } },
  ...extra,
});
const appTag = (id) => `miy-app:${id.repeat(12)}`;

for (const missing of [false, true]) {
  test(`candidate executable contract ${missing ? 'refuses missing' : 'checks present'} owned timeout before publication`, async () => {
    const script = await readFile(
      new URL('./prod-app.sh', import.meta.url),
      'utf8',
    );
    const start = script.indexOf('verify_files_gate_executable()');
    const functions = script.slice(
      start >= 0 ? start : script.indexOf('verify_candidate_image()'),
      script.indexOf('prepare_candidate_image()'),
    );
    const result = spawnSync(
      'bash',
      [
        '-c',
        `
set -euo pipefail
RELEASE_REVISION=revision RELEASE_CONTRACT=contract RELEASE_SOURCE_REVISION=source
RELEASE_TREE=tree RELEASE_PLATFORM=platform RELEASE_BENTO_URL_SHA256=urlhash RELEASE_MR=80
${functions}
image_id() { printf 'sha256:${'a'.repeat(64)}\n'; }
verify_release_image() { printf 'base-verifier\n'; }
image_label() {
  case "$2" in
    *release.contract) printf 'contract\n';; *source-revision) printf 'source\n';;
    *release.tree) printf 'tree\n';; *release.platform) printf 'platform\n';;
    *bento-url-sha256) printf 'urlhash\n';; *merge-request) printf '80\n';;
    *release.pipeline) printf '141\n';; *) return 9;;
  esac
}
docker() {
  [[ "$*" == 'run --rm --network none --entrypoint /bin/sh sha256:${'a'.repeat(64)} -ec test -x /usr/bin/timeout' ]] || return 9
  printf 'timeout-executable-probe\n'
  ${missing ? 'return 4' : 'return 0'}
}
if verify_candidate_image synthetic:candidate; then printf 'candidate-ready\n'; else printf 'candidate-blocked\n'; fi
`,
      ],
      { encoding: 'utf8', env: { PATH: process.env.PATH } },
    );
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(result.stdout.trim().split('\n'), [
      'base-verifier',
      'timeout-executable-probe',
      missing ? 'candidate-blocked' : 'candidate-ready',
    ]);
  });
}

async function forwardFixture(stage = '', mode = 'forward') {
  const script = await readFile(
    new URL('./prod-app.sh', import.meta.url),
    'utf8',
  );
  const functions = script.slice(
    script.indexOf('run_migrations()'),
    script.indexOf('start_runtime()'),
  );
  const upStart = script.indexOf('  up)\n');
  const upBody = script.slice(
    upStart + '  up)\n'.length,
    script.indexOf('    ;;', upStart),
  );
  const result = spawnSync(
    'bash',
    [
      '-c',
      `
set -euo pipefail
COMPOSE_PROJECT_NAME=miy-prod-app
CURRENT_IMAGE=miy-app:prod
PREVIOUS_IMAGE=miy-app:prod-previous
CURRENT_ID=sha256:${'a'.repeat(64)}
STAGE=${stage}
START_COUNT=0
PRIOR_CHANGED=0
HEALTH_READY=0
RECOVERY_STARTED=0
DEFINITION_HASH=${'c'.repeat(64)}
${functions}
compose() {
  case "$*" in
    'ps --all --quiet '*)
      [[ "$STAGE" != no-runtime && "$STAGE" != first-start ]] || return 0
      if [[ "$STAGE" == partial-prior && "$*" == *worker ]]; then return 0; fi
      if [[ "$STAGE" == replaced-prior && "$PRIOR_CHANGED" == 1 && "$*" == *api ]]; then printf '%064d\n' 4; return 0; fi
      case "$*" in *api) printf '%064d\n' 1;; *worker) printf '%064d\n' 2;; *beat) printf '%064d\n' 3;; esac
      return 0 ;;
    'config --hash '*) return 9 ;;
  esac
  printf '%s\n' "$*"
  case "$*" in
    'start '*) return 9 ;;
    'stop '*) [[ "$STAGE" != stop ]] || return 4 ;;
    'run --rm migrate') [[ "$STAGE" != migration ]] || return 4 ;;
    *cutover_gate*)
      [[ "$STAGE" != prior-*-gate ]] || return 4
      if [[ "$STAGE" == changed-image ]]; then CURRENT_ID=sha256:${'b'.repeat(64)}; return 4; fi
      if [[ "$STAGE" == replaced-prior || "$STAGE" == changed-definition ]]; then PRIOR_CHANGED=1; return 4; fi
      if [[ "$STAGE" == warmup || "$STAGE" == warm-timeout || "$STAGE" == stopped-after-start ]]; then return 4; fi
      [[ "$STAGE" != gate && "$STAGE" != timeout && "$STAGE" != no-runtime && "$STAGE" != retagged-runtime ]] || return 124 ;;
  esac
}
image_id() { [[ "$1" == "$CURRENT_IMAGE" ]]; printf '%s\n' "$CURRENT_ID"; }
docker() {
  if [[ "$1" == start ]]; then
    [[ "$*" == 'start ${'0'.repeat(63)}1 ${'0'.repeat(63)}2 ${'0'.repeat(63)}3' ]] || return 9
    RECOVERY_STARTED=1
    printf 'restored-existing\n'
    return 0
  fi
  if [[ "$*" == 'image inspect miy-app:prod' ]]; then printf 'inspect-current\n'; return 0; fi
  [[ "$1" == inspect ]] || return 9
  local service=api image="$CURRENT_ID" definition="$DEFINITION_HASH"
  case "\${*: -1}" in *2) service=worker;; *3) service=beat;; esac
  [[ "$STAGE" != retagged-runtime && !( "$STAGE" == mixed-prior && "$service" == worker ) ]] || image=sha256:${'b'.repeat(64)}
  [[ !( "$STAGE" == changed-definition && "$PRIOR_CHANGED" == 1 ) ]] || definition=${'d'.repeat(64)}
  [[ "$STAGE" != invalid-config-label ]] || definition=invalid
  local prior_status=running prior_running=true prior_health=healthy
  case "$STAGE" in
    prior-created-no-health*) prior_status=created; prior_running=false; prior_health='' ;;
    prior-exited-no-health*) prior_status=exited; prior_running=false; prior_health='' ;;
    prior-exited*) prior_status=exited; prior_running=false ;;
    prior-created*) prior_status=created; prior_running=false ;;
    prior-paused*) prior_status=paused ;;
    prior-restarting*) prior_status=restarting ;;
    prior-dead*) prior_status=dead; prior_running=false ;;
    prior-unhealthy*) prior_health=unhealthy ;;
    prior-starting*) prior_health=starting ;;
    prior-invalid-status) prior_status=unknown ;;
    prior-invalid-running) prior_running=invalid ;;
    prior-invalid-health) prior_health=invalid ;;
    prior-empty-status) prior_status='' ;;
  esac
  if [[ "$3" == '{{.State.Running}}' ]]; then
    [[ "$prior_status" != exited ]] && printf 'true\n' || printf 'false\n'
  elif [[ "$3" == '{{if .State.Health}}{{.State.Health.Status}}{{end}}' ]]; then printf '%s\n' "$prior_health";
  elif [[ "$3" == '{{.State.Status}}|{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' ]]; then
    [[ "$STAGE" != prior-inspect-error ]] || return 4
    printf '%s|%s|%s\n' "$prior_status" "$prior_running" "$prior_health"
  elif [[ "$3" == *'.State.Status'* ]]; then
    if [[ "$STAGE" == stopped-after-start ]]; then printf 'exited|healthy\n';
    elif [[ ( "$STAGE" == warmup || "$STAGE" == warm-timeout ) && "$HEALTH_READY" == 0 ]]; then printf 'running|starting\n';
    else printf 'running|healthy\n'; fi
  else printf '%s|miy-prod-app|%s|%s\n' "$image" "$service" "$definition"; fi
}
verify_files_gate_executable() {
  [[ "$1" == "sha256:${'a'.repeat(64)}" ]] || return 9
  printf 'timeout-executable-probe\n'
  [[ "$STAGE" != executable ]] || return 4
}
require_prod_checkout() { :; }
require_release_source() { :; }
acquire_operation_lock() { :; }
validate_environment() { :; }
require_terminal_broker_port_available() { :; }
start_runtime() {
  START_COUNT=$((START_COUNT+1))
  printf 'start:%s:%s\n' "$START_COUNT" "$CURRENT_ID"
  [[ "$STAGE:$START_COUNT" != start:1 && "$STAGE" != restore-start ]] || return 4
}
sleep() { printf 'health-wait\n'; if [[ "$STAGE" == warm-timeout ]]; then SECONDS=700; else HEALTH_READY=1; fi; }
run_smoke() {
  if [[ "$STAGE" == stop || "$STAGE" == migration || "$STAGE" == gate || "$STAGE" == timeout || "$STAGE" == warmup ]]; then [[ "$RECOVERY_STARTED" == 1 ]] || return 9; fi
  printf 'smoke\n'; [[ "$STAGE" != restore-smoke && !( "$STAGE" == warmup && "$HEALTH_READY" == 0 ) ]] || return 4; }
${mode === 'up' ? upBody : 'if start_forward_runtime; then printf "forward-ok\\n"; else printf "forward-failed\\n"; fi'}
`,
    ],
    { encoding: 'utf8', env: { PATH: process.env.PATH } },
  );
  return result;
}

test('forward runtime stops all old writers before migration, owned deadline gate, startup and smoke', async () => {
  const result = await forwardFixture();
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(result.stdout.trim().split('\n'), [
    'stop api worker beat',
    'run --rm migrate',
    'run --rm --no-deps --entrypoint /usr/bin/timeout migrate --signal=TERM --kill-after=5 130 apps/api/.venv/bin/python -m miy_api.domains.files.cutover_gate',
    `start:1:sha256:${'a'.repeat(64)}`,
    'smoke',
    'forward-ok',
  ]);
});

for (const stage of ['stop', 'migration', 'gate', 'timeout']) {
  test(`forward ${stage} failure never starts the candidate or claims success`, async () => {
    const result = await forwardFixture(stage);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /forward-failed/);
    assert.doesNotMatch(result.stdout, /start:|smoke|forward-ok/);
    if (stage === 'stop') assert.doesNotMatch(result.stdout, /run --rm/);
    if (stage === 'migration')
      assert.doesNotMatch(result.stdout, /cutover_gate/);
  });
}

test('up runs the same forward gate and starts the captured current image', async () => {
  const result = await forwardFixture('', 'up');
  assert.equal(result.status, 0, result.stderr);
  // Docker inspect is intentionally redirected by the production entrypoint.
  assert.match(result.stdout, /^timeout-executable-probe\nstop /);
  assert.match(result.stdout, /cutover_gate/);
  assert.match(
    result.stdout,
    new RegExp(`start:1:sha256:${'a'.repeat(64)}\\nsmoke`),
  );
});

test('up missing timeout executable refuses before stopping any current writer', async () => {
  const result = await forwardFixture('executable', 'up');
  assert.equal(result.status, 4);
  assert.equal(result.stdout, 'timeout-executable-probe\n');
  assert.doesNotMatch(result.stderr, /restoring|restoration/);
});

for (const stage of ['stop', 'migration', 'gate', 'timeout']) {
  test(`up ${stage} failure restores only the exact pre-up image and still fails`, async () => {
    const result = await forwardFixture(stage, 'up');
    assert.equal(result.status, 1);
    assert.match(result.stderr, /restoring the pre-up image/);
    assert.doesNotMatch(result.stderr, /restoration failed/);
    assert.match(result.stdout, /smoke\n/);
    assert.doesNotMatch(result.stdout, /start:[12]:/);
    assert.doesNotMatch(result.stdout, /prod-previous|tag|forward-ok/);
    assert.equal(
      (result.stdout.match(/cutover_gate/g) || []).length,
      ['gate', 'timeout'].includes(stage) ? 1 : 0,
    );
  });
}

test('up refuses restoration if its current image identity changed and never uses unrelated prod-previous', async () => {
  const result = await forwardFixture('changed-image', 'up');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /No unchanged attested pre-up runtime/);
  assert.match(result.stderr, /operator recovery is required/);
  assert.doesNotMatch(result.stdout, /start:|smoke|prod-previous|tag/);
});

test('up recovery smoke failure remains an explicit failure', async () => {
  const result = await forwardFixture('restore-smoke', 'up');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /operator recovery is required/);
  assert.doesNotMatch(result.stdout, /forward-ok/);
});

test('pipeline retries for the same release do not change the image contract', async () => {
  const script = await readFile(
    new URL('./prod-app.sh', import.meta.url),
    'utf8',
  );
  const load = script.slice(
    script.indexOf('load_release_contract()'),
    script.indexOf('candidate_matches_contract()'),
  );
  const result = spawnSync(
    'bash',
    [
      '-c',
      `
set -euo pipefail
ROOT_DIR=/synthetic ENV_FILE=/synthetic/env PIPELINE=141
SOURCE=${'a'.repeat(40)} MERGE=${'b'.repeat(40)} TREE=${'c'.repeat(40)}
${load}
node() {
  if [[ "$1" == *prod-app-release.mjs ]]; then
    printf '%s\\n%s\\n%s\\n' "$SOURCE" "$MERGE" "$PIPELINE"
  else
    printf 'https://bento.example.com/\\n'
  fi
}
git() { printf '%s\\n' "$TREE"; }
docker() { printf 'linux/amd64\\n'; }
load_release_contract 49
first="$RELEASE_CONTRACT"
PIPELINE=142
load_release_contract 49
[[ "$first" == "$RELEASE_CONTRACT" && "$RELEASE_PIPELINE" == 142 ]]
`,
    ],
    { encoding: 'utf8', env: { PATH: process.env.PATH } },
  );
  assert.equal(result.status, 0, result.stderr);
});

test('candidate preparation reuses a matching verified image without rebuilding', async () => {
  const script = await readFile(
    new URL('./prod-app.sh', import.meta.url),
    'utf8',
  );
  const prepare = script.slice(
    script.indexOf('prepare_candidate_image()'),
    script.indexOf('require_deploy_image()'),
  );
  const result = spawnSync(
    'bash',
    [
      '-c',
      `
set -euo pipefail
ROOT_DIR=/synthetic ENV_FILE=/synthetic/env IMAGE_REPOSITORY=synthetic CANDIDATE_IMAGE=synthetic:candidate
RELEASE_PLATFORM=linux/amd64 RELEASE_REVISION=${'a'.repeat(40)}
RELEASE_CONTRACT=${'b'.repeat(64)} RELEASE_SOURCE_REVISION=${'c'.repeat(40)}
RELEASE_TREE=${'d'.repeat(40)} RELEASE_BENTO_URL_SHA256=${'e'.repeat(64)}
RELEASE_MR=49 RELEASE_PIPELINE=141
${prepare}
docker() { [[ "$1 $2" == 'image inspect' ]]; }
candidate_matches_contract() { return 0; }
verify_candidate_image() { return 0; }
image_id() { printf 'sha256:%064d\n' 0; }
node() { printf 'unexpected node call\n' >&2; return 9; }
git() { printf 'unexpected git call\n' >&2; return 9; }
prepare_candidate_image
`,
    ],
    { encoding: 'utf8', env: { PATH: process.env.PATH } },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, `sha256:${'0'.repeat(64)}\n`);
});

test('candidate preparation builds once from the committed archive when the contract changed', async () => {
  const script = await readFile(
    new URL('./prod-app.sh', import.meta.url),
    'utf8',
  );
  const prepare = script.slice(
    script.indexOf('prepare_candidate_image()'),
    script.indexOf('require_deploy_image()'),
  );
  const result = spawnSync(
    'bash',
    [
      '-c',
      `
set -euo pipefail
ROOT_DIR=/synthetic ENV_FILE=/synthetic/env IMAGE_REPOSITORY=synthetic CANDIDATE_IMAGE=synthetic:candidate
RELEASE_PLATFORM=linux/amd64 RELEASE_REVISION=${'a'.repeat(40)}
RELEASE_CONTRACT=${'b'.repeat(64)} RELEASE_SOURCE_REVISION=${'c'.repeat(40)}
RELEASE_TREE=${'d'.repeat(40)} RELEASE_BENTO_URL_SHA256=${'e'.repeat(64)}
RELEASE_MR=49 RELEASE_PIPELINE=141
${prepare}
docker() {
  if [[ "$1 $2" == 'image inspect' ]]; then
    [[ "$3" == "$CANDIDATE_IMAGE" ]]
    return
  fi
  if [[ "$1" == build ]]; then cat >/dev/null; printf 'built\\n' >&2; return 0; fi
  if [[ "$1" == tag ]]; then return 0; fi
  return 9
}
candidate_matches_contract() { return 1; }
verify_candidate_image() { return 0; }
image_id() { printf 'sha256:%064d\\n' 1; }
node() {
  if [[ "$1" == *docker-storage.mjs ]]; then return 0; fi
  printf 'https://bento.example.com/\\n'
}
git() { printf 'committed-archive'; }
prepare_candidate_image
`,
    ],
    { encoding: 'utf8', env: { PATH: process.env.PATH } },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, `sha256:${'0'.repeat(63)}1\n`);
  assert.equal(result.stderr.match(/built/g)?.length, 1);
});

test('a matching candidate that fails verification is not rebuilt', async () => {
  const script = await readFile(
    new URL('./prod-app.sh', import.meta.url),
    'utf8',
  );
  const prepare = script.slice(
    script.indexOf('prepare_candidate_image()'),
    script.indexOf('require_deploy_image()'),
  );
  const result = spawnSync(
    'bash',
    [
      '-c',
      `
set -euo pipefail
CANDIDATE_IMAGE=synthetic:candidate
${prepare}
docker() { [[ "$1 $2" == 'image inspect' ]]; }
candidate_matches_contract() { return 0; }
verify_candidate_image() { return 7; }
node() { return 9; }
git() { return 9; }
prepare_candidate_image
`,
    ],
    { encoding: 'utf8', env: { PATH: process.env.PATH } },
  );
  assert.equal(result.status, 1, result.stderr);
});

test('promoting the already-current image preserves the rollback tag', async () => {
  const script = await readFile(
    new URL('./prod-app.sh', import.meta.url),
    'utf8',
  );
  const promote = script.slice(
    script.indexOf('promote_image()'),
    script.indexOf('run_migrations()'),
  );
  const result = spawnSync(
    'bash',
    [
      '-c',
      `
set -euo pipefail
CURRENT_IMAGE=synthetic:prod PREVIOUS_IMAGE=synthetic:previous
${promote}
image_id() { printf 'sha256:%064d\\n' 2; }
docker() {
  if [[ "$1 $2" == 'image inspect' ]]; then return 0; fi
  printf 'unexpected tag mutation\\n' >&2
  return 9
}
promote_image sha256:${'0'.repeat(63)}2
`,
    ],
    { encoding: 'utf8', env: { PATH: process.env.PATH } },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr, '');
});
const storageImages = () => [
  oldImage('current', ['miy-app:prod', appTag('a')]),
  oldImage('previous', ['miy-app:prod-previous', appTag('b')]),
  oldImage('ci', [
    'miy-validation:node22-python312',
    'miy-validation:redis64-impact-release',
  ]),
  oldImage('retired', [appTag('c')]),
];

test('storage requires both absolute and proportional disk headroom', () => {
  const stats = (available, total) => ({
    bavail: available,
    blocks: total,
    bsize: 1024 ** 3,
  });
  assert.equal(diskHeadroom(stats(20, 100)).ok, true);
  assert.equal(diskHeadroom(stats(15, 100)).ok, true);
  assert.equal(diskHeadroom(stats(14, 50)).ok, false);
  assert.equal(diskHeadroom(stats(20, 200)).ok, false);
  assert.equal(diskHeadroom(stats(20, 0)).ok, false);
  assert.equal(diskHeadroom(stats(NaN, 100)).ok, false);
});

test('retention preserves current, rollback, CI, container refs, recent and unknown images', () => {
  const images = [
    ...storageImages(),
    oldImage('candidate', ['miy-app:candidate']),
    oldImage('running', [appTag('d')]),
    oldImage('stopped', [appTag('e')]),
    oldImage('manual', [appTag('f'), 'miy-app:keep-for-investigation']),
    oldImage('foreign', ['another-project:old']),
    oldImage('unlabeled', [appTag('1')], { Config: {} }),
    oldImage('recent', [appTag('2')], { Created: new Date().toISOString() }),
    oldImage('undated', [appTag('3')], { Created: 'unknown' }),
    oldImage('dangling', []),
    oldImage('old-ci', ['miy-validation:deps-aaaaaaaaaaaa']),
  ];
  assert.deepEqual(
    retirementPlan(images, [{ Image: 'running' }, { Image: 'stopped' }]).map(
      (i) => i.id,
    ),
    ['retired', 'old-ci'],
  );
  assert.deepEqual(retirementPlan([images[3]], []), []);
});

test('cleanup is read-only by default and uses only scoped non-force image removal', () => {
  const state = { images: storageImages(), containers: [] };
  const calls = [];
  const options = { inspect: () => state, invoke: (args) => calls.push(args) };
  cleanup(options);
  assert.deepEqual(calls, []);
  cleanup({ ...options, apply: true });
  assert.deepEqual(calls, [
    ['image', 'rm', '--no-prune', appTag('c')],
    [
      'image',
      'prune',
      '--force',
      '--filter',
      'label=io.miy.build-cache=true',
      '--filter',
      'until=48h',
    ],
    [
      'image',
      'prune',
      '--force',
      '--filter',
      'label=org.opencontainers.image.title=miy',
      '--filter',
      'until=48h',
    ],
  ]);
});

test('replaced validation images are retired by identity without touching unknown or referenced images', () => {
  const validation = (id, extra = {}) =>
    oldImage(id, [], {
      Config: {
        Labels: { 'io.miy.validation.contract': 'a'.repeat(64) },
      },
      ...extra,
    });
  const state = {
    images: [
      ...storageImages().slice(0, 3),
      validation('obsolete-ci'),
      validation('null-tags-ci', { RepoTags: null }),
      validation('missing-tags-ci', { RepoTags: undefined }),
      validation('running-ci'),
      validation('stopped-ci'),
      validation('recent-ci', { Created: new Date().toISOString() }),
      validation('manual-ci', { RepoTags: ['manual:preserve'] }),
      validation('invalid-label', {
        Config: { Labels: { 'io.miy.validation.contract': '' } },
      }),
      oldImage('unknown-dangling', [], { Config: {} }),
    ],
    containers: [{ Image: 'running-ci' }, { Image: 'stopped-ci' }],
  };
  assert.deepEqual(
    retirementPlan(state.images, state.containers).map((i) => i.id),
    ['obsolete-ci', 'null-tags-ci', 'missing-tags-ci'],
  );
  assert.deepEqual(retirementPlan([validation('obsolete-ci')], []), []);
  const calls = [];
  cleanup({
    apply: true,
    inspect: () => state,
    invoke: (args) => calls.push(args),
  });
  assert.deepEqual(
    calls.filter((args) => args[1] === 'rm'),
    [
      ['image', 'rm', '--no-prune', 'obsolete-ci'],
      ['image', 'rm', '--no-prune', 'null-tags-ci'],
      ['image', 'rm', '--no-prune', 'missing-tags-ci'],
    ],
  );
});

test('cleanup stops if a candidate gains a reference or tag after inspection', () => {
  for (const change of ['container', 'tag']) {
    let count = 0;
    assert.throws(
      () =>
        cleanup({
          apply: true,
          inspect: () => {
            const state = { images: storageImages(), containers: [] };
            if (count++ > 0) {
              if (change === 'container')
                state.containers.push({ Image: 'retired' });
              else state.images[3].RepoTags.push('miy-app:prod-previous');
            }
            return state;
          },
          invoke: () =>
            assert.fail('changed references must prevent any deletion'),
        }),
      /references changed/,
    );
  }
});

test('production dependency layers exclude revision churn, uv cache and local test artifacts', async () => {
  const dockerfile = await readFile(
    new URL('../ops/app/Dockerfile', import.meta.url),
    'utf8',
  );
  const ignore = await readFile(
    new URL('../.dockerignore', import.meta.url),
    'utf8',
  );
  const [buildStages, runtime] = dockerfile.split('AS runtime');
  assert.match(runtime, /COPY --chown=miy:miy config config/);
  assert.ok(!ignore.split('\n').includes('config'));
  assert.equal(
    (buildStages.match(/uv sync --no-cache --frozen/g) ?? []).length,
    2,
  );
  const dependencies = buildStages.slice(
    0,
    buildStages.indexOf('FROM python-build AS python-packages'),
  );
  assert.doesNotMatch(dependencies, /COPY apps\/(?:api|worker)\/src/);
  assert.match(
    runtime,
    /COPY --from=python-build \/opt\/miy\/apps\/api\/\.venv/,
  );
  assert.match(
    runtime,
    /--mount=type=bind,from=python-packages,source=\/wheels/,
  );
  assert.match(
    runtime,
    /uv pip install --no-cache --no-deps --python apps\/api\/\.venv\/bin\/python/,
  );
  assert.ok(
    buildStages.indexOf('RUN pnpm --filter') < buildStages.indexOf('COPY . .'),
  );
  assert.ok(
    buildStages.indexOf('ARG MIY_BENTO_SERVER_URL') >
      buildStages.indexOf('RUN pnpm install'),
  );
  assert.equal(
    (buildStages.match(/io.miy.build-cache="true"/g) ?? []).length,
    2,
  );
  assert.ok(
    runtime.indexOf('ARG MIY_BUILD_REVISION') > runtime.lastIndexOf('COPY '),
  );
  assert.ok(
    runtime.indexOf('ARG MIY_BUILD_REVISION') > runtime.lastIndexOf('RUN '),
  );
  assert.match(
    runtime,
    /org.opencontainers.image.revision="\$\{MIY_BUILD_REVISION\}"/,
  );
  assert.match(runtime, /io.miy.release.contract=/);
  assert.match(runtime, /io.miy.release.pipeline=/);
  assert.doesNotMatch(runtime, /io.miy.build-cache/);
  for (const entry of [
    '.runtime',
    '.dev',
    '**/test-results',
    '**/playwright-report',
    '**/blob-report',
    '**/celerybeat-schedule*',
    '**/celerybeat-heartbeat',
  ]) {
    assert.ok(
      ignore.split('\n').includes(entry),
      `missing Docker context exclusion: ${entry}`,
    );
  }
  const release = await readFile(
    new URL('./prod-app.sh', import.meta.url),
    'utf8',
  );
  const prepare = release.slice(
    release.indexOf('prepare_candidate_image()'),
    release.indexOf('require_deploy_image()'),
  );
  assert.ok(
    prepare.indexOf('docker-storage.mjs" check') <
      prepare.indexOf('docker build'),
  );
  assert.match(prepare, /git -C "\$ROOT_DIR" archive --format=tar HEAD/);
  assert.match(prepare, /--tag "\$build_image"/);
  assert.match(prepare, /candidate_image="\$CANDIDATE_IMAGE"/);
  assert.match(prepare, /docker tag "\$build_image" "\$candidate_image"/);
  const deploy = release.slice(
    release.indexOf('deploy()'),
    release.indexOf('COMMAND='),
  );
  assert.doesNotMatch(deploy, /docker build|build_release_image/);
  assert.doesNotMatch(
    deploy.slice(0, deploy.indexOf('passed public smoke')),
    /cleanup --apply/,
  );
  assert.match(deploy, /passed public smoke[\s\S]+cleanup --apply/);
});

function validEnv(overrides = {}) {
  return new Map(
    Object.entries({
      OPENROUTER_API_KEY: 'sk-or-v1-production-test-key',
      MIY_API_ALLOW_DEV_ADMIN_LOGIN: '0',
      MIY_API_DEV_PORT: '8001',
      MIY_API_ENVIRONMENT: 'production',
      MIY_API_OBJECT_STORAGE_REQUIRED: 'true',
      MIY_API_SEED_DEV_LOGIN_ACCOUNT: 'false',
      MIY_CONTENT_GRANT_SIGNING_KEY: 'production-test-content-signing-key',
      MIY_APP_BIND_HOST: '127.0.0.1',
      MIY_APP_FORWARDED_ALLOW_IPS: '127.0.0.1',
      MIY_APP_PORT: '8000',
      MIY_APP_PUBLIC_URL: 'https://prod.example.com',
      MIY_BENTO_BIND_HOST: '127.0.0.1',
      MIY_BENTO_PORT: '18084',
      MIY_BENTO_SERVER_URL: 'https://bento.example.com',
      MIY_DRAWIO_PORT: '18083',
      MIY_ENV_PROFILE: 'prod',
      MIY_HERMES_API_KEY: 'production-hermes-runtime-secret-00000001',
      MIY_HERMES_ENABLED: 'true',
      MIY_HERMES_MANAGEMENT_BASE_URL: 'http://127.0.0.1:9119',
      MIY_HERMES_MANAGEMENT_PORT: '9119',
      MIY_HERMES_MANAGEMENT_TOKEN: 'production-hermes-management-secret-0001',
      MIY_HERMES_MCP_SERVER_URL:
        'http://127.0.0.1:8000/api/v1/internal/hermes/mcp',
      MIY_HERMES_MCP_SHARED_SECRET: 'production-hermes-mcp-secret-0000000001',
      MIY_HERMES_PROFILE_CLONE_SOURCE: 'default',
      MIY_HERMES_RUNTIME_BASE_URL: 'http://127.0.0.1:8642',
      MIY_HERMES_RUNTIME_PORT: '8642',
      MIY_HERMES_TERMINAL_BROKER_BASE_URL: 'http://127.0.0.1:8765',
      MIY_HERMES_TERMINAL_BROKER_PORT: '8765',
      MIY_HERMES_TERMINAL_RESOURCE_NAMESPACE: 'prod',
      MIY_INFRA_NGINX_PORT: '14200',
      MIY_OPF_ENABLED: 'true',
      MIY_OPF_REQUIRED: 'true',
      MIY_OPF_SERVICE_BASE_URL: 'http://127.0.0.1:18081',
      MIY_WEB_DEV_PORT: '4200',
      ...overrides,
    }),
  );
}

test('parses dotenv assignments without evaluating shell syntax', () => {
  const values = parseEnvText(`
    # comment
    export MIY_ENV_PROFILE=prod
    MIY_APP_PUBLIC_URL="https://prod.example.com"
    ignored shell text
  `);
  assert.equal(values.get('MIY_ENV_PROFILE'), 'prod');
  assert.equal(values.get('MIY_APP_PUBLIC_URL'), 'https://prod.example.com');
  assert.equal(values.has('ignored shell text'), false);
});

test('accepts a separated production runtime configuration', () => {
  const config = assertProductionAppEnv(validEnv());
  assert.equal(config.appPort, 8000);
  assert.equal(config.bentoBindHost, '127.0.0.1');
  assert.equal(config.bentoServerUrl.href, 'https://bento.example.com/');
  assert.equal(config.hermesRuntimeBaseUrl.href, 'http://127.0.0.1:8642/');
  assert.equal(
    config.hermesTerminalBrokerBaseUrl.href,
    'http://127.0.0.1:8765/',
  );
  assert.equal(config.hermesTerminalBrokerPort, 8765);
  assert.equal(config.publicBaseUrl.href, 'https://prod.example.com/');
});

test('first-party preflight reserves both internal API ports without changing legacy configuration', () => {
  assert.equal(assertProductionAppEnv(validEnv(), { firstParty: true }).appPort, 8000);
  for (const port of ['18779', '18780']) {
    const values = validEnv({ MIY_APP_PORT: port,
      MIY_HERMES_MCP_SERVER_URL: `http://127.0.0.1:${port}/api/v1/internal/hermes/mcp` });
    assert.equal(assertProductionAppEnv(values).appPort, Number(port));
    assert.throws(() => assertProductionAppEnv(values, { firstParty: true }), /reserved first-party internal API port/);
  }
});

test('requires an exact private or loopback Bento IPv4 bind address', () => {
  for (const value of [
    '',
    '0.0.0.0',
    '::',
    '::1',
    'fd00::1',
    '203.0.113.10',
    'proxy.internal',
  ]) {
    assert.throws(
      () => assertProductionAppEnv(validEnv({ MIY_BENTO_BIND_HOST: value })),
      /exact private or loopback IPv4 address/,
    );
  }

  for (const value of ['10.20.30.40', '172.16.0.1', '192.168.1.10']) {
    assert.equal(
      assertProductionAppEnv(validEnv({ MIY_BENTO_BIND_HOST: value }))
        .bentoBindHost,
      value,
    );
  }
});

test('rejects development access and port collisions', () => {
  assert.throws(
    () =>
      assertProductionAppEnv(validEnv({ MIY_API_ALLOW_DEV_ADMIN_LOGIN: '1' })),
    /ALLOW_DEV_ADMIN_LOGIN/,
  );
  assert.throws(
    () => assertProductionAppEnv(validEnv({ MIY_APP_PORT: '4200' })),
    /WEB_DEV_PORT/,
  );
  assert.throws(
    () => assertProductionAppEnv(validEnv({ MIY_APP_PORT: '18084' })),
    /BENTO_PORT/,
  );
});

test('requires a credential-free HTTPS public origin', () => {
  for (const value of [
    '',
    'http://prod.example.com',
    'https://localhost:8000',
    'https://user:password@prod.example.com',
  ]) {
    assert.throws(() =>
      assertProductionAppEnv(validEnv({ MIY_APP_PUBLIC_URL: value })),
    );
  }
});

test('requires a separate credential-free HTTPS Bento origin', () => {
  for (const value of [
    '',
    'http://bento.example.com',
    'https://localhost:18084',
    'https://user:password@bento.example.com',
    'https://prod.example.com',
  ]) {
    assert.throws(() =>
      assertProductionAppEnv(validEnv({ MIY_BENTO_SERVER_URL: value })),
    );
  }
});

test('rejects unsafe production secrets and proxy trust', () => {
  for (const value of [
    '',
    'dev-content-grant-signing-key',
    'short',
    'a'.repeat(31),
    `development-${'a'.repeat(32)}`,
    `CHANGE_ME-${'a'.repeat(32)}`,
  ]) {
    assert.throws(
      () =>
        assertProductionAppEnv(
          validEnv({ MIY_CONTENT_GRANT_SIGNING_KEY: value }),
        ),
      /CONTENT_GRANT_SIGNING_KEY/,
    );
  }
  assert.throws(
    () =>
      assertProductionAppEnv(validEnv({ MIY_APP_FORWARDED_ALLOW_IPS: '*' })),
    /exact proxy IP addresses/,
  );
});

test('requires a separate loopback privacy-filter origin', () => {
  assert.throws(
    () =>
      assertProductionAppEnv(
        validEnv({
          MIY_OPF_SERVICE_BASE_URL: 'http://127.0.0.1:8000',
        }),
      ),
    /must not collide/,
  );
  assert.throws(
    () =>
      assertProductionAppEnv(
        validEnv({
          MIY_OPF_SERVICE_BASE_URL: 'https://opf.example.com',
        }),
      ),
    /loopback HTTP origin/,
  );
});

test('requires isolated production Hermes credentials', () => {
  for (const [key, value] of [
    ['OPENROUTER_API_KEY', 'short'],
    ['MIY_HERMES_API_KEY', 'change-me'],
    ['MIY_HERMES_MANAGEMENT_TOKEN', 'short'],
    ['MIY_HERMES_MCP_SHARED_SECRET', 'dev-secret'],
  ]) {
    assert.throws(() => assertProductionAppEnv(validEnv({ [key]: value })));
  }
  assert.throws(
    () =>
      assertProductionAppEnv(
        validEnv({
          MIY_HERMES_MANAGEMENT_TOKEN:
            'production-hermes-runtime-secret-00000001',
        }),
      ),
    /must be distinct/,
  );
});

test('accepts Hermes with administrator-managed providers and no legacy OpenRouter key', () => {
  assert.doesNotThrow(() =>
    assertProductionAppEnv(validEnv({ OPENROUTER_API_KEY: '' })),
  );
});

test('requires loopback Hermes endpoints on their declared ports', () => {
  assert.throws(
    () =>
      assertProductionAppEnv(
        validEnv({
          MIY_HERMES_RUNTIME_BASE_URL: 'http://0.0.0.0:8642',
        }),
      ),
    /loopback HTTP endpoint/,
  );
  assert.throws(
    () =>
      assertProductionAppEnv(
        validEnv({
          MIY_HERMES_MCP_SERVER_URL: 'http://127.0.0.1:8000/api/v1/tools/mcp',
        }),
      ),
    /internal Hermes MCP endpoint/,
  );
  assert.throws(
    () =>
      assertProductionAppEnv(
        validEnv({
          MIY_HERMES_TERMINAL_BROKER_BASE_URL: 'http://127.0.0.1:8766',
        }),
      ),
    /Hermes Terminal broker port/,
  );
});

test('worker healthcheck uses the container hostname without spawning hostname', async () => {
  const composeText = await readFile(
    new URL('../ops/compose/miy-prod.app.yml', import.meta.url),
    'utf8',
  );
  assert.match(composeText, /--destination "prod-worker@\$\$\{HOSTNAME\}"/);
  assert.doesNotMatch(composeText, /\$\$\(hostname\)/);
});

test('production compose does not add a second ingress proxy', async () => {
  const [composeText, releaseScript] = await Promise.all([
    readFile(
      new URL('../ops/compose/miy-prod.app.yml', import.meta.url),
      'utf8',
    ),
    readFile(new URL('./prod-app.sh', import.meta.url), 'utf8'),
  ]);
  assert.doesNotMatch(composeText, /miy-edge|ops\/edge/);
  assert.match(releaseScript, /--remove-orphans/);
});

test('production image build embeds the validated Bento public URL', async () => {
  const [dockerfile, releaseScript] = await Promise.all([
    readFile(new URL('../ops/app/Dockerfile', import.meta.url), 'utf8'),
    readFile(new URL('./prod-app.sh', import.meta.url), 'utf8'),
  ]);
  assert.match(dockerfile, /ARG MIY_BENTO_SERVER_URL/);
  assert.match(dockerfile, /MIY_BENTO_SERVER_URL="\$\{MIY_BENTO_SERVER_URL\}"/);
  assert.match(
    releaseScript,
    /--build-arg "MIY_BENTO_SERVER_URL=\$bento_server_url"/,
  );
});

test('production runtime checks the fixed terminal broker port before mutation', async () => {
  const releaseScript = await readFile(
    new URL('./prod-app.sh', import.meta.url),
    'utf8',
  );
  assert.match(releaseScript, /require_terminal_broker_port_available/);
  assert.match(
    releaseScript,
    /refusing before release preparation or migration/,
  );
  assert.match(releaseScript, /expected_binding" == "127\.0\.0\.1:\$port"/);
});

for (const namespace of [
  undefined,
  '',
  ' ',
  'dev',
  'local',
  'Prod',
  '-prod',
  'prod/team',
  'prod_team',
  'p'.repeat(33),
]) {
  test(`production rejects unsafe Hermes resource namespace ${JSON.stringify(namespace)}`, () => {
    assert.throws(
      () =>
        assertProductionAppEnv(
          validEnv({
            MIY_HERMES_TERMINAL_RESOURCE_NAMESPACE: namespace,
          }),
        ),
      /MIY_HERMES_TERMINAL_RESOURCE_NAMESPACE/,
    );
  });
}

for (const namespace of ['prod', 'company-prod-20260908', 'p'.repeat(32)]) {
  test(`production accepts explicit Hermes resource namespace ${namespace}`, () => {
    assert.doesNotThrow(() =>
      assertProductionAppEnv(
        validEnv({
          MIY_HERMES_TERMINAL_RESOURCE_NAMESPACE: namespace,
        }),
      ),
    );
  });
}

test('broker Compose maps the typed namespace and production has no fallback', async () => {
  for (const [filename, expression] of [
    ['miy-dev.infra.yml', '${MIY_HERMES_TERMINAL_RESOURCE_NAMESPACE:-dev}'],
    [
      'miy-prod.app.yml',
      '${MIY_HERMES_TERMINAL_RESOURCE_NAMESPACE:?Production Hermes resource namespace is required}',
    ],
  ]) {
    const text = await readFile(
      new URL(`../ops/compose/${filename}`, import.meta.url),
      'utf8',
    );
    const line = text
      .split('\n')
      .find((value) =>
        value.trim().startsWith('MIY_HERMES_TERMINAL_RESOURCE_NAMESPACE:'),
      );
    assert.equal(
      line?.trim(),
      `MIY_HERMES_TERMINAL_RESOURCE_NAMESPACE: ${expression}`,
    );
  }
});

// Actual required-review regressions: no inferred tag-only recovery and service grace.
test('P1 absent prior runtime cannot start a gate-refused candidate through recovery', async () => {
  const result = await forwardFixture('no-runtime', 'up');
  assert.equal(result.status, 1);
  assert.doesNotMatch(result.stdout, /start:|restored-existing|smoke/);
});

test('P1 retagged existing runtime refuses before stopping any prior writers', async () => {
  const result = await forwardFixture('retagged-runtime', 'up');
  assert.equal(result.status, 1);
  assert.doesNotMatch(result.stdout, /stop |start:|restored-existing|smoke/);
});

test('P2 forward stop preserves declared per-service grace without a timeout override', async () => {
  const result = await forwardFixture();
  assert.equal(result.status, 0);
  assert.match(result.stdout, /^stop api worker beat\n/);
  assert.doesNotMatch(result.stdout, /stop .*--timeout/);
});

for (const stage of ['mixed-prior', 'partial-prior', 'invalid-config-label']) {
  test(`P1 ${stage} cannot stop or restore an inconsistent prior runtime`, async () => {
    const result = await forwardFixture(stage, 'up');
    assert.equal(result.status, 1);
    assert.doesNotMatch(result.stdout, /stop |start:|restored-existing|smoke/);
  });
}

test('P1 lost captured container ID after gate failure refuses recovery', async () => {
  const result = await forwardFixture('replaced-prior', 'up');
  assert.equal(result.status, 1);
  assert.doesNotMatch(result.stdout, /start:|restored-existing|smoke/);
  assert.match(result.stderr, /operator recovery is required/);
});

test('P1 first startup with no prior runtime starts only after a successful gate', async () => {
  const result = await forwardFixture('first-start', 'up');
  assert.equal(result.status, 0, result.stderr);
  assert.ok(
    result.stdout.indexOf('cutover_gate') < result.stdout.indexOf('start:'),
  );
  assert.doesNotMatch(result.stdout, /restored-existing/);
});

test('P1 partial forward runtime start requires operator recovery without another startup', async () => {
  const result = await forwardFixture('start', 'up');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /operator recovery is required/);
  assert.equal((result.stdout.match(/start:/g) || []).length, 1);
  assert.doesNotMatch(result.stdout, /restored-existing|smoke/);
});

test('P1 recovery waits for saved containers to become healthy before smoke', async () => {
  const result = await forwardFixture('warmup', 'up');
  assert.equal(result.status, 1);
  assert.match(result.stdout, /health-wait\nsmoke/);
  assert.doesNotMatch(result.stderr, /restoration failed/);
});

for (const stage of ['warm-timeout', 'stopped-after-start']) {
  test(`P1 ${stage} recovery cannot report healthy restoration or start another container`, async () => {
    const result = await forwardFixture(stage, 'up');
    assert.equal(result.status, 1);
    assert.match(result.stderr, /operator recovery is required/);
    assert.doesNotMatch(result.stdout, /start:|smoke/);
  });
}

test('P1 changed captured configuration label after gate failure refuses recovery', async () => {
  const result = await forwardFixture('changed-definition', 'up');
  assert.equal(result.status, 1);
  assert.doesNotMatch(result.stdout, /start:|restored-existing|smoke/);
  assert.match(result.stderr, /operator recovery is required/);
});

test('P1 live label hashing never assumes config --hash env_file equivalence', async () => {
  const result = await forwardFixture('gate', 'up');
  assert.equal(result.status, 1);
  // Any config --hash call is refused by the pinned public-API fixture.
  assert.match(result.stdout, /smoke/);
  assert.doesNotMatch(result.stderr, /restoration failed/);
});

for (const state of [
  'exited',
  'unhealthy',
  'starting',
  'created',
  'paused',
  'restarting',
  'dead',
  'created-no-health',
  'exited-no-health',
]) {
  test(`P2 review378 known prior ${state} permits gated forward startup`, async () => {
    const result = await forwardFixture(`prior-${state}`, 'up');
    assert.equal(result.status, 0, result.stderr);
    assert.ok(result.stdout.indexOf('stop api worker beat') >= 0);
    assert.ok(
      result.stdout.indexOf('stop api worker beat') <
        result.stdout.indexOf('run --rm migrate'),
    );
    assert.ok(
      result.stdout.indexOf('run --rm migrate') <
        result.stdout.indexOf('cutover_gate'),
    );
    assert.ok(
      result.stdout.indexOf('cutover_gate') < result.stdout.indexOf('start:1:'),
    );
    assert.match(result.stdout, /start:1:.*\nsmoke/);
    assert.doesNotMatch(result.stdout, /restored-existing/);
  });

  test(`P2 review378 known prior ${state} cannot become a recovery target after gate refusal`, async () => {
    const result = await forwardFixture(`prior-${state}-gate`, 'up');
    assert.equal(result.status, 1);
    assert.match(result.stdout, /stop api worker beat\nrun --rm migrate\n/);
    assert.match(result.stdout, /cutover_gate/);
    assert.doesNotMatch(result.stdout, /start:|restored-existing|smoke/);
    assert.match(result.stderr, /operator recovery is required/);
  });
}

for (const stage of [
  'prior-inspect-error',
  'prior-invalid-status',
  'prior-invalid-running',
  'prior-invalid-health',
  'prior-empty-status',
]) {
  test(`P2 review378 ${stage} remains unknown and refuses before stop`, async () => {
    const result = await forwardFixture(stage, 'up');
    assert.equal(result.status, 1);
    assert.doesNotMatch(
      result.stdout,
      /stop |run --rm|start:|restored-existing|smoke/,
    );
  });
}
