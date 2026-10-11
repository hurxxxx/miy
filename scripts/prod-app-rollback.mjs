#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import {
  closeSync,
  constants,
  existsSync,
  fstatSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

import { assertLegacyOfficialRouting } from './prod-app-smoke.mjs';

const IMAGE_ID = /^sha256:[a-f0-9]{64}$/;
const REVISION = /^[a-f0-9]{40}$/;

function invoke(command, args) {
  const fileIndex = command === 'docker' && args[0] === 'compose' ? args.indexOf('-f') : -1;
  const previousPrefix = fileIndex >= 0
    ? path.basename(args[fileIndex + 1]).replace(/-prod\.app\.yml$/, '').replaceAll('-', '_').toUpperCase() + '_'
    : null;
  return execFileSync(command, args, {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    env: Object.fromEntries(Object.entries(process.env).filter(([key]) =>
      !key.startsWith('MIY_') && !(previousPrefix && key.startsWith(previousPrefix)) && key !== 'OPENROUTER_API_KEY')),
  }).trim();
}

function checked(run, command, args, label) {
  try {
    return run(command, args).trim();
  } catch {
    // Child diagnostics can include environment values. Only describe the stage.
    throw new Error(`Rollback ${label} failed.`);
  }
}

function readSecureEnv(file) {
  let descriptor;
  try {
    descriptor = openSync(
      file,
      constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
    );
    const stat = fstatSync(descriptor);
    if (
      !stat.isFile() ||
      (stat.mode & 0o7777) !== 0o600 ||
      stat.uid !== process.getuid()
    ) {
      throw new Error('insecure');
    }
    return { contents: readFileSync(descriptor), stat };
  } catch {
    throw new Error(
      'Rollback environment must be an owned regular non-symlink file with mode 0600.',
    );
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
  }
}

function ensurePrivateDirectory(directory) {
  if (!existsSync(directory)) mkdirSync(directory, { mode: 0o700 });
  const stat = lstatSync(directory);
  if (
    !stat.isDirectory() ||
    stat.isSymbolicLink() ||
    stat.uid !== process.getuid() ||
    stat.mode & 0o022
  ) {
    throw new Error(
      'Rollback directory must be owned and not writable by other users.',
    );
  }
}

function checkSnapshotTree(directory) {
  for (const entry of readdirSync(directory)) {
    const candidate = path.join(directory, entry);
    const stat = lstatSync(candidate);
    if (stat.isDirectory()) checkSnapshotTree(candidate);
    else if (!stat.isFile() || stat.isSymbolicLink()) {
      throw new Error(
        'Rollback deployment assets must contain only regular files and directories.',
      );
    }
  }
}

function envDigest(contents) {
  return createHash('sha256').update(contents).digest('hex');
}

function verifyOfficialImage(rootDir, run, image, expectedImage, role) {
  if (!IMAGE_ID.test(image)) throw new Error('Pinned official image must be immutable.');
  for (const ref of [image, expectedImage]) {
    if (checked(run, 'docker', ['image', 'inspect', '--format', '{{.Id}}', ref], 'official image identity') !== image)
      throw new Error('Pinned official image does not match the prior artifact.');
  }
  const label = (name) => checked(run, 'docker', ['image', 'inspect', '--format', `{{ index .Config.Labels "${name}" }}`, image], 'official image metadata');
  const revision = label('org.opencontainers.image.revision');
  if (!REVISION.test(revision) || label('org.opencontainers.image.title') !== `miy-${role}`
      || label('io.miy.artifact.activation') !== 'first-party-runtime'
      || label('io.miy.artifact.source-dirty') !== 'false'
      || !/^[a-f0-9]{64}$/.test(label('io.miy.release.contract'))
      || !REVISION.test(label('io.miy.release.source-revision'))
      || !REVISION.test(label('io.miy.release.tree'))
      || !/^linux\/(amd64|arm64)$/.test(label('io.miy.release.platform'))
      || !/^[a-f0-9]{64}$/.test(label('io.miy.release.bento-url-sha256'))
      || !/^[1-9][0-9]*$/.test(label('io.miy.release.merge-request'))
      || !/^[1-9][0-9]*$/.test(label('io.miy.release.pipeline')))
    throw new Error('Pinned official image lacks its guarded release metadata.');
  if (checked(run, 'git', ['-C', rootDir, 'rev-parse', '--verify', `${revision}^{commit}`], 'official Git source') !== revision)
    throw new Error('Pinned official source is unavailable.');
  const tree = label('io.miy.release.tree');
  if (checked(run, 'git', ['-C', rootDir, 'rev-parse', `${revision}^{tree}`], 'official Git tree') !== tree)
    throw new Error('Pinned official source tree does not match.');
  if (checked(run, 'git', ['-C', rootDir, 'rev-parse', `${label('io.miy.release.source-revision')}^{tree}`], 'official reviewed tree') !== tree)
    throw new Error('Pinned official reviewed source does not match.');
  return { revision, tree, contract: label('io.miy.release.contract'), source: label('io.miy.release.source-revision'),
    platform: label('io.miy.release.platform'), bento: label('io.miy.release.bento-url-sha256'), mr: label('io.miy.release.merge-request') };
}

function imageBindings(runtime) {
  return `MIY_OFFICIAL_API_IMAGE=${runtime.officialApiImage}\nMIY_OFFICIAL_WORKER_IMAGE=${runtime.officialWorkerImage}\n`;
}

export function prepareRollbackBundle(
  { rootDir, envFile, image, expectedImage, topology = 'legacy', officialApiImage, officialWorkerImage,
    expectedOfficialApiImage = 'miy-official-api:prod', expectedOfficialWorkerImage = 'miy-official-worker:prod' },
  { run = invoke } = {},
) {
  if (!['legacy', 'first-party'].includes(topology)
      || (topology === 'legacy' && (officialApiImage || officialWorkerImage)))
    throw new Error('Invalid rollback topology.');
  if (!IMAGE_ID.test(image))
    throw new Error('Rollback image must be a full immutable sha256 image ID.');
  const actualId = checked(
    run,
    'docker',
    ['image', 'inspect', '--format', '{{.Id}}', image],
    'image inspection',
  );
  const expectedId = checked(
    run,
    'docker',
    ['image', 'inspect', '--format', '{{.Id}}', expectedImage],
    'expected image inspection',
  );
  if (actualId !== image || expectedId !== image) {
    throw new Error(
      'Rollback image does not match the required production image.',
    );
  }
  const revision = checked(
    run,
    'docker',
    [
      'image',
      'inspect',
      '--format',
      '{{ index .Config.Labels "org.opencontainers.image.revision" }}',
      image,
    ],
    'image revision inspection',
  );
  if (!REVISION.test(revision))
    throw new Error(
      'Rollback image must declare a full 40-character Git revision.',
    );
  const commit = checked(
    run,
    'git',
    ['-C', rootDir, 'rev-parse', '--verify', `${revision}^{commit}`],
    'Git commit verification',
  );
  if (commit !== revision)
    throw new Error(
      'Rollback image revision is not the expected local Git commit.',
    );
  let official;
  if (topology === 'first-party') {
    // Current artifact identity is checked before the new candidate changes tags.
    const api = verifyOfficialImage(rootDir, run, officialApiImage, expectedOfficialApiImage, 'official-api');
    const worker = verifyOfficialImage(rootDir, run, officialWorkerImage, expectedOfficialWorkerImage, 'official-worker');
    if (JSON.stringify(api) !== JSON.stringify(worker))
      throw new Error('Official rollback artifacts are not one reviewed pair.');
    official = { officialApiImage, officialWorkerImage, officialRevision: api.revision };
  }
  const { contents, stat } = readSecureEnv(envFile);
  const activeEnv = path.join(rootDir, '.env');
  if (existsSync(activeEnv)) {
    const activeStat = lstatSync(activeEnv);
    if (activeStat.dev === stat.dev && activeStat.ino === stat.ino) {
      throw new Error(
        'Rollback environment must be a separate backup of the previous environment.',
      );
    }
  }
  let parent = rootDir;
  for (const segment of ['.runtime', 'prod-app', 'rollback']) {
    parent = path.join(parent, segment);
    ensurePrivateDirectory(parent);
  }
  const bundle = mkdtempSync(path.join(parent, `${image.slice(7, 19)}-`));
  try {
    const archive = path.join(bundle, 'assets.tar');
    checked(
      run,
      'git',
      [
        '-C',
        rootDir,
        'archive',
        '--format=tar',
        `--output=${archive}`,
        revision,
        'ops',
        'scripts',
        'package.json',
      ],
      'deployment asset snapshot',
    );
    checked(
      run,
      'tar',
      [
        '--extract',
        '--file',
        archive,
        '--directory',
        bundle,
        '--no-same-owner',
        '--no-same-permissions',
      ],
      'deployment asset extraction',
    );
    rmSync(archive);
    checkSnapshotTree(bundle);
    for (const relative of [
      'scripts/prod-app-config.mjs',
      'scripts/prod-app-smoke.mjs',
      'package.json',
    ]) {
      if (!lstatSync(path.join(bundle, relative)).isFile())
        throw new Error('Rollback deployment assets are incomplete.');
    }
    const candidates = readdirSync(path.join(bundle, 'ops/compose'))
      .filter(name => /^[a-z][a-z0-9-]*-prod\.app\.yml$/.test(name));
    if (candidates.length !== 1) throw new Error('Rollback app definition is ambiguous.');
    const composeFile = `ops/compose/${candidates[0]}`;
    const project = candidates[0].replace(/-prod\.app\.yml$/, '-prod-app');
    writeFileSync(path.join(bundle, '.env'), contents, {
      flag: 'wx',
      mode: 0o600,
    });
    checked(
      run,
      'node',
      [
        path.join(bundle, 'scripts/prod-app-config.mjs'),
        path.join(bundle, '.env'),
      ],
      'previous environment validation',
    );
    const composeOverride = 'ops/first-party/compose.override.yml.example';
    const extra = [];
    if (official) {
      if (!lstatSync(path.join(bundle, composeOverride)).isFile()) throw new Error('Pinned split topology is missing.');
      writeFileSync(path.join(bundle, '.images.env'), imageBindings(official), { flag: 'wx', mode: 0o600 });
      extra.push('--env-file', path.join(bundle, '.images.env'));
    }
    const config = JSON.parse(checked(run, 'docker', [
      'compose', '--project-name', project, '--env-file', path.join(bundle, '.env'),
      ...extra, '-f', path.join(bundle, composeFile),
      ...(official ? ['-f', path.join(bundle, composeOverride)] : []), 'config', '--format', 'json',
    ], 'previous Compose validation'));
    const runtime = {
      composeFile,
      project: config.name,
      image: config.services?.api?.image,
      broker: config.services?.['hermes-terminal-broker']?.container_name,
      revisionEnv: `${config.name?.replace(/-prod-app$/, '').replaceAll('-', '_').toUpperCase()}_EXPECTED_REVISION`,
      ...(official ? { topology, composeOverride, ...official } : {}),
    };
    validateRuntime(runtime);
    if (official) {
      if (config.services?.['official-api']?.image !== officialApiImage || config.services?.['official-worker']?.image !== officialWorkerImage
          || config.services?.worker?.image !== runtime.image || config.services?.beat?.image !== runtime.image
          || config.services?.gateway?.image !== runtime.image)
        throw new Error('Pinned split Compose artifact bindings do not match.');
      for (const [service, entry] of [['api', 'miy_api.platform_runtime:app'], ['worker', 'miy_worker.first_party_platform:celery_app'],
        ['beat', 'miy_worker.first_party_beat:celery_app'], ['official-api', 'miy_official_api.runtime:app'], ['official-worker', 'miy_official_worker.runtime:celery_app'],
        ['gateway', 'ops/first-party/gateway.py']]) {
        if (!JSON.stringify(config.services?.[service]?.command).includes(entry)) throw new Error('Pinned split service assembly is invalid.');
      }
    }
    writeFileSync(
      path.join(bundle, 'rollback.json'),
      JSON.stringify({
        version: official ? 2 : 1,
        image,
        revision,
        envSha256: envDigest(contents),
        runtime,
      }),
      { flag: 'wx', mode: 0o600 },
    );
    return bundle;
  } catch (error) {
    rmSync(bundle, { recursive: true, force: true });
    throw error;
  }
}

function validateRuntime(runtime) {
  if (!runtime || !/^ops\/compose\/[a-z][a-z0-9-]*-prod\.app\.yml$/.test(runtime.composeFile)
    || !/^[a-z][a-z0-9-]*-prod-app$/.test(runtime.project)
    || !/^[a-z][a-z0-9-]*-app:prod$/.test(runtime.image)
    || !/^[a-z][a-z0-9-]*-prod-hermes-terminal-broker$/.test(runtime.broker)
    || !/^[A-Z][A-Z0-9_]*_EXPECTED_REVISION$/.test(runtime.revisionEnv)) {
    throw new Error('Invalid pinned rollback runtime identity.');
  }
  const brand = runtime.project.slice(0, -'-prod-app'.length);
  if (runtime.composeFile !== `ops/compose/${brand}-prod.app.yml`
      || runtime.image !== `${brand}-app:prod`
      || runtime.broker !== `${brand}-prod-hermes-terminal-broker`
      || runtime.revisionEnv !== `${brand.replaceAll('-', '_').toUpperCase()}_EXPECTED_REVISION`) {
    throw new Error('Rollback runtime identities do not match the pinned project.');
  }
  if (runtime.topology !== undefined && (runtime.topology !== 'first-party' || brand !== 'miy'
      || runtime.composeOverride !== 'ops/first-party/compose.override.yml.example'
      || !IMAGE_ID.test(runtime.officialApiImage) || !IMAGE_ID.test(runtime.officialWorkerImage)
      || !REVISION.test(runtime.officialRevision)))
    throw new Error('Invalid pinned split rollback runtime identity.');
}

export function rollbackRuntime(bundle) {
  const manifest = JSON.parse(readSecureEnv(path.join(bundle, 'rollback.json')).contents);
  validateRuntime(manifest.runtime);
  if (envDigest(readSecureEnv(path.join(bundle, '.env')).contents) !== manifest.envSha256)
    throw new Error('Rollback environment snapshot has changed.');
  if (manifest.runtime.topology === 'first-party'
      && readSecureEnv(path.join(bundle, '.images.env')).contents.toString() !== imageBindings(manifest.runtime))
    throw new Error('Rollback artifact bindings have changed.');
  return manifest.runtime;
}

export function restoreRollbackEnvironment({ rootDir, bundle, image }) {
  const parent = path.join(rootDir, '.runtime', 'prod-app', 'rollback');
  if (path.dirname(path.resolve(bundle)) !== path.resolve(parent)) {
    throw new Error('Rollback bundle must belong to this production checkout.');
  }
  for (const directory of [
    path.join(rootDir, '.runtime'),
    path.join(rootDir, '.runtime', 'prod-app'),
    parent,
    bundle,
  ]) {
    ensurePrivateDirectory(directory);
  }
  const manifest = JSON.parse(
    readSecureEnv(path.join(bundle, 'rollback.json')).contents.toString('utf8'),
  );
  if (
    ![1, 2].includes(manifest.version) ||
    manifest.image !== image ||
    !IMAGE_ID.test(image) ||
    !REVISION.test(manifest.revision)
  ) {
    throw new Error('Rollback bundle image identity does not match.');
  }
  if ((manifest.version === 2) !== (manifest.runtime?.topology === 'first-party'))
    throw new Error('Rollback manifest topology does not match.');
  rollbackRuntime(bundle);
  const { contents } = readSecureEnv(path.join(bundle, '.env'));
  if (envDigest(contents) !== manifest.envSha256)
    throw new Error('Rollback environment snapshot has changed.');
  const destination = path.join(rootDir, '.env');
  const destinationStat = lstatSync(destination, { throwIfNoEntry: false });
  if (
    destinationStat &&
    (!destinationStat.isFile() || destinationStat.isSymbolicLink())
  ) {
    throw new Error(
      'Production environment destination must be a regular non-symlink file.',
    );
  }
  const temporary = path.join(rootDir, `.env.rollback-${randomUUID()}`);
  let descriptor;
  try {
    descriptor = openSync(temporary, 'wx', 0o600);
    writeFileSync(descriptor, contents);
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    renameSync(temporary, destination);
    const directory = openSync(rootDir, constants.O_RDONLY);
    try {
      fsyncSync(directory);
    } finally {
      closeSync(directory);
    }
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    rmSync(temporary, { force: true });
  }
}

export async function assertRollbackLegacyRouting(bundle) {
  const runtime = rollbackRuntime(bundle);
  if (runtime.topology === 'first-party')
    throw new Error('Legacy routing recovery requires a legacy bundle.');
  // The pinned validator owns the old branding and configuration contract.
  // Current checks inspect only its public runtime locations, never .env values.
  const owner = await import(pathToFileURL(path.join(bundle, 'scripts/prod-app-config.mjs')).href);
  if (typeof owner.assertProductionAppEnv !== 'function' || typeof owner.readEnvFile !== 'function')
    throw new Error('Pinned rollback config does not expose its public runtime contract.');
  const config = owner.assertProductionAppEnv(owner.readEnvFile(path.join(bundle, '.env')));
  await assertLegacyOfficialRouting(config);
}

async function main(args) {
  const [command, rootDir, envOrBundle, image, expectedImage] = args;
  if (command === 'prepare' && args.length >= 5) {
    const options = {};
    const names = { '--topology': 'topology', '--official-api-image': 'officialApiImage', '--official-worker-image': 'officialWorkerImage',
      '--expected-official-api-image': 'expectedOfficialApiImage', '--expected-official-worker-image': 'expectedOfficialWorkerImage' };
    for (let index = 5; index < args.length; index += 2) {
      const name = names[args[index]];
      if (!name || !args[index + 1] || options[name] !== undefined) throw new Error('Invalid rollback binding argument.');
      options[name] = args[index + 1];
    }
    process.stdout.write(
      `${prepareRollbackBundle({ rootDir, envFile: envOrBundle, image, expectedImage, ...options })}\n`,
    );
  } else if (command === 'runtime' && args.length === 2) {
    const runtime = rollbackRuntime(rootDir);
    const fields = [runtime.composeFile, runtime.project, runtime.image, runtime.broker, runtime.revisionEnv];
    if (runtime.topology === 'first-party') fields.push(runtime.officialApiImage, runtime.officialWorkerImage, runtime.composeOverride, runtime.officialRevision);
    process.stdout.write(fields.join('\n') + '\n');
  } else if (command === 'restore-env' && args.length === 4) {
    restoreRollbackEnvironment({ rootDir, bundle: envOrBundle, image });
  } else if (command === 'smoke-routing' && args.length === 2) {
    await assertRollbackLegacyRouting(rootDir);
  } else {
    throw new Error('Invalid rollback helper command.');
  }
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main(process.argv.slice(2)).catch(() => {
    process.stderr.write(
      'Production rollback preparation or environment restoration failed; no environment values were logged.\n',
    );
    process.exitCode = 1;
  });
}
