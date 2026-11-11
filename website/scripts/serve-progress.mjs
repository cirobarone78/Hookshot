import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { siteConfig } from '../site.config.mjs';
import { collectFeed, createFeedCache, readSnapshot, saveSnapshot, curationPath } from './progress-feed.mjs';

const origin = process.env.PROGRESS_ALLOWED_ORIGIN || siteConfig.origin;
if (new URL(origin).origin !== origin) throw new Error('PROGRESS_ALLOWED_ORIGIN must be an exact origin.');
const getFeed = createFeedCache({ initial: await readSnapshot(), save: saveSnapshot,
  collect: async () => collectFeed({ token: process.env.GITHUB_TOKEN || '', curation: JSON.parse(await readFile(curationPath, 'utf8')) }) });
const server = createServer(async (request, response) => {
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.setHeader('Vary', 'Origin');
  if (request.headers.origin === origin) response.setHeader('Access-Control-Allow-Origin', origin);
  if (!['GET', 'HEAD'].includes(request.method)) {
    response.writeHead(405, { Allow: 'GET, HEAD' }).end(); return;
  }
  if (request.url !== `${siteConfig.base}progress-feed.json`) { response.writeHead(404).end(); return; }
  const feed = await getFeed({ wait: false });
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.setHeader('Cache-Control', 'no-store');
  if (!feed) response.setHeader('Retry-After', '300');
  response.writeHead(feed ? 200 : 503);
  response.end(request.method === 'HEAD' ? undefined : JSON.stringify(feed || { error: 'Progress data is temporarily unavailable.' }));
});
const host = process.env.PROGRESS_HOST || '127.0.0.1';
const port = Number(process.env.PROGRESS_PORT || 4322);
server.listen(port, host, () => console.log(`Progress feed: http://${host}:${port}${siteConfig.base}progress-feed.json`));
void getFeed({ wait: false });
