import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createUpdateController } from './update-controller.ts';

function setup(overrides = {}) {
  const calls = [];
  const update = { currentVersion: '0.5.6', version: '0.5.7',
    async download(progress) { calls.push('download'); progress({ event: 'Started', data: { contentLength: 100 } }); progress({ event: 'Progress', data: { chunkLength: 40 } }); progress({ event: 'Progress', data: { chunkLength: 60 } }); },
    async install() { calls.push('install'); }, async close() { calls.push('close'); },
  };
  const controller = createUpdateController({ currentVersion: '0.5.6',
    check: async () => { calls.push('check'); return update; },
    activeSession: async () => false, relaunch: async () => { calls.push('relaunch'); }, ...overrides,
  });
  return { controller, calls, update };
}

test('automatic and manual checks share an operation; latest is explicit', async () => {
  let checks = 0;
  const { controller } = setup({ check: async () => { checks++; return null; } });
  await Promise.all([controller.automaticCheck(), controller.automaticCheck(), controller.check()]);
  assert.equal(checks, 1);
  assert.equal(controller.getSnapshot().phase, 'latest');
  await controller.check();
  assert.equal(checks, 2);
});

test('download reports real bytes and installs once even on repeated clicks', async () => {
  const { controller, calls } = setup();
  const snapshots = [];
  controller.subscribe(() => snapshots.push(controller.getSnapshot()));
  await controller.check();
  await Promise.all([controller.install(), controller.install()]);
  assert.deepEqual(calls, ['check', 'download', 'install', 'relaunch']);
  assert(snapshots.some(state => state.phase === 'downloading' && state.downloaded === 40 && state.total === 100));
  assert.equal(controller.getSnapshot().phase, 'ready');
});

test('a Junction session started during download blocks installation and can resume', async () => {
  let checks = 0;
  const { controller, calls } = setup({ activeSession: async () => ++checks === 2 });
  await controller.check();
  await controller.install();
  assert.deepEqual(calls, ['check', 'download']);
  assert.equal(controller.getSnapshot().phase, 'available');
  assert.match(controller.getSnapshot().error, /Junction/);
  await controller.install();
  assert.deepEqual(calls, ['check', 'download', 'install', 'relaunch']);
});

test('failed checks are visible and retryable', async () => {
  let checks = 0;
  const { controller } = setup({ check: async () => { if (++checks === 1) throw Error('offline'); return null; } });
  await controller.check();
  assert.equal(controller.getSnapshot().phase, 'error');
  assert.match(controller.getSnapshot().error, /offline/);
  await controller.check();
  assert.equal(controller.getSnapshot().phase, 'latest');
});

test('failed relaunch retries without installing again', async () => {
  let restarts = 0;
  const { controller, calls } = setup({ relaunch: async () => { if (++restarts === 1) throw Error('restart failed'); } });
  await controller.check();
  await controller.install();
  assert.equal(controller.getSnapshot().phase, 'ready');
  await controller.restart();
  assert.equal(restarts, 2);
  assert.deepEqual(calls, ['check', 'download', 'install']);
});
