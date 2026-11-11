import { readFile } from 'node:fs/promises';
import { collectFeed, saveSnapshot, curationPath } from './progress-feed.mjs';

const curation = JSON.parse(await readFile(curationPath, 'utf8'));
const feed = await collectFeed({ token: process.env.GITHUB_TOKEN || '', curation });
await saveSnapshot(feed);
console.log(`Saved ${feed.items.length} public progress items, checked ${feed.generatedAt}.`);
