# Workflow

How work moves through Hookshot, from a report to a release, and how to decide what to work on next. It is written
for people and for coding agents alike. The rules that never bend, above all that no game files or anything made from
them leave your PC, are in [CONTRIBUTING.md](../../CONTRIBUTING.md).

With many contributors and agents working at once, the project moves fastest when everyone picks from the same
priorities, claims before starting, and leaves a trail the next person can follow.

- [Where work comes from](#where-work-comes-from)
- [Priority](#priority)
- [Hardware tiers](#hardware-tiers)
- [The lifecycle of a problem](#the-lifecycle-of-a-problem)
- [The worklist](#the-worklist)
- [Tested configurations](#tested-configurations)
- [Security reports](#security-reports)
- [Labels](#labels)
- [For agents](#for-agents)

## Where work comes from

| Source | What lands there |
|---|---|
| GitHub issues (game problem, build problem, idea) | The record: version, hardware, place in the game, `hookshot_log.txt` |
| Tracking issues (`[Tracking] ...`) | One per family of reports: AMD rendering, no mesh shaders, Linux, VRAM, missing walls, frame rate |
| Discord #bug-reporting (forum) | First reports, often without a log. Turn the reproducible ones into issues |
| Discord #dev-work | Claims, progress, review requests |
| Discord #dev-stuff | Security scan results, handled before anything else |
| CI | A red check on `main` is everyone's first problem |

## Priority

Score a problem as **severity x reach x confidence** and work from the top. Write the three parts in the issue or the
claim, so others can see why it was picked.

### Severity

| Level | Weight | What it means |
|---|---|---|
| S0 | 8 | Security issue; crash, hang, device lost or a PC freeze; lost or corrupted saves; the builder cannot build |
| S1 | 5 | Cannot progress or cannot start: black screen, missing walls that block a dungeon, softlock, menus unusable |
| S2 | 3 | Wrong but playable: visual corruption, missing objects, audio out of sync, a frame-rate loss over 20% |
| S3 | 1 | Polish: small visual issues, small frame-rate gains, settings, features |

### Reach

Reach is the share of players on the hardware the problem affects, from 0 to 1 (1 when it affects everyone). Two
sources feed it. Both change, so read them again rather than reusing old numbers.

- **Who reports problems.** `python -I scripts/hardware_report.py` counts the GPU vendor, card class and OS named in
  the issue forms. It needs the `gh` CLI. It over-counts hardware where things break.
- **Who plays.** The [Steam Hardware Survey](https://store.steampowered.com/hwsurvey/) is the best public picture of
  PC gaming hardware. Use its current numbers for the installed base.

A problem that hits a large installed base, or that dominates the reports, ranks high either way.

### Confidence

| Evidence | Weight |
|---|---|
| Reproduced by you or a maintainer, with a log | 1.0 |
| Two or more reporters with logs | 0.7 |
| One report, or no log | 0.4. Ask for the log first |

## Hardware tiers

A change must not break a higher tier to help a lower one.

| Tier | Hardware | What it means |
|---|---|---|
| 1 | NVIDIA RTX 20 to 50 and AMD RX 6000 to 9000, on Windows and on Linux (NVIDIA driver, Mesa RADV); Steam Deck | Must keep working. Test here before merging; a regression is S0 or S1 |
| 2 | AMD APUs and handhelds (ROG Ally, Legion Go, Radeon 780M, 890M, 8060S), Intel Arc | Fixed when reported, tested when someone with the hardware can |
| 3 | Cards without mesh shaders (GTX 10 and 16, RX 5000 and older) | Best effort through the fallback, never at a Tier 1 cost |

AMD cards file about half of the reports, while most Tier 1 testing happens on NVIDIA. So an AMD Tier 1 problem with
a log outranks an NVIDIA one of the same severity.

## The lifecycle of a problem

1. **Triage.** Reproduce it if you can. Find the tracking issue it belongs to, or open an issue with the log. Score it
   and add it to the [worklist](#the-worklist).
2. **Claim.** Before starting, say so in Discord #dev-work and on the issue: what, why (the score), and on which
   hardware you can test. Search open pull requests first; two people fixing the same thing is the most common waste.
   Drop a claim out loud when you stop.
3. **Fix.** A branch from current `main`, one topic. Find the cause before the fix: a log, a trace, a measurement.
4. **Test.**
   - A game-free test that fails without the change.
   - `python -I -B tests/run_all.py`, all of it.
   - In the game, on your hardware: what you did and what you saw, with numbers from `hookshot_log.txt` for
     performance. Add a row to [tested configurations](#tested-configurations) for each run you measured.
   - Say what you could not test: another OS, another vendor, real input devices.
5. **Pull request.** Open the description with why the change is needed, then what changed, how it was tested, what
   was not tested, and screenshots when it shows on screen. Give it a Conventional Commit title
   ([releasing](releasing.md#pull-request-titles-decide-the-version)). Link the issue and the tracking issue, and
   post the link in #dev-work.
6. **Review.** Answer every comment in the pull request. Rebase onto `main` before asking for review again: a pull
   request that does not merge cleanly waits.
7. **Merge and release.** The pull request is squash-merged into `main`. It ships in the next release candidate and
   then in the release that promotes it; see [releasing](releasing.md). There are no release branches to merge back.
   Move its worklist row to *Fixed, waiting for a release*.
8. **Verify.** Ask the reporter to retest on the release, then close the issue, or keep it open on the tracking issue
   with what is left.

## The worklist

[docs/worklist.md](../worklist.md) is the scored, sorted list of open work. A GitHub issue stays the full record; the
worklist is the order.

- **Pick** the highest-scored row in **Open** with no owner that you can reproduce, and put your name in *Owner*.
- **Add** a new problem as a row with its three parts filled in and a link to its issue or Discord thread. If a row
  already covers it, add the link there and raise its confidence instead.
- **Move** the row to **Fixed, waiting for a release** when its pull request merges, and delete it when a release
  ships it. A row nobody can reproduce for two weeks, with logs asked for, goes to **Parked**.
- Keep each table sorted by score, and re-score when new logs or hardware numbers arrive.

The page itself has the full rules. Agents may add and re-score rows; a person reviews the change like any other pull
request.

## Tested configurations

[docs/tested-configurations.md](../tested-configurations.md) records what has actually been run: one row per run,
newest first. A run that worked is as useful as one that did not. A row holds:

- the build, from the first line of `hookshot_log.txt` (`hookshot vX.Y.Z-N-gHASH`);
- the hardware and driver;
- the settings that matter;
- where in the game;
- what you measured. Frame rates come from `hookshot_log.txt` ("N presents, X fps") at a named spot, standing still
  unless the row says otherwise.

Name a build by its version or pull request number, never "this change".

## Security reports

Security comes first: a scan result in #dev-stuff is triaged before other work.

- Check every finding against the code, and post the finding and the verdict for each: real or false positive, and
  why.
- Fix the real ones in a pull request marked as security in its title.
- Record false positives in the scanner as not exploitable, with the reason, so the next scan shows only new ones.
- Never paste secrets, tokens or the scanner's private links in public channels.

## Labels

The repository uses GitHub's standard labels (`bug`, `enhancement`, `documentation`, `good first issue`,
`help wanted`, `duplicate`, `question`), plus `testing wanted` for changes that need a run on hardware the author
does not have. release-please manages the `autorelease:` labels; do not set them by hand. Priority is kept in the
worklist, not in labels.

## For agents

- Read this page, then [AGENTS.md](../../AGENTS.md), then [CONTRIBUTING.md](../../CONTRIBUTING.md).
- Pick from the top of the [worklist](../worklist.md); add a scored row for a new problem you find.
- Prefer problems you can reproduce on the hardware you run on.
- Claim before working, report progress where you claimed, and post the pull request there.
- Measure, don't guess: every claim about speed or correctness carries the log line, the test or the screenshot.
- Never open a pull request whose tests you have not run, or that is not rebased onto `main`.
