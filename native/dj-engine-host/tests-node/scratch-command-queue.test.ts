import test from "node:test";
import assert from "node:assert/strict";
import { ScratchCommandQueue } from "../../../src/services/dj-engine/scratch-command-queue.ts";
import type { ScratchCommand, ScratchPhase } from "../../../src/types/dj-engine.ts";

const tick = () => new Promise<void>((resolve) => setImmediate(resolve));
const command = (gestureId: string, phase: ScratchPhase, positionMs: number): ScratchCommand =>
  ({ deck: "A", gestureId, phase, positionMs });

test("scratch lifecycle keeps barriers and only the newest adjacent move", async () => {
  const sent: ScratchCommand[] = [];
  const replies: (() => void)[] = [];
  const queue = new ScratchCommandQueue((value) => {
    sent.push({ ...value });
    return new Promise<void>((resolve) => replies.push(resolve));
  });

  const begin = queue.enqueue(command("g1", "begin", 0));
  await tick();
  const move = queue.enqueue(command("g1", "move", 10));
  for (let value = 11; value <= 1000; value++) assert.equal(queue.enqueue(command("g1", "move", value)), move);
  const end = queue.enqueue(command("g1", "end", 1000));
  assert.deepEqual(sent.map(({ phase, positionMs }) => [phase, positionMs]), [["begin", 0]]);

  replies.shift()!(); await begin; await tick();
  assert.deepEqual(sent.map(({ phase, positionMs }) => [phase, positionMs]), [["begin", 0], ["move", 1000]]);
  replies.shift()!(); await move; await tick();
  assert.equal(sent.at(-1)?.phase, "end");
  replies.shift()!(); await end;
});

test("a rapid next gesture cannot move across the preceding end/begin barriers", async () => {
  const sent: ScratchCommand[] = [];
  const replies: (() => void)[] = [];
  const queue = new ScratchCommandQueue((value) => {
    sent.push({ ...value });
    return new Promise<void>((resolve) => replies.push(resolve));
  });
  const promises = [
    queue.enqueue(command("old", "begin", 0)),
    queue.enqueue(command("old", "move", 50)),
    queue.enqueue(command("old", "end", 50)),
    queue.enqueue(command("new", "begin", 0)),
    queue.enqueue(command("new", "move", -25)),
  ];
  await tick();
  while (replies.length || sent.length < 5) {
    replies.shift()?.();
    await tick();
  }
  await Promise.all(promises);
  assert.deepEqual(sent.map(({ gestureId, phase }) => `${gestureId}:${phase}`), [
    "old:begin", "old:move", "old:end", "new:begin", "new:move",
  ]);
});

test("clear releases queued lifecycle promises without sending stale commands", async () => {
  const sent: ScratchCommand[] = [];
  let reply!: () => void;
  const queue = new ScratchCommandQueue((value) => {
    sent.push(value);
    return new Promise<void>((resolve) => { reply = resolve; });
  });
  const active = queue.enqueue(command("g", "begin", 0)); await tick();
  const move = queue.enqueue(command("g", "move", 25));
  const end = queue.enqueue(command("g", "end", 25));
  queue.clear();
  await Promise.all([move, end]);
  reply(); await active; await tick();
  assert.deepEqual(sent.map(({ phase }) => phase), ["begin"]);
});

test("stalled IPC bounds rapid gesture backlog while accepted ends remain reliable", async () => {
  const sent: ScratchCommand[] = [];
  const replies: (() => void)[] = [];
  const queue = new ScratchCommandQueue((value) => {
    sent.push({ ...value });
    return new Promise<void>((resolve) => replies.push(resolve));
  });
  const accepted: Promise<void>[] = [];
  for (let index = 0; index < 4; index++) {
    accepted.push(queue.enqueue(command(`g${index}`, "begin", 0)));
    accepted.push(queue.enqueue(command(`g${index}`, "move", index + 1)));
    accepted.push(queue.enqueue(command(`g${index}`, "end", index + 1)));
  }
  await assert.rejects(queue.enqueue(command("overflow", "begin", 0)), /backlog is full/);
  await tick();
  assert.deepEqual(sent.map(({ gestureId, phase }) => `${gestureId}:${phase}`), ["g0:begin"]);

  while (sent.length < 12 || replies.length) {
    replies.shift()?.();
    await tick();
  }
  await Promise.all(accepted);
  assert.deepEqual(sent.map(({ gestureId, phase }) => `${gestureId}:${phase}`), [
    "g0:begin", "g0:move", "g0:end",
    "g1:begin", "g1:move", "g1:end",
    "g2:begin", "g2:move", "g2:end",
    "g3:begin", "g3:move", "g3:end",
  ]);
});

test("queued direction reversals survive an ACK stall", async () => {
  const sent:ScratchCommand[]=[];const replies:(()=>void)[]=[];
  const queue=new ScratchCommandQueue(value=>{sent.push(value);return new Promise<void>(resolve=>replies.push(resolve));});
  const promises=[queue.enqueue(command('turn','begin',0))];await tick();
  for(const position of [10,20,-10,-20,30])promises.push(queue.enqueue(command('turn','move',position)));
  promises.push(queue.enqueue(command('turn','end',30)));
  while(sent.length<5||replies.length){replies.shift()?.();await tick();}
  await Promise.all(promises);assert.deepEqual(sent.map(p=>p.positionMs),[0,20,-20,30,30]);
});
