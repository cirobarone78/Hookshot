import { readFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { siteConfig } from '../site.config.mjs';
import { contentSources } from '../content-sources.mjs';
import { verifyCompatibilitySources } from './verify-compatibility-sources.mjs';

const site = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dist = path.join(site, 'dist');
await verifyCompatibilitySources(path.join(site, '..'));
const origin = siteConfig.origin;
const base = siteConfig.base;
const bug = 'https://github.com/NotRexed/Hookshot/issues/new/choose';
const files = [];
async function walk(dir) {
  for (const item of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, item.name);
    if (item.isDirectory()) await walk(full);
    else if (item.name.endsWith('.html')) files.push(full);
  }
}
await walk(dist);
const publishedRoutes = new Set([...contentSources.values(), '', 'about', 'antivirus', 'compatibility', 'progress', '404.html']);
for (const file of files) {
  const route = path.relative(dist, file).replaceAll(path.sep, '/').replace(/\/?index\.html$/, '');
  assert(publishedRoutes.has(route), `Unexpected published page: ${route}`);
}
const ids = new Map();
for (const file of files) {
  const html = await readFile(file, 'utf8');
  ids.set(file, new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1])));
}
const errors = [];
let links = 0;
for (const file of files) {
  const html = await readFile(file, 'utf8');
  const route = base + path.relative(dist, file).replaceAll(path.sep, '/').replace(/index\.html$/, '');
  assert(html.includes(`href="${bug}"`), `Missing Report a bug link: ${route}`);
  assert(/<h1\b/.test(html), `Missing page heading: ${route}`);
  for (const [, editUrl] of html.matchAll(/href="(https:\/\/github\.com\/[^\"]+\/edit\/[^\"]+)"/g)) {
    assert(editUrl.startsWith(siteConfig.editBase), `Wrong edit repository: ${editUrl}`);
    const source = editUrl.slice(siteConfig.editBase.length);
    await stat(path.join(site, '..', source));
  }
  for (const match of html.matchAll(/<(a|img|script|link)\b[^>]*?\b(?:href|src)="([^"]+)"/g)) {
    const [, tag, raw] = match;
    if (/^(?:data:|mailto:|tel:|javascript:)/.test(raw)) continue;
    const url = new URL(raw.replaceAll('&amp;', '&'), origin + route);
    if (url.origin !== origin) continue;
    // Astro emits a /404/ canonical URL but GitHub Pages serves the file as /404.html.
    if (tag === 'link' && file.endsWith('/404.html') && url.pathname === base + '404/') continue;
    if (!url.pathname.startsWith(base)) {
      errors.push(`${route}: URL escapes project base: ${raw}`);
      continue;
    }
    let target = path.join(dist, decodeURIComponent(url.pathname.slice(base.length)));
    try {
      if ((await stat(target)).isDirectory()) target = path.join(target, 'index.html');
      await stat(target);
      links++;
      if (tag === 'a' && url.hash && ids.has(target) && !ids.get(target).has(decodeURIComponent(url.hash.slice(1)))) {
        errors.push(`${route}: missing anchor: ${raw}`);
      }
    } catch { errors.push(`${route}: missing target: ${raw}`); }
  }
}
const original = await readFile(path.join(site, '../assets/hookshot.png'));
assert(original.equals(await readFile(path.join(dist, 'assets/hookshot.png'))), 'Original README logo changed');
assert((await readFile(path.join(dist, 'index.html'), 'utf8')).includes('class="adventure-hero"'), 'Custom landing page missing');
assert((await readdir(path.join(dist, 'pagefind'))).some((f) => f === 'pagefind.js'), 'Search index missing');
if (errors.length) {
  console.error([...new Set(errors)].join('\n'));
  process.exitCode = 1;
} else {
  console.log(`PASS: ${files.length} pages, ${links} local links/assets, all local anchors, project base path, Report a bug links, search index, and unchanged original logo.`);
}
