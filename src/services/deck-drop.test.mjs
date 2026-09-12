import test from 'node:test';
import assert from 'node:assert/strict';
import { TRACK_MIME, readDraggedTrack, deckDropTarget, nativeDropElement, installDeckDropRouting } from './deck-drop.ts';

// Minimal DOM contract; real React surfaces and browser propagation are covered
// separately by tools/deck-drop-ui-test.mjs. No extra CI dependency is needed.
class ElementStub {
  constructor(dataset = {}, parent = null) { this.dataset = dataset; this.parent = parent; this.isConnected = true; this.attributes = new Map(); }
  closest(selector) {
    assert.equal(selector, '[data-track-drop-deck]');
    return this.dataset.trackDropDeck !== undefined ? this : this.parent?.closest(selector) ?? null;
  }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { this.attributes.delete(name); }
}
globalThis.Element = ElementStub;
const track = { id: 1, filepath: '/music/test.wav', duration: 180, title: 'Test' };
const transfer = value => ({ getData: type => type === TRACK_MIME ? JSON.stringify(value) : '', dropEffect: 'none' });
function setup(t) {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const listeners = new Map(), loads = [];
  const doc = {
    addEventListener(type, handler, capture = false) { listeners.set(type, { handler, capture }); },
    removeEventListener(type) { listeners.delete(type); },
  };
  const router = installDeckDropRouting(doc, (deck, value) => loads.push([deck, value.id]));
  t.after(() => router.dispose());
  const decks = Object.fromEntries(['A', 'B', 'C', 'D'].map(id => [id, new ElementStub({ trackDropDeck: id })]));
  const child = id => new ElementStub({}, decks[id]);
  const emit = (type, target = null, dataTransfer = transfer(track), extra = {}) => {
    const event = { target, dataTransfer, preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; }, ...extra };
    listeners.get(type)?.handler(event);
    return event;
  };
  const start = (value = track) => emit('dragstart', null, transfer(value));
  return { router, listeners, loads, decks, child, emit, start, tick: ms => t.mock.timers.tick(ms) };
}

test('payload validation rejects malformed, external and incomplete data', () => {
  assert.deepEqual(readDraggedTrack(transfer(track)), track);
  assert.equal(readDraggedTrack(null), null);
  assert.equal(readDraggedTrack({ getData: () => '{' }), null);
  assert.equal(readDraggedTrack({ getData: () => { throw Error('protected'); } }), null);
  for (const value of [null, {}, { ...track, id: -1 }, { ...track, id: '1' }, { ...track, filepath: '' }, { ...track, duration: 0 }]) {
    assert.equal(readDraggedTrack(transfer(value)), null);
  }
});

test('only dedicated deck surfaces qualify, never generic mixer data-deck', t => {
  const { child, decks } = setup(t);
  for (const id of ['A', 'B', 'C', 'D']) assert.equal(deckDropTarget(child(id)), decks[id]);
  assert.equal(deckDropTarget(new ElementStub({ deck: 'B' })), null);
  assert.equal(deckDropTarget(new ElementStub({ trackDropDeck: 'E' })), null);
  assert.equal(deckDropTarget(null), null);
});

test('native hit testing converts physical pixels exactly once at all display scales', () => {
  for (const scale of [1, 1.25, 1.5, 1.75, 2]) {
    const calls = [], doc = { elementFromPoint: (x, y) => { calls.push([x, y]); return null; } };
    assert.equal(nativeDropElement(doc, 120 * scale, 240 * scale, scale), null);
    assert.deepEqual(calls, [[120, 240]], 'no unscaled retry when outside the webview');
    for (const bad of [0, -1, NaN, Infinity]) nativeDropElement(doc, 120, 240, bad);
    nativeDropElement(doc, NaN, 240, scale);
    assert.equal(calls.length, 1);
  }
});

test('capture routing accepts every deck descendant and consumes exactly once', t => {
  const { start, emit, loads, child, listeners } = setup(t);
  assert.equal(listeners.get('dragstart').capture, false, 'React writes the MIME payload first');
  assert.equal(listeners.get('drop').capture, true, 'child handlers cannot intercept loading');
  for (const id of ['A', 'B', 'C', 'D']) {
    start();
    assert(emit('dragover', child(id)).prevented);
    const event = emit('drop', child(id));
    assert(event.prevented && event.stopped);
    emit('drop', child('B'));
  }
  assert.deepEqual(loads, ['A', 'B', 'C', 'D'].map(id => [id, 1]));
});

for (const order of ['DOM first', 'native first']) test(`${order}: conflicting native B and DOM A load only A`, t => {
  const { router, start, emit, child, loads, tick } = setup(t);
  start();
  if (order === 'native first') router.drop(child('B'));
  emit('drop', child('A'));
  emit('dragend');
  router.drop(child('B'));
  tick(100);
  assert.deepEqual(loads, [['A', 1]]);
  assert.equal(router.current().id, 1, 'retain consumed origin for late native notifications');
  tick(500);
  assert.equal(router.current(), null);
});

test('native-only webviews can load A/B/C/D and cannot double load', t => {
  const { router, start, child, loads, tick } = setup(t);
  for (const id of ['A', 'B', 'C', 'D']) {
    start(); router.drop(child(id)); tick(51); router.drop(child('B')); tick(51);
  }
  assert.deepEqual(loads, ['A', 'B', 'C', 'D'].map(id => [id, 1]));
});

test('latest native coordinates replace stale DOM hover when the drop has no DOM event', t => {
  const { router, start, emit, child, loads, tick } = setup(t);
  start(); emit('dragover', child('A')); router.drop(child('B')); router.leave(); tick(51);
  assert.deepEqual(loads, [['B', 1]]);
});

test('hover feedback follows exact deck and clears on outside, leave, drop and disposal', t => {
  const { router, start, emit, child, decks } = setup(t);
  const active = () => Object.entries(decks).filter(([, el]) => el.attributes.has('data-track-drop-active')).map(([id]) => id);
  start(); router.hover(child('A')); assert.deepEqual(active(), ['A']);
  emit('dragover', child('C')); router.hover(child('B')); assert.deepEqual(active(), ['B']);
  emit('dragover', new ElementStub()); assert.deepEqual(active(), []);
  router.leave(); router.hover(child('D')); assert.deepEqual(active(), ['D']);
  emit('drop', child('D')); assert.deepEqual(active(), []);
  start(); router.hover(child('A')); router.dispose(); assert.deepEqual(active(), []);
});

test('playlist/outside HTML drops keep their handlers but suppress late native deck loads', t => {
  const { router, start, emit, child, loads, tick } = setup(t);
  start(); emit('dragover', child('B'));
  assert(!emit('drop', new ElementStub()).stopped);
  router.drop(child('B')); tick(100);
  assert.deepEqual(loads, []);
});

test('native fallback for sampler is once-only and cannot run after an HTML deck drop', t => {
  const { router, start, emit, child, loads, tick } = setup(t);
  let samples = 0;
  start(); emit('drop', child('A')); router.drop(new ElementStub(), () => samples++); tick(100);
  assert.equal(samples, 0);
  start(); router.drop(new ElementStub(), () => samples++); tick(51);
  router.drop(child('B')); tick(100);
  assert.equal(samples, 1); assert.deepEqual(loads, [['A', 1]]);
});

test('Escape, new gestures, removed decks and unmount cancel pending native loads', t => {
  const { router, start, emit, child, decks, loads, tick, listeners } = setup(t);
  start(); router.drop(child('A')); emit('keydown', null, null, { key: 'Escape' }); tick(100);
  start(); router.drop(child('B')); start({ ...track, id: 2 }); tick(100);
  decks.C.isConnected = false; router.drop(child('C')); tick(100);
  start(); router.drop(child('D')); router.dispose(); tick(100);
  assert.deepEqual(loads, []); assert.equal(listeners.size, 0);
});

test('external files and sampler MIME never replace deck tracks', t => {
  const { router, emit, child, loads, tick } = setup(t);
  emit('dragstart', null, null);
  assert(!emit('dragover', child('A'), null).prevented);
  assert(!emit('drop', child('A'), null).stopped);
  router.drop(child('B')); tick(100); assert.deepEqual(loads, []);
});
