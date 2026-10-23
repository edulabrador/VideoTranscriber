import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { applyCobaltSecurity } from './apply-cobalt-security.mjs';

test('dependency patch is repeatable and preserves unrelated local settings', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'cobalt-patch-test-'));
  const target = path.join(temporary, 'checkout');
  fs.mkdirSync(target);
  const git = args => execFileSync('git', ['-c', 'core.fsmonitor=false', '-C', target, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  try {
    git(['init']);
    git(['config', 'user.name', 'Fixture']);
    git(['config', 'user.email', 'fixture@example.test']);
    const metadata = path.join(target, 'package.json');
    const workspace = path.join(target, 'pnpm-workspace.yaml');
    fs.writeFileSync(metadata, '{"version":"1.0.0"}\n');
    fs.writeFileSync(workspace, 'packages:\n    - api\n');
    git(['add', '.']); git(['commit', '-m', 'Synthetic fixture']);
    fs.writeFileSync(metadata, '{"version":"1.0.1"}\n');
    const patch = path.join(temporary, 'security.patch');
    fs.writeFileSync(patch, git(['diff', '--', 'package.json']));
    fs.writeFileSync(metadata, '{"version":"1.0.0"}\n');
    fs.writeFileSync(path.join(temporary, 'cobalt-security-overrides.json'), JSON.stringify({ 'cookie@0.6': '^0.7.0' }));
    fs.appendFileSync(workspace, '\nallowBuilds:\n    esbuild: false\n');
    assert.equal(applyCobaltSecurity(target, patch), true);
    assert.equal(JSON.parse(fs.readFileSync(metadata)).version, '1.0.1');
    assert.ok(fs.readFileSync(workspace, 'utf8').includes('esbuild: false'));
    assert.equal(applyCobaltSecurity(target, patch), false);
    fs.writeFileSync(metadata, '{"version":"unexpected-local-edit"}\n');
    assert.throws(() => applyCobaltSecurity(target, patch), /unexpected local dependency changes/);
    assert.equal(JSON.parse(fs.readFileSync(metadata)).version, 'unexpected-local-edit');
  } finally {
    const parent = path.resolve(os.tmpdir()) + path.sep;
    if (!path.resolve(temporary).startsWith(parent)) throw new Error('Unsafe test cleanup path');
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});
