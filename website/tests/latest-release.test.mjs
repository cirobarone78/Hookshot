import test from 'node:test';
import assert from 'node:assert/strict';
import { getLatestRelease } from '../src/lib/latest-release.mjs';

const stable = { tag_name: 'v2.0.14', draft: false, prerelease: false };
const response = (data, ok = true) => async () => ({ ok, json: async () => data });
test('shows the version returned by GitHub and links only to upstream release notes', async () => {
  const release = await getLatestRelease(response({ ...stable, html_url: 'https://example.com' }));
  assert.deepEqual(release, { version: 'v2.0.14', url: 'https://github.com/NotRexed/Hookshot/releases/tag/v2.0.14' });
});
test('never labels a draft, prerelease, or malformed response as stable', async () => {
  for (const data of [null, {}, { ...stable, tag_name: '' }, { ...stable, prerelease: true }, { ...stable, draft: true }]) {
    assert.equal(await getLatestRelease(response(data)), null);
  }
});
test('keeps the fallback link on rate limiting, bad JSON, and network failure', async () => {
  assert.equal(await getLatestRelease(response(stable, false)), null);
  assert.equal(await getLatestRelease(async () => { throw Error('offline'); }), null);
  assert.equal(await getLatestRelease(async () => ({ ok: true, json: async () => { throw Error('invalid JSON'); } })), null);
});
