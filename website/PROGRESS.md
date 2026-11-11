# Progress page implementation and operation

## Plan and scope

Extend the existing documentation PR #2083 on `docs/starlight-preview`. The recovered base is
`ce09826e2f7b0d204ecf8971ff4f94e0510eb41f`; the previously prepared Libertinus font patch is applied alongside
this feature. The user authorized committing and pushing this documentation update to the existing fork branch
after local validation. The fork preview now has a scheduled Pages workflow; upstream hosting remains a separate decision. No game changes or game builds.

1. Add `/Hookshot/progress/`, sidebar and home links, accessible search, views, filters and progressive results.
2. Normalize public upstream issues, pull requests and releases. Include all open items and closed items updated
   within 90 days, plus the latest 20 published releases and the latest stable release. State coverage and collection times explicitly.
3. Keep reported, proposed, draft, merged, closed, stable release and preview release states distinct. Never infer
   release inclusion from merge dates or mark every closed issue fixed. Only an explicit `in progress` label
   means work is underway; assignment, comments and draft PRs do not prove ongoing activity.
4. Support reviewed plain-language titles, summaries, platforms and workarounds in `progress-curation.json`.
   Require source links, review date and the exact reviewed GitHub update timestamp; hide the curation when the
   source changes, until someone reviews it again. Never generate advice from unreviewed issue bodies.
5. Provide a dependency-free collector, atomic snapshot writer and optional cached feed server. Refresh no more
   than every five minutes; keep the last complete snapshot on errors and respect GitHub retry/reset headers.
6. Validate normalization, pagination, failures, hostile data, curation expiry, cache concurrency, searching and
   filtering. Run site build/check for default and preview hosting. Inspect desktop/mobile, keyboard, search,
   light/dark and unavailable/stale states locally when browser access is available.
7. Add separate modules for development totals, current-version report groups, reviewed serious issues, searchable
   work and help links. Count recent merges by `merged_at` and releases by `published_at`, not comment activity.
   Match versions only in the issue forms' Hookshot/Builder version fields; exclude questions and known duplicates
   from the current-version watch. No language model, inferred diagnosis, release-date guesses or player-prevalence claims.

## Feed and hosting

`npm run progress:sync` writes ignored `public/progress-feed.json`. Run it before building a static snapshot.
Normal builds never fetch GitHub; without a snapshot the page honestly reports that progress data is unavailable.
The page's explanatory content is indexed by Pagefind; the activity search searches the downloaded feed itself.

For continuous updates, run `npm run progress:serve`. It serves only `/Hookshot/progress-feed.json` on
`127.0.0.1:4322` by default. A host can reverse-proxy this route alongside the static site. Alternatively build
with `DOCS_PROGRESS_FEED_URL=https://your-feed-host/Hookshot/progress-feed.json` and set `PROGRESS_ALLOWED_ORIGIN`
on the server to the exact documentation origin. Local HTTP is permitted only on localhost/127.0.0.1 for review.
`PROGRESS_HOST` and `PROGRESS_PORT` configure the listener. HTTPS termination belongs to the host.

The server caches a complete feed, refreshes on demand after five minutes, coalesces simultaneous refreshes and
persists the last successful snapshot. Slow refreshes run in the background so the previous snapshot remains
immediately available. On refresh failure it serves the last complete data with a warning; without data it returns
503 and a retry hint while collecting. `GITHUB_TOKEN` is optional, server-only, read-only and never sent to browsers or written to
the snapshot. For busy repositories authentication may be needed to stay within GitHub's API quota.

GitHub Pages cannot run this server. Its static snapshot changes only when a refreshed artifact is deployed.
The fork uses `.github/workflows/docs-progress.yml` to collect, build/check and publish every 15 minutes.
The workflow also supports manual runs; see README.md for default-branch activation, permissions and rollback.
A failed collection or build does not replace the last successful deployment. The fork is enabled; other repositories require an explicit
`DOCS_PROGRESS_ENABLED=true` opt-in, so merging the PR alone does not enable upstream publication.
The same workflow supports upstream adoption on `main`; see README.md for the activation steps.
The browser checks the feed every five minutes while visible; timestamps describe the data, not just a successful
HTTP request. This is periodic refresh, not a promise of real-time delivery. A restarted server can use an older
saved snapshot until GitHub is reachable. Pagination limits fail the entire update rather than truncate silently.

## Editorial maintenance

Keys in `progress-curation.json` use `issue:123`, `pull:456` or `release:789` (the release ID, not tag).
Each entry needs `title`, `summary`, `reviewedAt` (ISO date), `sourceUpdatedAt` (exact API timestamp), and `sources`
(public URLs under `https://github.com/NotRexed/Hookshot/`). Optional `platforms` contains `Windows`, `Linux`,
`Steam Deck`, or `Other`; optional `area` is `Graphics`, `Performance`, `Controls`, `Audio`, `Setup`, or
`Documentation`, `Crashes or startup`, or `Sound, controls or saves`; optional `workaround` is plain text.
Optional `impact` is `Crashes`, `Save integrity`, `Cannot start`, or `Blocked progression`; it enables the reviewed
serious-issue highlight only when the report explicitly matches the current stable version. Do not add speculative fixes, dates or progress percentages.
Review timestamps appear with curated advice. If a source's update timestamp changes the entry falls back to
the original title and neutral status explanation. The collector rejects malformed editorial entries.

Only metadata, labels, selected report-form version/category values and reviewed prose are published. Issue/PR bodies, comments, attachments, author accounts
and downloaded assets are excluded. Text is rendered with textContent, never interpreted as HTML/Markdown.
Links are constructed from the fixed public upstream repository and validated again in the browser.

## Modules for future updates

| Module | Source | Purpose |
|---|---|---|
| Development at a glance | `src/components/ProgressOverview.astro`, `src/lib/progress-overview.mjs` | Explain open reports, review proposals, recent merges and stable releases. |
| Current version watch | `src/lib/progress-watch.mjs` | Match exact report versions, group reported areas and separate other/unknown versions. |
| Searchable work | `src/components/ProgressBoard.astro`, `src/lib/progress-board.ts`, `src/lib/progress.mjs` | Search, filters, progressive results, freshness and plain-language status explanations. |
| Reviewed highlights | `progress-curation.json` | Sourced summaries, platform tags and serious reported impacts, invalidated by source changes. |
| Help and status guide | `src/content/docs/progress.mdx` | Explain what the data means and link players to practical help. |
| Shared feed | `scripts/progress-feed.mjs`, `scripts/serve-progress.mjs`, `scripts/sync-progress.mjs` | Collect public data, follow verified cursor links, cache and retain complete snapshots. |

The overview is descriptive, not a roadmap commitment. No module treats counts as unique bugs, developer speed,
completion percentages or affected-player totals. The current-version watch intentionally misses unstructured
reports and reports updated only in comments; source links remain essential. Editorial summaries are reviewed
against reports, not claims of independent reproduction.

See [PROGRESS-VALIDATION.md](PROGRESS-VALIDATION.md) for the local checks and remaining review limits.

## Acceptance

- Existing source guards, generated-page boundaries, font notices and Pagefind search remain intact.
- All-open pagination and bounded recent history are explicit; an unavailable feed is not an empty tracker.
- Merged PRs never become releases by inference; a closed report does not promise a fix.
- Search, filters and clear/reset controls work with keyboard and narrow screens. Status is conveyed by text.
- Successful data survives a failed refresh; no token or user-entered search is uploaded by this page.
- Changes stay on the existing source branch for PR #2083. The next successful scheduled run deploys the latest source from that branch and a fresh feed.
