# Hookshot documentation site

An optional Astro Starlight site using the original `assets/hookshot.png` logo. The game build does not depend on Node
or this site. Adopting the website, its dependencies, and hosting remains the upstream maintainer's decision.

## Typography

The site uses the main UI's bundled fallback set: Libertinus Sans Regular (400) for body text, Sans Bold (700) for
emphasis, and Serif Semibold (600) for headings. The unchanged version 7.051 TTF files are copied from
`third_party/fonts/libertinus/` into `src/assets/fonts/libertinus/`; CSS-relative imports let Astro process the font
URLs for the configured site base. No external font service is needed. Code retains Starlight's monospace font.

The game UI's preferred fonts come from the player's game files and are not included in this website. Keep the
Libertinus copyright and SIL Open Font License with the font assets; `public/fonts/libertinus/OFL.txt` publishes that
notice with the site. When updating these copies, use the repository's bundled font version and retain its notice.

## Build and check

Use Node 22.23.4 or newer. From `website/`:

```sh
npm ci
npm run build
npm run check
npm run preview
```

Open the printed local URL with `/Hookshot/`. For live editing use `npm run dev`; restart it when imported Markdown
changes. The checks validate published routes, local links and anchors, edit-link targets, logo bytes, search output,
compatibility source review, and the calculator and release-fetch behavior.

## Hosting and edit links

`site.config.mjs` is shared by Astro, content preparation, and validation. Defaults target upstream:

| Variable | Default |
|---|---|
| `DOCS_SITE_URL` | `https://notrexed.github.io` |
| `DOCS_SOURCE_REPOSITORY` | `NotRexed/Hookshot` |
| `DOCS_SOURCE_BRANCH` | `main` |

The project path is `/Hookshot/`. Set the same environment for build and check when overriding hosting.
Handwritten pages inherit the configured edit base; imported pages link to their original Markdown source.
These defaults do not enable an upstream site or change Pages settings.

For bibigurl-yum's preview, `npm run build:preview` builds and checks with the fork's host and
`docs/starlight-preview` edit branch. The `Refresh documentation progress` Action publishes **only `dist/`**
through GitHub Pages artifacts. The preview is at https://bibigurl-yum.github.io/Hookshot/.
The older `preview/starlight-pages` branch is retained as a rollback snapshot; pushing it no longer deploys
while Pages uses GitHub Actions.

## What gets published

`content-sources.mjs` explicitly lists eight imported pages: five short player guides, the existing save guide,
the README as the reference manual, and CONTRIBUTING.md. Home, about, antivirus, and compatibility pages are
written in `src/content/docs/`. Internal design notes, development docs, workflow notes, and pipeline references
remain on GitHub and are linked there. Adding a file to `docs/` does not publish it automatically.

The manual is generated from `readme.md`, not maintained as another copy. Player guides link to its sections
rather than repeat requirement tables, menu settings, paths, or update procedures. Edit imported content in its
original location; generated pages and copied assets are ignored.

## Compatibility source review

The calculator translates selected README requirements into checks. `compatibility-review.json` records SHA-256
hashes of the reviewed **Project status** and **What you need** sections. Both build preparation and `npm run check`
stop if either section changes. A regression test verifies that requirement and GPU-status edits trigger the guard.
This catches changes in the checked-out source at build time; it does not monitor upstream in the background.

When the guard fails:

1. Read the changed README sections and review `src/lib/compatibility.mjs`, its tests, and the labels in
   `src/components/CompatibilityChecker.astro`. Adjust the checks and advice as needed.
2. Update the review date on the compatibility page and in `compatibility-review.json`.
3. After reviewing, compute the new section hashes from the repository root:

   ```sh
   node --input-type=module -e 'import {readFile} from "node:fs/promises"; import {sectionDigest} from "./website/scripts/verify-compatibility-sources.mjs"; const text = await readFile("readme.md", "utf8"); for (const heading of ["## Project status", "### What you need"]) console.log(heading, sectionDigest(text, heading));'
   ```

4. Put the reviewed hashes in the JSON file, then build and check. Do not refresh hashes without reviewing the rules.

Common-issue entries are historical examples with direct links to responses and trackers. They do not claim a
current open/fixed status. Review the source before changing an example. Antivirus signing information is explicitly
dated. The release badge fetches GitHub's latest stable version on page load and retains a permanent release link
if the API is unavailable or rate-limited. No game files or calculator answers are uploaded.

## Progress overview

The **Progress & updates** page searches upstream reports, feature requests, proposed changes and releases.
Its **Current version watch** groups open reports that explicitly name the latest stable version. It does not
infer affected versions, confirmed bugs, severity or released fixes from activity counts or merge dates.
See [PROGRESS.md](PROGRESS.md) for the implementation plan, editorial review rules, coverage and hosting options.

Run `npm run progress:sync` before a build to include a current static snapshot. Normal builds remain offline.
`npm run progress:serve` provides an optional shared feed with a five-minute cache. GitHub Pages can serve the
snapshot but cannot run this server; automatic public updates require hosting or scheduled deployment configured
separately. The fork uses the scheduled workflow described below; the scripts alone do not enable hosting.

## Maintenance and deployment

Astro, Starlight, and their dependencies are pinned in the lockfile. Use `npm ci`; review dependency upgrades and
run the checks before publication. Node is needed for documentation tooling only. There is no new dependency-update workflow.

`.github/workflows/docs-progress.yml` refreshes the fork preview at minutes 7, 22, 37 and 52 each hour,
and offers **Actions → Refresh documentation progress → Run workflow → main** for a manual refresh.
It collects a complete snapshot, builds and checks the documentation, then publishes only `website/dist`.
A collection, build or validation failure prevents deployment, leaving the last successful site available.
Only the deployment job receives Pages/OIDC write permissions; no personal token is needed.

GitHub runs schedules only from the default branch, so the workflow must also be present on the fork's `main`.
It checks out `docs/starlight-preview` for the actual website source. Keep its default-branch copy synchronized
when changing the workflow in this PR. Scheduled runs can be delayed; the page's “checked” timestamp is the
source of truth. GitHub may disable public-repository schedules after 60 days without repository activity;
re-enable the workflow in Actions if that happens.

Activation requires Pages source **GitHub Actions** and allowing `main` in the `github-pages` environment's
branch policy. The fork is enabled explicitly; other repositories must set the Actions repository variable
`DOCS_PROGRESS_ENABLED=true`. Every run must originate from the default branch. It has no PR-triggered deployment.

After this PR is approved and merged into `NotRexed/Hookshot:main`, maintainers can activate the same Action:

1. Set Pages source to **GitHub Actions** and allow `main` in the `github-pages` environment.
2. Set the Actions repository variable `DOCS_PROGRESS_ENABLED` to `true`.
3. Run **Refresh documentation progress** manually from `main` and verify the site and feed timestamp.

Outside the preview fork, the workflow builds the repository's default branch and derives the site URL and edit
links from that repository. `DOCS_SITE_URL` can override the hosting origin for an adopted custom domain;
`/Hookshot/` remains the configured base path. No personal access token is required. Merging the workflow alone
does not opt upstream into publishing. Disable the workflow or remove its opt-in variable to stop upstream refreshes.

The browser polls the published feed every five minutes while visible. The scheduled collection interval is
15 minutes, plus build/deployment and GitHub queue time; this is periodic updating, not real-time delivery.
Version matching, report groups and activity counts refresh automatically. Curated impact summaries still need
human source review and expire when the linked report changes.

For rollback, disable the refresh workflow first, then switch Pages back to **Deploy from a branch** using
`preview/starlight-pages` at `/`. This restores the retained static snapshot; do not confuse it with fresh data.
See [GitHub's custom Pages workflow instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
and [schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Verification limits

Browser access was unavailable in the authoring environment. Desktop/mobile visual review, keyboard interaction,
search, and light/dark-mode screenshots are still outstanding. Build, source-guard, rule, and link checks run locally.
