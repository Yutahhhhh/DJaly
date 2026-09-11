import assert from 'node:assert/strict';
import test from 'node:test';
import {existsSync, readdirSync} from 'node:fs';
import path from 'node:path';
import {docTopics, figuresOf} from './topics.ts';

const docsDir = path.resolve(import.meta.dirname, '../../../public/docs');

test('every Docs figure exists and every Docs image is referenced', () => {
  const referenced = new Set(docTopics.flatMap(topic => figuresOf(topic).map(figure => figure.image)));
  for (const image of referenced) assert(existsSync(path.join(docsDir, `${image}.png`)), `missing public/docs/${image}.png`);
  const unused = readdirSync(docsDir).filter(file => file.endsWith('.png') && !referenced.has(file.slice(0, -4)));
  assert.deepEqual(unused, [], 'unreferenced Docs images');
});

test('Docs topics keep related links and captions valid', () => {
  const ids = new Set(docTopics.map(topic => topic.id));
  for (const topic of docTopics) {
    for (const id of topic.related) assert(ids.has(id), `${topic.id} links to unknown topic ${id}`);
    for (const figure of figuresOf(topic)) assert(figure.caption.trim(), `${topic.id}/${figure.image} needs a caption`);
  }
});
