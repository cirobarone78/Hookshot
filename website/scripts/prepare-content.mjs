import { readFile, writeFile, mkdir, rm, copyFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { siteConfig } from '../site.config.mjs';
import { contentSources } from '../content-sources.mjs';
import { verifyCompatibilitySources } from './verify-compatibility-sources.mjs';

const site = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const root = path.resolve(site, '..');
const out = path.join(site, 'src/content/docs/generated');
await verifyCompatibilitySources(root);
const base = siteConfig.base;
const pages = new Map(contentSources);
pages.set('docs/README.md', '');

const assetDir = path.join(site, 'public/assets');
await mkdir(assetDir, { recursive: true });
await copyFile(path.join(root, 'assets/hookshot.png'), path.join(assetDir, 'hookshot.png'));
const publicAssets = new Set(['assets/hookshot.png']);
function urlFor(value, source) {
  if (!value || /^(?:[a-z]+:|\/\/|#)/i.test(value)) return value;
  const hashAt = value.indexOf('#');
  const fragment = hashAt < 0 ? '' : value.slice(hashAt);
  const pathname = hashAt < 0 ? value : value.slice(0, hashAt);
  const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(source), pathname));
  if (pages.has(resolved)) return base + (pages.get(resolved) ? `${pages.get(resolved)}/` : '') + fragment;
  if (publicAssets.has(resolved)) return base + resolved + fragment;
  return `https://github.com/NotRexed/Hookshot/blob/main/${resolved}${fragment}`;
}
await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });
for (const [source, slug] of pages) {
  if (!slug) continue;
  let text = await readFile(path.join(root, source), 'utf8');
  let title = text.match(/^# (.+)$/m)?.[1] || source;
  if (source === 'readme.md') title = 'Complete reference manual';
  if (source === 'docs/development.md') title = 'Development guide';
  if (source === 'docs/design.md') title = 'Architecture and design';
  text = text.replace(/^# .+\n/m, '');
  // Keep code samples untouched; only rewrite actual prose links and HTML attributes.
  const chunks = text.split(/(^```[^\n]*\n[\s\S]*?^```\s*$)/gm);
  text = chunks.map((chunk) => {
    if (chunk.startsWith('```')) return chunk;
    return chunk.replace(/(!?\[[^\]]*\]\()([^\s)]+)(\))/g, (_, before, url, after) => before + urlFor(url, source) + after)
      .replace(/(\b(?:src|href)=")(?!https?:|#)([^"]+)(")/g, (_, before, url, after) => before + urlFor(url, source) + after);
  }).join('');
  const front = [
    '---', `title: ${JSON.stringify(title)}`, `slug: ${JSON.stringify(slug)}`,
    `editUrl: ${JSON.stringify(siteConfig.editBase + source)}`,
    '---', '',
  ].join('\n');
  await writeFile(path.join(out, slug.replaceAll('/', '--') + '.md'), front + text);
}
console.log(`Prepared ${pages.size - 1} documentation pages; original README logo copied unchanged.`);
