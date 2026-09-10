import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pathBreadcrumbs } from './path-breadcrumbs.ts';

test('macOS root and Unicode paths', () => {
  assert.deepEqual(pathBreadcrumbs('/Users/音楽 DJ').map(c => c.path), ['/', '/Users', '/Users/音楽 DJ']);
});
test('Windows drive root remains absolute', () => {
  assert.deepEqual(pathBreadcrumbs('C:\\Users\\音楽 DJ').map(c => c.path), ['C:\\', 'C:\\Users', 'C:\\Users\\音楽 DJ']);
  assert.deepEqual(pathBreadcrumbs('D:/Music').map(c => c.path), ['D:/', 'D:/Music']);
});
test('UNC share is the navigation root', () => {
  assert.deepEqual(pathBreadcrumbs('\\\\NAS\\Music\\House').map(c => c.path), ['\\\\NAS\\Music\\', '\\\\NAS\\Music\\House']);
});
test('empty and relative paths', () => {
  assert.deepEqual(pathBreadcrumbs(''), []);
  assert.deepEqual(pathBreadcrumbs('Music/House').map(c => c.path), ['Music', 'Music/House']);
});
