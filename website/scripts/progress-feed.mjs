import { readFile, mkdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { REPOSITORY, REFRESH_MS, normalizeItem, validateCuration, validateFeed } from '../src/lib/progress.mjs';

const API = `https://api.github.com/repos/${REPOSITORY}`;
export const snapshotPath = fileURLToPath(new URL('../public/progress-feed.json', import.meta.url));
export const curationPath = new URL('../progress-curation.json', import.meta.url);

export class GitHubError extends Error {
  constructor(response, now) {
    super(`GitHub progress request failed (${response.status}).`);
    const retry = response.headers.get('retry-after');
    const reset = Number(response.headers.get('x-ratelimit-reset')) * 1000;
    const retryTime = retry ? (/^\d+$/.test(retry) ? now + Number(retry) * 1000 : Date.parse(retry)) : 0;
    this.retryAt = Math.max(now + REFRESH_MS, retryTime || 0,
      response.headers.get('x-ratelimit-remaining') === '0' ? reset || 0 : 0);
  }
}

export async function collectFeed({ fetcher = fetch, token = '', curation = {}, now = Date.now(), maxPages = 100 } = {}) {
  validateCuration(curation);
  const closedSince = new Date(now - 90 * 86400000).toISOString();
  const headers = { Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'Hookshot-docs-progress' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const repositoryResponse = await fetcher(API, { headers, signal: AbortSignal.timeout(15000), redirect: 'error' });
  if (!repositoryResponse.ok) throw new GitHubError(repositoryResponse, Date.now());
  const repository = await repositoryResponse.json();
  if (repository.private !== false || !Number.isSafeInteger(repository.id) || repository.id <= 0 ||
      repository.full_name?.toLowerCase() !== REPOSITORY.toLowerCase()) throw new Error('Progress source must be the expected public repository.');
  async function page(endpoint, query, next) {
    const url = new URL(next || `${API}/${endpoint}`);
    if (!next) url.search = new URLSearchParams(query).toString();
    // Only follow GitHub's same-endpoint pagination links, never forward credentials elsewhere.
    if (url.origin !== 'https://api.github.com' || ![`/repos/${REPOSITORY}/${endpoint}`, `/repositories/${repository.id}/${endpoint}`].includes(url.pathname) || url.username || url.password) {
      throw new Error('Unsafe GitHub pagination link.');
    }
    const response = await fetcher(url.href, { headers, signal: AbortSignal.timeout(15000), redirect: 'error' });
    if (!response.ok) {
      const error = new GitHubError(response, Date.now());
      error.message += ` Endpoint: ${endpoint}, state: ${query.state || 'published'}.`;
      throw error;
    }
    const data = await response.json();
    if (!Array.isArray(data)) throw new Error('Unexpected GitHub response.');
    const link = response.headers.get('link') || '';
    const nextPage = link.split(',').map(part => part.match(/<([^>]+)>;\s*rel="next"/)).find(Boolean)?.[1] || null;
    return { data, next: nextPage };
  }
  const latestResponse = await fetcher(`${API}/releases/latest`, { headers, signal: AbortSignal.timeout(15000), redirect: 'error' });
  if (!latestResponse.ok && latestResponse.status !== 404) throw new GitHubError(latestResponse, Date.now());
  const latest = latestResponse.ok ? await latestResponse.json() : null;
  if (latest && (latest.draft !== false || latest.prerelease !== false)) throw new Error('Invalid latest stable release.');
  const latestItem = latest ? normalizeItem(latest, 'release', curation) : null;
  if (latest && !latestItem) throw new Error('Invalid latest stable release.');
  async function list(endpoint, state) {
    const result = [];
    let next;
    const visited = new Set();
    for (let n = 1; n <= maxPages; n++) {
      const batch = await page(endpoint, { state, sort: 'updated', direction: 'desc', per_page: '100' }, next);
      const { data } = batch;
      if (data.some(i => !Number.isFinite(Date.parse(i.updated_at)))) throw new Error('Missing GitHub update date.');
      result.push(...data.filter(i => state === 'open' || i.updated_at >= closedSince));
      if (!batch.next || !data.length || (state === 'closed' && data.at(-1).updated_at < closedSince)) return result;
      if (visited.has(batch.next)) throw new Error('Repeated GitHub pagination cursor.');
      visited.add(batch.next);
      next = batch.next;
    }
    throw new Error('Progress pagination limit reached; previous snapshot retained.');
  }
  // Sequential pagination limits burst traffic. Do not publish any part until every list succeeds.
  const items = new Map();
  if (latestItem) items.set(latestItem.id, latestItem);
  for (const [endpoint, kind] of [['issues', 'issue'], ['pulls', 'pull']]) {
    for (const state of ['closed', 'open']) {
      for (const raw of await list(endpoint, state)) {
        if (kind === 'issue' && raw.pull_request) continue;
        const item = normalizeItem(raw, kind, curation);
        items.set(item.id, item);
      }
    }
  }
  // Token access must not leak draft releases. Walk pages until 20 published releases are found.
  let releases = 0;
  let nextRelease;
  for (let n = 1; n <= maxPages; n++) {
    const batch = await page('releases', { per_page: '100' }, nextRelease);
    const { data } = batch;
    for (const raw of data) {
      if (raw.draft !== false) continue;
      const item = normalizeItem(raw, 'release', curation);
      if (item) { items.set(item.id, item); releases++; }
      if (releases === 20) break;
    }
    if (releases === 20 || !batch.next) break;
    nextRelease = batch.next;
    if (n === maxPages) throw new Error('Release pagination limit reached.');
  }
  return validateFeed({ version: 1, repository: REPOSITORY, collectionStartedAt: new Date(now).toISOString(),
    generatedAt: new Date().toISOString(), closedSince, warning: '',
    stableRelease: latestItem ? { tag: latest.tag_name, url: latestItem.url, publishedAt: latest.published_at } : null,
    items: [...items.values()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt) || a.id.localeCompare(b.id)) });
}

export async function saveSnapshot(feed, filename = snapshotPath) {
  validateFeed(feed);
  await mkdir(path.dirname(filename), { recursive: true });
  const temporary = `${filename}.${process.pid}.tmp`;
  await writeFile(temporary, JSON.stringify(feed) + '\n');
  await rename(temporary, filename);
}

export async function readSnapshot(filename = snapshotPath) {
  try { return validateFeed(JSON.parse(await readFile(filename, 'utf8'))); }
  catch { return null; }
}

export function createFeedCache({ collect, save = async () => {}, initial = null, now = Date.now } = {}) {
  let current = initial;
  let nextAttempt = initial ? Date.parse(initial.generatedAt) + REFRESH_MS : 0;
  let pending;
  let failed = false;
  return async function getFeed({ wait = true } = {}) {
    if (now() >= nextAttempt && !pending) {
      pending = (async () => {
        try {
          const fresh = validateFeed(await collect());
          await save(fresh);
          current = fresh;
          failed = false;
          nextAttempt = now() + REFRESH_MS;
        } catch (error) {
          failed = true;
          nextAttempt = Math.max(now() + REFRESH_MS, error.retryAt || 0);
        } finally { pending = null; }
      })();
    }
    if (pending && wait) await pending;
    if (!current) return null;
    return { ...current, warning: failed ? 'Could not update from GitHub. Showing the last complete snapshot.' :
      pending ? 'Checking GitHub for updates. Showing the last complete snapshot.' : current.warning };
  };
}
