# Local validation — November 11, 2026

## Readability and hero follow-up

Increased document body text to 1.0625rem and enlarged the smaller navigation, button and homepage text.
Added “Progress & updates” beside “Install Hookshot” in the hero and moved its summary above the setup content.
The fork preview build and all four website test files passed; generated HTML confirms the hero link targets
`/Hookshot/progress/`. Browser access was attempted again but the host remains unavailable, so rendered layout,
keyboard and light/dark review remain outstanding.

## Search-button follow-up

Added a shared-header “Search for your problem” link, including a full-width mobile row. It targets the search
input, selects reported problems, clears restrictive filters and focuses the field, including repeated clicks
on the same fragment. Default and fork-preview build/check passed with 14 pages and 691/692 local links/assets
respectively. All four existing website test files passed; generated HTML checks found the header link on all
14 pages and its input anchor on the progress page. Browser visual and interaction review remains unavailable.

Implementation is applied locally on `docs/starlight-preview`, based on
`ce09826e2f7b0d204ecf8971ff4f94e0510eb41f`, the existing documentation PR #2083 branch.
These checks were performed before committing or pushing. The user subsequently authorized a commit and push to
the existing fork branch for PR #2083. Website deployment, public feed hosting and maintainer contact remain separate.

## Passed

- Default upstream build/check: 14 pages, 677 local links/assets, local anchors, edit targets, Pagefind output,
  original logo bytes and compatibility source guard.
- Fork preview build/check with the optional local live-feed endpoint: 14 pages, 678 local links/assets and the
  same checks. Deployment remains under `/Hookshot/`.
- All four website test files passed. Running each file directly verified 28 individual tests: 13 existing and
  15 progress tests. The runner's grouped output reports four files; it is not a count of individual assertions.
- Progress tests cover exact report versions, preview/older/unknown exclusions, status meanings, curation expiry,
  combined search filters, date-based overview counts, unsafe links, public-only repository enforcement,
  cursor pagination, incomplete-fetch rejection, concurrent caching, background refresh, API backoff and atomic snapshots.
- TypeScript syntax/stripping check for the browser controller passed. Astro compiled the client bundle.
- Real public GitHub collection completed beyond the 1,000-item boundary using GitHub's cursor links and verified
  canonical repository ID. The final authored snapshot contained 2,480 items at `2026-11-11T20:52:42.401Z` and
  identified `v2.1.0` as the latest stable release. These are dated observations, not permanent project statistics.
- Three source-reviewed summaries are included, with exact source update timestamps and public evidence links.
  No workaround or underlying cause is claimed as verified.
- Local HTTP smoke checks: feed returned 200 with the configured exact allowed origin, POST returned 405,
  unrelated origins received no permission header, three summaries were present, and report bodies/account fields
  were absent. The preview served the page with all five player-facing modules.
- `git diff --check` passed. Generated feeds, site output, dependencies and game assets are outside the source diff.

## Environment and limits

The recorded original checkout was absent. The PR branch was cloned into the game workspace's `hookshot-docs/`
directory; it is a separate Git repository containing public source only. The earlier prepared Libertinus patch
matched this exact base and was applied locally, with its original font files and license notice.

The system Node executable could not load `libsimdjson.so.34`. Validation used official Node 22.23.4 extracted
under `/tmp` after verifying its SHA-256 against the official distribution manifest. Dependencies came from the
existing lockfile; no dependency upgrade was made.

Building directly on the workspace's NTFS filesystem produced an Astro virtual-module resolution error.
The same source and pinned dependencies built successfully in the isolated `/tmp/hookshot-progress-check` copy.
Use a Linux filesystem for local validation in this environment. No project dependency or toolbar configuration
was altered to hide the error.

The browser-access host was unavailable. Rendered desktop/mobile layout, light/dark themes, keyboard navigation,
in-browser search interaction and screenshots are **not verified**. HTTP, source and unit checks do not replace
that review. Full TypeScript type checking was not run; TypeScript is not a pinned project dependency.

No game build, runtime experiment, launch, installation or setting change was performed. The game-free runtime
suite was not run for these website-only changes.

Public continuous updates are not activated. GitHub Pages can publish a snapshot; operating the optional server
or scheduling snapshot deployments is a separate hosting step. The local preview demonstrates the configured
endpoint but is not a public deployment. Scheduled fetch times are approximate, not real-time guarantees.
