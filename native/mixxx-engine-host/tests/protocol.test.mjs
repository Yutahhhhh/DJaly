import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { once } from 'node:events';
import test from 'node:test';
import path from 'node:path';

const binary = process.env.PLUMDECK_TEST_HOST || path.resolve(import.meta.dirname, '../build-seam/plumdeck-mixxx-host-seam');
function client() {
  const child = spawn(binary, [], { stdio: ['pipe', 'pipe', 'pipe'] });
  const queue = [], waiters = [];
  let stderr = '';
  child.stderr.on('data', data => { stderr += data; });
  createInterface({ input: child.stdout }).on('line', line => {
    const message = JSON.parse(line);
    if (waiters.length) waiters.shift()(message); else queue.push(message);
  });
  return {
    child,
    send(message) { child.stdin.write(typeof message === 'string' ? message : JSON.stringify(message) + '\n'); },
    async next() {
      if (queue.length) return queue.shift();
      return Promise.race([new Promise(resolve => waiters.push(resolve)), new Promise((_, reject) => {
        const timer = setTimeout(() => reject(new Error(`host reply timeout; stderr=${stderr}`)), 3000); timer.unref();
      })]);
    },
    async close() { const ended = once(child, 'exit'); child.stdin.end(); const [code] = await ended; assert.equal(code, 0, stderr); },
  };
}

test('compiled Qt seam speaks v1, rejects stale sessions and never claims playback', async () => {
  const c = client();
  try {
    c.send({ id: 1, op: 'engine.ping' }); assert.equal((await c.next()).error.code, 'session_required');
    c.send({ protocol: 1, kind: 'command', id: 2, op: 'session.hello' });
    const hello = await c.next(); assert.equal(hello.kind, 'hello');
    assert.equal(hello.engine.audioAvailable, false); assert.equal(hello.engine.implementation, 'unavailable');
    assert.equal(typeof hello.engine.audioProblem, 'string'); assert(hello.engine.audioProblem.length > 0);
    assert.deepEqual(hello.engine.capabilities, []);
    const command = (id, op, params = {}, overrides = {}) => ({ id, op, params, sessionId: hello.sessionId, engineId: hello.engineId, ...overrides });
    c.send(command(3, 'state.snapshot')); const snapshot = (await c.next()).data;
    assert.equal(snapshot.decks.A.status, 'empty'); assert.equal(snapshot.audio.applied, false);
    assert.equal(snapshot.decks.B.available, false);
    const { isEngineSnapshot } = await import('../../../src/services/dj-engine/protocol.ts');
    assert(isEngineSnapshot(snapshot), 'C++ snapshot must satisfy TypeScript wire contract');
    c.send(command(4, 'deck.load', { deck: 'A', track: { trackId: 'x', path: '/tmp/example.wav' } }));
    assert.equal((await c.next()).error.code, 'unsupported_operation');
    c.send(command(4, 'engine.ping')); assert.equal((await c.next()).error.code, 'stale_command_id');
    c.send(command(5, 'engine.ping', {}, { engineId: 'old' })); assert.equal((await c.next()).error.code, 'engine_mismatch');
    c.send(command(5, 'engine.ping')); assert.equal((await c.next()).data.pong, true);
    c.send(command(6, 'sim.advanceTime')); assert.equal((await c.next()).error.code, 'unknown_op');
    c.send(command(7, 'mixer.crossfader')); assert.equal((await c.next()).error.code, 'unsupported_operation');
    c.send({ id: 1, op: 'session.hello' }); const renewed = await c.next();
    const invalidated = await c.next(); assert.equal(invalidated.event, 'session.invalidated'); assert.equal(invalidated.data.sessionId, hello.sessionId);
    c.send(command(8, 'engine.ping')); assert.equal((await c.next()).error.code, 'session_mismatch');
    c.send(command(2, 'state.snapshot', {}, { sessionId: renewed.sessionId }));
    const after = (await c.next()).data; assert.equal(after.seq, invalidated.seq); assert.equal(after.rev, snapshot.rev);
  } finally { await c.close(); }
});

test('malformed and oversized lines recover without poisoning the next command', async () => {
  const c = client();
  try {
    c.send('{broken}\n'); assert.equal((await c.next()).error.code, 'malformed_message');
    c.send({ id: 1.5, op: 'session.hello' }); assert.equal((await c.next()).error.code, 'malformed_message');
    c.send({ id: 1, op: 'session.hello', protocol: 2 }); assert.equal((await c.next()).error.code, 'protocol_version_unsupported');
    c.send('x'.repeat(1024 * 1024 + 5000) + '\n'); assert.equal((await c.next()).error.code, 'malformed_message');
    c.send({ id: 1, op: 'session.hello' }); assert.equal((await c.next()).kind, 'hello');
  } finally { await c.close(); }
});
