import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

export function sectionDigest(markdown, heading) {
  const lines = markdown.replaceAll('\r\n', '\n').split('\n');
  const start = lines.indexOf(heading);
  if (start < 0) throw new Error(`Missing compatibility source section: ${heading}`);
  const level = heading.match(/^#+/)[0].length;
  let end = start + 1;
  for (; end < lines.length; end++) {
    const next = lines[end].match(/^(#+) /);
    if (next && next[1].length <= level) break;
  }
  return createHash('sha256').update(lines.slice(start, end).join('\n').trim()).digest('hex');
}

export function assertReviewedSources(markdown, review) {
  for (const [heading, digest] of Object.entries(review.sections)) {
    if (sectionDigest(markdown, heading) !== digest) {
      throw new Error(`README ${heading} changed since compatibility review (${review.reviewedOn}). Review the calculator's rules, labels, and advice against readme.md, then update website/compatibility-review.json. See website/README.md.`);
    }
  }
}

export async function verifyCompatibilitySources(root) {
  const [markdown, data] = await Promise.all([
    readFile(path.join(root, 'readme.md'), 'utf8'),
    readFile(path.join(root, 'website/compatibility-review.json'), 'utf8'),
  ]);
  assertReviewedSources(markdown, JSON.parse(data));
}
