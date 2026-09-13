// Cross-machine manual Junction admission. The local process and a Windows
// process reached through SSH exchange exactly the same text as the desktop UI.
// Run explicitly; normal CI has no second machine:
//   PLUMDECK_JUNCTION_CROSS_REMOTE=user@host \
//   PLUMDECK_JUNCTION_CROSS_REMOTE_BINARY='C:\\path\\to\\plumdeck-mixxx-engine-host.exe' \
//   node --test native/mixxx-engine-host/tests/junction/cross-platform-runtime.test.mjs
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import test from 'node:test';
import path from 'node:path';

const localBinary = process.env.PLUMDECK_TEST_HOST
  || path.resolve(import.meta.dirname, '../../build-upstream/plumdeck-mixxx-engine-host');
const remote = process.env.PLUMDECK_JUNCTION_CROSS_REMOTE;
const remoteBinary = process.env.PLUMDECK_JUNCTION_CROSS_REMOTE_BINARY;
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function until(read, predicate, label, timeout = 50000) {
  const end = Date.now() + timeout;
  let last;
  while (Date.now() < end) {
    last = await read();
    if (predicate(last)) return last;
    await pause(80);
  }
  throw new Error(`${label}: timed out; state=${JSON.stringify({
    connection:last?.connection,
    exchange:last?.exchange && {state:last.exchange.state, detail:last.exchange.detail, errorCode:last.exchange.errorCode},
  })}`);
}

function wrap(child, label) {
  let hello;
  let id = 0;
  let stderr = '';
  const pending = new Map();
  child.stderr.on('data', (data) => {
    stderr = (stderr + data).slice(-16000);
    if (process.env.PLUMDECK_JUNCTION_TRACE) process.stderr.write(`[${label}] ${data}`);
  });
  const rejectAll = (reason) => {
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(reason);
    }
    pending.clear();
  };
  child.on('error', rejectAll);
  child.on('exit', (code) => rejectAll(new Error(`${label} exited (${code}): ${stderr}`)));
  createInterface({input:child.stdout}).on('line', (line) => {
    let reply;
    try { reply = JSON.parse(line); } catch { return; }
    const entry = pending.get(reply.id);
    if (!entry) return;
    pending.delete(reply.id);
    clearTimeout(entry.timer);
    entry.resolve(reply);
  });
  const raw = (op, params = {}) => {
    const current = ++id;
    const result = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(current);
        reject(new Error(`${label} ${op} timed out: ${stderr}`));
      }, 20000);
      pending.set(current, {resolve, reject, timer});
    });
    child.stdin.write(`${JSON.stringify({id:current, op, params, ...(hello ? {engineId:hello.engineId, sessionId:hello.sessionId} : {})})}\n`);
    return result;
  };
  const command = async (op, params = {}) => {
    const reply = await raw(op, params);
    assert.notEqual(reply.kind, 'error', `${label} ${op}: ${reply.error?.message || 'native error'}`);
    assert.notEqual(reply.ok, false, `${label} ${op}: ${reply.error?.message || 'native error'}`);
    return reply.data ?? reply;
  };
  return {
    label,
    command,
    snapshot: () => command('junction.snapshot'),
    diagnostics: () => stderr.replace(/PLUMDECK-JUNCTION-\S+/g, '[exchange redacted]'),
    async start() {
      hello = await command('session.hello');
      assert.equal(hello.engine.implementation, 'mixxx');
      await command('junction.network.configure', {stunUrls:[], turn:{}, save:false});
    },
    async close() {
      if (child.exitCode !== null) return;
      child.stdin.end();
      await Promise.race([new Promise((resolve) => child.once('exit', resolve)), pause(5000)]);
      if (child.exitCode === null) child.kill('SIGKILL');
    },
  };
}

function localPeer(label) {
  return wrap(spawn(localBinary, [], {env:{...process.env, PLUMDECK_JUNCTION_EPHEMERAL_NETWORK:'1'}}), label);
}

function windowsPeer(label) {
  const escaped = remoteBinary.replaceAll("'", "''");
  const command = `$env:PLUMDECK_JUNCTION_EPHEMERAL_NETWORK='1'; $env:PLUMDECK_JUNCTION_TRACE='1'; Set-Location (Split-Path '${escaped}'); & '${escaped}'`;
  return wrap(spawn('ssh', ['-T', '-o', 'BatchMode=yes', remote, command]), label);
}

const participant = (snapshot, peerId) => snapshot.participants.find((entry) => entry.peerId === peerId);

async function connect(host, guest) {
  await Promise.all([host.start(), guest.start()]);
  await host.command('junction.create', {
    djName:`${host.label} DJ`, sessionName:`${host.label} host`, adoptCurrent:false,
    startInLobby:true, exchangeMode:'manual',
  });
  const before = await host.snapshot();
  await host.command('junction.invite.create');
  const invited = await until(host.snapshot, (snapshot) => snapshot.participants.some((entry) =>
    entry.peerId !== snapshot.localPeerId && entry.exchange?.inviteText), `${host.label} invitation`);
  const slot = invited.participants.find((entry) => entry.peerId !== invited.localPeerId && entry.exchange?.inviteText);
  assert(slot);
  await guest.command('junction.exchange.inspect', {text:slot.exchange.inviteText});
  await guest.command('junction.join', {djName:`${guest.label} DJ`, text:slot.exchange.inviteText});
  const answered = await until(guest.snapshot, (snapshot) => snapshot.exchange?.responseText, `${guest.label} response`);
  assert.equal(answered.exchange.state, 'response_ready');
  await host.command('junction.exchange.import', {peerId:slot.peerId, text:answered.exchange.responseText});
  const pending = await host.snapshot();
  assert.equal(participant(pending, slot.peerId)?.exchange?.state, 'approval_pending');
  await pause(1000);
  assert.equal((await guest.snapshot()).exchange.state, 'response_ready', 'import alone must not tear down the guest');
  await host.command('junction.peer.approve', {peerId:slot.peerId, accept:true});
  await Promise.all([
    until(host.snapshot, (snapshot) => participant(snapshot, slot.peerId)?.exchange?.state === 'connected', `${host.label} connected`),
    until(guest.snapshot, (snapshot) => snapshot.exchange?.state === 'connected' && snapshot.connection?.state === 'connected', `${guest.label} connected`),
  ]);
  await host.command('junction.end');
  await until(guest.snapshot, (snapshot) => !snapshot.active, `${guest.label} ended`);
  assert(before.active);
}

test('manual Junction connects with macOS host and Windows guest, then reversed', {
  timeout:180000,
  skip:!remote || !remoteBinary ? 'set cross-platform SSH environment variables' : false,
}, async () => {
  for (const direction of ['mac-host', 'windows-host']) {
    const mac = localPeer(`mac-${direction}`);
    const windows = windowsPeer(`windows-${direction}`);
    try {
      await connect(direction === 'mac-host' ? mac : windows, direction === 'mac-host' ? windows : mac);
    } catch (error) {
      error.message += `\nmac diagnostics:\n${mac.diagnostics()}\nwindows diagnostics:\n${windows.diagnostics()}`;
      throw error;
    } finally {
      await Promise.allSettled([mac.close(), windows.close()]);
    }
  }
});
