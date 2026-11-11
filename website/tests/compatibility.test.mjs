import test from 'node:test';
import assert from 'node:assert/strict';
import { checkCompatibility } from '../src/lib/compatibility.mjs';

const ready = { game: 'supported', os: 'windows', gpu: 'nvidia', driver: 'yes', ram: '16', vram: '8', disk: '60' };
test('documented Windows requirements pass without promising performance', () => {
  assert.equal(checkCompatibility(ready).status, 'pass');
});
test('missing answers never produce a pass', () => {
  const result = checkCompatibility({});
  assert.equal(result.status, 'unknown');
  assert(result.rows.every(row => row.level === 'unknown'));
});
test('unsupported selections take priority over missing answers', () => {
  for (const field of ['game', 'os']) assert.equal(checkCompatibility({ [field]: 'other' }).status, 'block');
  assert.equal(checkCompatibility({ ...ready, gpu: 'legacy' }).status, 'block');
  assert.equal(checkCompatibility({ ...ready, driver: 'no' }).status, 'block');
});
test('Linux AppImage requires both glibc and AVX2', () => {
  const linux = { ...ready, os: 'linux-appimage', glibc: 'yes', avx2: 'yes' };
  assert.equal(checkCompatibility(linux).status, 'pass');
  for (const field of ['glibc', 'avx2']) {
    assert.equal(checkCompatibility({ ...linux, [field]: 'no' }).status, 'block');
    assert.equal(checkCompatibility({ ...linux, [field]: 'unknown' }).status, 'unknown');
  }
});
test('AVX2 is not required for Windows or Linux source builds', () => {
  assert.equal(checkCompatibility({ ...ready, avx2: 'no', glibc: 'no' }).status, 'pass');
  assert.equal(checkCompatibility({ ...ready, os: 'linux-source', glibc: 'yes', avx2: 'no' }).status, 'pass');
});
test('AMD, Intel, and Deck carry known-problem notices', () => {
  for (const gpu of ['amd', 'intel', 'deck']) assert.equal(checkCompatibility({ ...ready, gpu }).status, 'warning');
});
test('below-target memory and space warn, exact thresholds pass', () => {
  for (const [field, value] of [['ram', 15.9], ['vram', 7.9], ['disk', 59.9]]) {
    assert.equal(checkCompatibility({ ...ready, [field]: value }).status, 'warning');
  }
});
test('invalid numbers and shared-memory unknowns cannot count as passing', () => {
  for (const value of ['', ' ', 'oops', 'Infinity', '-1', '0', null, undefined]) {
    assert.equal(checkCompatibility({ ...ready, vram: value }).status, 'unknown');
  }
});
