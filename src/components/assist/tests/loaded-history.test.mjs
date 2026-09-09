import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeLoadedIds, parseLoadedHistory, resolvedLoadedIds, MAX_EXCLUDED_TRACKS } from '../loaded-history.ts';

test('ambiguous, unresolved, and empty observations never become history even with an attached candidate', () => {
  assert.deepEqual(resolvedLoadedIds([
    { status: 'resolved', track: { id: 12 } },
    { status: 'ambiguous', track: { id: 13 } },
    { status: 'unresolved', track: { id: 14 } },
    { status: 'empty', track: null },
    { status: 'resolved', track: { id: 12 } },
  ]), [12]);
});
test('loading a new deck track preserves unloaded history through persistence; reset to current decks releases prior tracks', () => {
  const first = resolvedLoadedIds([{ status: 'resolved', track: { id: 8 } }]);
  const current = resolvedLoadedIds([{ status: 'resolved', track: { id: 20 } }]);
  const restored = parseLoadedHistory(JSON.stringify(mergeLoadedIds(first, current)));
  assert.deepEqual(restored, [8, 20]);
  const reset = current;
  assert.deepEqual(parseLoadedHistory(JSON.stringify(reset)), [20]);
});
test('invalid stored histories cannot inject unsupported IDs; duplicates normalize', () => {
  assert.deepEqual(parseLoadedHistory('[3,1,3]'), [1,3]);
  for (const raw of ['{}', '[0]', '[-1]', '[1.5]', '["1"]', 'broken']) assert.throws(() => parseLoadedHistory(raw));
});
test('history beyond request limit remains intact so UI can require explicit reset without silently forgetting oldest tracks', () => {
  const ids = Array.from({ length: MAX_EXCLUDED_TRACKS }, (_, i) => i + 1);
  const next = mergeLoadedIds(ids, [MAX_EXCLUDED_TRACKS + 1]);
  assert.equal(next.length, MAX_EXCLUDED_TRACKS + 1);
  assert.equal(next[0], 1);
  assert.deepEqual(parseLoadedHistory(JSON.stringify(next)), next);
});
