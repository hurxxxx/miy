import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAX_INPUT_BYTES = 1024 * 1024;
const git = (root, args) =>
  execFileSync('git', ['-C', root, ...args], {
    encoding: 'utf8',
    timeout: 3000,
    maxBuffer: 8 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
const within = (root, target) => {
  const relative = path.relative(root, target);
  return (
    relative === '' ||
    (!relative.startsWith(`..${path.sep}`) &&
      relative !== '..' &&
      !path.isAbsolute(relative))
  );
};
export function resolveRoot(cwd) {
  if (typeof cwd !== 'string' || !path.isAbsolute(cwd))
    throw new Error('invalid cwd');
  return fs.realpathSync(git(cwd, ['rev-parse', '--show-toplevel']).trim());
}

function resolvedPatchPath(root, name) {
  let target = path.resolve(root, name);
  const tail = [];
  while (!fs.existsSync(target)) {
    const parent = path.dirname(target);
    if (parent === target) break;
    tail.unshift(path.basename(target));
    target = parent;
  }
  return path.join(fs.realpathSync(target), ...tail);
}

export function patchViolation(root, patch, cwd = root) {
  if (
    typeof patch !== 'string' ||
    !patch.startsWith('*** Begin Patch\n') ||
    !patch.trimEnd().endsWith('*** End Patch') ||
    !/^\*\*\* (?:Add File|Update File|Delete File): .+$/m.test(patch)
  )
    throw new Error('invalid patch');
  for (const match of patch.matchAll(
    /^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$/gm,
  )) {
    const name = match[1].trim();
    const target = resolvedPatchPath(cwd, name);
    if (
      target.split(path.sep).includes('.git') ||
      path.resolve(cwd, name).split(path.sep).includes('.git')
    ) {
      return 'Git metadata must be changed through Git, not a file patch.';
    }
    if (
      within(root, target) &&
      /(?:\.generated\.(?:ts|d\.ts)|_generated\.py)$/.test(target)
    ) {
      return 'Generated contracts must be updated through their owning generator.';
    }
  }
  return null;
}

// Only the native apply_patch payload is supported. Shell command policy remains
// in native .rules; this hook does not parse shell programs or run validation.
export function handleEvent(input, dependencies = {}) {
  if (
    input.hook_event_name !== 'PreToolUse' ||
    input.tool_name !== 'apply_patch'
  )
    return {};
  const root = (dependencies.resolveRoot ?? resolveRoot)(input.cwd);
  const violation = patchViolation(root, input.tool_input?.command, input.cwd);
  return violation
    ? {
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'deny',
          permissionDecisionReason: violation,
        },
      }
    : {};
}

export async function main() {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > MAX_INPUT_BYTES) throw new Error('hook input too large');
    chunks.push(chunk);
  }
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const result = handleEvent(input);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === path.join(HERE, 'codex-hooks.mjs')
) {
  main().catch(() => {
    // Exit 2 is the documented blocking/feedback status. Never echo tool input or stderr.
    process.stderr.write(
      'Project patch guard could not validate this operation. Inspect the hook configuration.\n',
    );
    process.exitCode = 2;
  });
}
