import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const patch = path.join(root, 'scripts', 'cobalt-security.patch');

/** Apply only a reviewed dependency patch. Unexpected local edits fail before any write. */
export function applyCobaltSecurity(directory, patchFile = patch) {
  const overrides = JSON.parse(fs.readFileSync(path.join(path.dirname(patchFile), 'cobalt-security-overrides.json'), 'utf8'));
  const block = '\n# Reviewed VideoTranscriber dependency overrides\noverrides:\n' + Object.entries(overrides).map(([key, value]) => `    ${key}: ${JSON.stringify(value)}\n`).join('');
  const workspace = path.join(directory, 'pnpm-workspace.yaml');
  const original = fs.readFileSync(workspace, 'utf8');
  const hasOverrides = original.includes(block.trim());
  if (!hasOverrides && /^overrides:/m.test(original)) throw new Error('Cobalt has unexpected local dependency changes in its overrides. No files were overwritten.');
  const git = args => spawnSync('git', ['-C', directory, 'apply', '--ignore-space-change', ...args, patchFile], { encoding: 'utf8', windowsHide: true });
  const alreadyPatched = git(['--reverse', '--check']).status === 0;
  if (alreadyPatched && hasOverrides) return false;
  if (!alreadyPatched && git(['--check']).status !== 0) {
    throw new Error('Cobalt has unexpected local dependency changes. Review them before applying scripts/cobalt-security.patch. No files were overwritten.');
  }
  if (!alreadyPatched && git([]).status !== 0) throw new Error('Could not apply the reviewed Cobalt dependency patch.');
  if (!hasOverrides) {
    const temporary = `${workspace}.security-tmp`;
    try {
      fs.writeFileSync(temporary, original + block);
      fs.renameSync(temporary, workspace);
    } finally { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); }
  }
  return true;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const changed = applyCobaltSecurity(path.join(root, 'services', 'cobalt'));
    console.log(changed ? 'Applied reviewed Cobalt dependency fixes.' : 'Cobalt dependency fixes already present.');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
