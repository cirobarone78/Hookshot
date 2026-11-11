# Releasing

How Hookshot is versioned and released: the version number, how pull request titles decide it, the release flow,
the update tracks, the release files, and where each copy of the version comes from. The players' side of updating
is in the [install guide](../user/install.md#updating).

- [The version number](#the-version-number)
- [Pull request titles decide the version](#pull-request-titles-decide-the-version)
- [How a release is made](#how-a-release-is-made)
- [Promoting a release candidate](#promoting-a-release-candidate)
- [When a promotion goes wrong](#when-a-promotion-goes-wrong)
- [The nightly and rc prereleases](#the-nightly-and-rc-prereleases)
- [Update tracks](#update-tracks)
- [The files of a release](#the-files-of-a-release)
- [Tags pushed by hand](#tags-pushed-by-hand)
- [Hotfixes](#hotfixes)
- [Where the version comes from](#where-the-version-comes-from)
- [The changelog](#the-changelog)
- [Rules](#rules)

## The version number

Hookshot follows [Semantic Versioning 2.0.0](https://semver.org/). Releases are made with
[release-please](https://github.com/googleapis/release-please) (`release-please-config.json`): the version and the
changelog come from the [Conventional Commit](https://www.conventionalcommits.org/) titles of the pull requests
merged into `main`.

A version is `MAJOR.MINOR.PATCH` with an optional prerelease suffix: `2.0.7`, `2.1.0-rc.1`. Its tag is `v2.0.7`; the
`v` belongs to the tag, not the version. Build metadata is not used in tags.

One version covers the whole project: the game, the Vulkan back end, the lift pipeline and its scripts, Hookshot
Builder and the Linux AppImage. They are built from the same commit and released together.

The surface the version rules protect is:

- the command line of `nx2/make_game.py` and of the builder;
- the `RX_` and `HOS_` switches;
- the files a build writes into a game folder (`hookshot_options.ini`, `hookshot_env.txt`, `language.txt`,
  `hookshot_version.txt`);
- saves;
- the format of `hookshot_log.txt`.

The C sources and internal headers are not an API and may change in any release.

## Pull request titles decide the version

Pull requests are squash-merged, so each becomes one commit on `main` whose subject is the pull request's title. The
*PR title* workflow (`.github/workflows/pr-title.yml`) checks that the title is a Conventional Commit:

```
type(scope): description
type(scope)!: description        (a breaking change)
```

`scope` is optional. A `!` before the colon, or `BREAKING CHANGE:` in the commit body, marks a breaking change. The
description becomes the changelog line. The allowed types and examples are in
[CONTRIBUTING.md](../../CONTRIBUTING.md#pull-request-titles).

Every release is first a release candidate, so the next version is always a release candidate's:

| Commit | After `2.0.7` (a release) | After `2.0.8-rc.1` (a release candidate) | Changelog section |
|---|---|---|---|
| `!` or `BREAKING CHANGE:` | `3.0.0-rc.1` | `3.0.0-rc.1` | its own section, and its type's |
| `feat` | `2.1.0-rc.1` | `2.1.0-rc.1` | Features |
| `fix` | `2.0.8-rc.1` | `2.0.8-rc.2` | Bug Fixes |
| `perf` | `2.0.8-rc.1` | `2.0.8-rc.2` | Performance Improvements |
| `revert` | `2.0.8-rc.1` | `2.0.8-rc.2` | Reverts |
| `refactor`, `build`, `ci`, `docs`, `test`, `style`, `chore` | `2.0.8-rc.1` | `2.0.8-rc.2` | Code Refactoring, Build System, Continuous Integration, Documentation, Tests, Styles, Miscellaneous Chores |

A release candidate of a minor version (`2.1.0-rc.1`) goes on to `2.1.0-rc.2` for a `feat` too, and one of a major
version for any commit. With release-please's prerelease versioning, a version that moves up during a series keeps
the release candidate number: a `feat` after `2.0.8-rc.2` proposes `2.1.0-rc.2`. To start at `rc.1`, put
`Release-As: 2.1.0-rc.1` in that pull request's squash-merge description.

A release takes the highest bump among its commits. A commit whose subject is not a Conventional Commit (a merge
commit, or a pull request merged without squashing) is not read: it makes no release and is not in the changelog.

To choose the version yourself, put a `Release-As:` footer in the body of a commit on `main`. Name a release
candidate, so the release still goes through Promote:

```
fix(vk): keep the swapchain when the window is moved

Release-As: 2.1.0-rc.1
```

## How a release is made

The Release workflow (`.github/workflows/release.yml`) makes every release in two steps: a release candidate, which
is a prerelease for testing, and then Promote, which publishes a good release candidate as its version.

On every push to `main`:

1. release-please reads the commits since the last release candidate. If any of them makes a release, it opens or
   updates a pull request titled `chore: release <version>` for the next release candidate. The pull request changes
   `.release-please-manifest.json`, writes the version to `.release-please-version`, and puts the new entry at the
   top of `CHANGELOG.md`. The entry can be edited in the pull request before merging.
2. Merging the release pull request (squash or not; it is the one exception) makes the release candidate.
   release-please tags the merge commit `v<version>` and makes its GitHub release as a draft, with the changelog entry
   as its notes.
3. The workflow calls the Linux AppImage (`linux-appimage.yml`) and Windows builder (`windows-builder.yml`) workflows
   on the tag. They build the files, sign their build provenance, and attach them with `scripts/release_upload.sh`.
   New update parts go to the `linux-parts` and `builder-parts` releases.
4. The publish job adds `SHA256SUMS` and the "Which file do I download?" table under the notes
   (`scripts/release_files.sh finish`), checks that every file is there and listed in `SHA256SUMS`, and publishes the
   draft as a prerelease. A release candidate is never "latest".
5. The rc job updates the `rc` prerelease (see [below](#the-nightly-and-rc-prereleases)).

There is no step to start a series: the first fix after a release proposes the next version's `rc.1`, and each later
merge of the release pull request makes the next `rc.<n>`.

The releases are made with the workflow's `GITHUB_TOKEN`, and the builds are called from the same workflow, so no
personal access token is needed. A pull request opened by `GITHUB_TOKEN` does not start other workflows, so the release
pull request has no checks of its own; it changes only the changelog, the manifest and the version file.

## Promoting a release candidate

When a release candidate is good, start the Release workflow by hand on `main` (Actions > Release > Run workflow) with
its tag, or empty for the newest release candidate:

```sh
gh workflow run release.yml -R NotRexed/Hookshot -f rc=v2.0.8-rc.2
```

Start it once. Promote runs one at a time from its first job to its last (the workflow's concurrency group). A second
run started meanwhile waits, and stops with "v2.0.8 is already published" once the first has published.

1. `scripts/release_promote.sh prepare` checks that the release candidate is a published prerelease on `main`, tags
   its version (`v2.0.8`) on the same commit, and makes that release as a draft. Its notes are those of the version's
   release candidates, newest first.
2. The Linux and Windows workflows build the version's files from that commit, and the publish job checks them and
   publishes the release as "latest". The files are built again, not copied from the release candidate, because every
   file names the version it was built as and the updaters compare that with the latest release's tag. Update parts
   that did not change are the same files on `builder-parts` and `linux-parts`, so a player who tried the release
   candidate downloads only the parts that name the version.
3. The record job sets `.release-please-manifest.json` to `2.0.8` (`scripts/release_promote.sh record`), adds the
   version's entry to `CHANGELOG.md`, and has release-please remake the release pull request, which now proposes
   `2.0.9-rc.1` or `2.1.0-rc.1`. It runs whenever the version ends up published, including when someone publishes the
   release by hand, and changes nothing if the manifest and changelog already have the version. If `main` takes no
   direct push, it opens a pull request `chore(release): record 2.0.8 as released` instead: merge it before the
   release pull request.

If a build fails, the release stays a draft: re-run the failed jobs. Files already on the release are replaced, so a
re-run never fails because of them. Promote can also be started again with the same release candidate; it continues
with the tag and draft it made.

With the repository variable `CI_RELEASE_WINDOWS` set to `false`, the Windows files are left for you to upload and the
draft for you to publish. Upload them, run `scripts/release_files.sh finish v<version>` (with `GH_REPO` set) so
`SHA256SUMS` lists them, then publish; publishing starts the record job.

## When a promotion goes wrong

The scripts find a release by listing the repository's releases, drafts included, and change it by its id
(`scripts/release_files.sh find`). A failed listing stops the job; it is never taken as "no release". The release jobs
of the Linux and Windows workflows never create a release for a tag the Release workflow passed them.

| Symptom | What to do |
|---|---|
| A tag has two releases; every script refuses it and names both ids | Delete the one not meant (on its release page, or `gh api -X DELETE repos/NotRexed/Hookshot/releases/<id>`), then re-run the failed jobs |
| Promote says the version is already published | It is. Check that the record job ran (last row). A later fix goes into the next release candidate |
| Promote says another Promote run is in progress | Wait for that run or cancel it, then start Promote again |
| The release is published, but the next release pull request proposes `2.0.8-rc.<n+1>` instead of `2.0.9-rc.1` | The manifest still holds a release candidate. Re-run the failed jobs of the Promote run, which runs its record job. By hand: `scripts/release_promote.sh record v2.0.8` in a checkout of `main` (with `GH_REPO` set), then a pull request with the change, merged before the release pull request |

## The nightly and rc prereleases

**`nightly`** is the latest development build. On every push to `main`, once the Linux and Windows workflows have
built that commit, their release jobs move the `nightly` tag to it and replace the files of the `nightly` prerelease
(`scripts/release_upload.sh nightly`), with `SHA256SUMS` and build provenance as for a release. A run that finishes
after a newer push leaves it alone. `nightly` is not a `v*` tag, so release-please and `git describe` ignore it; the
builders and the game read it only on the Nightly track. Its AppImage's update information names `nightly`, so
AppImageUpdate moves a nightly AppImage to the next nightly.

**`rc`** ("Latest release candidate") holds the AppImage and `.zsync` of the newest published release candidate or
release, in semver order (`v2.1.0-rc.2` < `v2.1.0-rc.3` < `v2.1.0`). A release candidate's AppImage names `rc` in its
update information, so AppImageUpdate takes it to the next release candidate and then to its version's release, and
never back to an older release. The rc job (`scripts/release_rc.sh`, concurrency group `release-rc`) runs after each
publish and when a release is published by hand. Each run finds the newest release by listing them, copies its two
files (so that release's `SHA256SUMS` still checks them), uploads them before removing the older ones, and moves the
`rc` tag. `scripts/release_upload.sh rc` and `scripts/release_files.sh publish rc` are refused, and a hand-pushed `rc`
tag builds nothing.

Neither is a version: the builders, the setup, the game's update check and the parts lookup read only
`v<major>.<minor>.<patch>` and `-rc.<n>` tags.

## Update tracks

The builders have an **Update track** setting: Release, Release candidate or Nightly. Its default is the track of the
installed build, read from its version: `v2.0.7` is a release, `v2.1.0-rc.1` a release candidate, and a
`git describe --long` name such as `v2.1.0-rc.1-3-g1a2b3c4` (or `-0-g...` on a tagged commit) the nightly.

| Track | Updates to | Offered when |
|---|---|---|
| Release | the latest release | it is another version |
| Release candidate | the newest release candidate or release, in semver order | it is newer; never an older release |
| Nightly | the `nightly` release's build (its list's `tag` line) | it is another build |

Choosing another track installs that track's newest build, an older version too, after asking. The game's own update
check (`host/hos_update.c`) follows the track of the folder's version. The same rules are in
`builder/HookshotBuilder/Updater.cs`, `builder/linux/linux_update.py` and `tests/test_update_tracks.py`. A release
candidate's and the nightly's `HookshotBuilder.exe` are built with `HOOKSHOT_SETUP_RELEASE`, so without `--tag` they
install their own release (`builder/setup/setup.c`).

## The files of a release

The names never change: the updaters look for them by name.

| File | For |
|---|---|
| `HookshotBuilder.exe` | Windows: the setup players download. It reads `hookshot-setup.txt` and downloads the rest |
| `Hookshot-v<version>-x86_64.AppImage` | Linux and Steam Deck |
| `Hookshot-v<version>-x86_64.AppImage.zsync` | AppImageUpdate and Gear Lever, which update the AppImage itself |
| `hookshot-setup.txt` | The update list of the setup and the Windows builder (`builder/setup/setup.c`, `builder/HookshotBuilder/Updater.cs`) |
| `hookshot-linux.txt` | The Linux updater's list (`builder/linux/linux_update.py`) |
| `Hookshot-v<version>-Windows-x64.zip` | RecompLauncher: `HookshotBuilder.exe` and `recomplauncher.json` |
| `SHA256SUMS` | The SHA-256 of every other file, in `sha256sum`'s format |

The release notes end with a short table of which file to download (`scripts/release_files.sh table`).

The AppImage carries update information, written by `scripts/linux/appimage.sh`:
`gh-releases-zsync|NotRexed|Hookshot|latest|Hookshot-*-x86_64.AppImage.zsync` for a release, with `rc` or `nightly`
in place of `latest` for those builds. `./Hookshot-v<version>-x86_64.AppImage --appimage-updateinformation` prints it.

**Checking a download.** Put it beside `SHA256SUMS` and run:

```sh
sha256sum -c --ignore-missing SHA256SUMS
```

Every file, `SHA256SUMS` included, also has a build provenance attestation (`actions/attest-build-provenance`) signed
by the workflow run that built it:

```sh
gh attestation verify HookshotBuilder.exe -R NotRexed/Hookshot
```

It passes only for a file built by this repository's workflows, and shows the commit and the run.

## Tags pushed by hand

A `v*` tag pushed by hand (`git tag v2.0.8-rc.9 <commit>`, `git push origin v2.0.8-rc.9`) still starts the Linux and
Windows workflows, which make its release with GitHub's generated notes and attach the files, `SHA256SUMS` and the
table. A tag with a prerelease part is a prerelease. release-please is not involved and the next release pull request
does not change, so this is only for one-off test builds.

## Hotfixes

Fix on `main` with a `fix:` pull request, merge the release pull request (the next release candidate) and promote it.
There are no maintenance branches: only the newest release is supported. A tag pushed by hand on another branch is
built and released like a release candidate, but release-please follows only `main`, so merge that commit into `main`
afterwards.

## Where the version comes from

The git tag is the source of truth.

| Place | Comes from |
|---|---|
| git tag | release-please (a release candidate), Promote (its version), or a tag pushed by hand |
| `.release-please-manifest.json` | The release pull request, and the record job once a version is published |
| `.release-please-version` | The release pull request. It is not named `version.txt` because `nx2/version.py` would read a root `version.txt` as the version of every build from the checkout |
| `CHANGELOG.md` | The release pull request, and the record job |
| `hookshot_log.txt` and the Insert menu | `nx2/version.py`: `HOOKSHOT_VERSION`, then `VERSION` or `version.txt`, then `git describe --tags --match "v[0-9]*"` |
| `hookshot_version.txt` in a game folder | The `VERSION` file written when the tools are packaged (`nx2/make_game.py`) |
| AppImage file name | The release's tag (`HOOKSHOT_VERSION`), else `git describe --tags --match "v[0-9]*"` (`scripts/linux/appimage.sh`) |
| `HookshotBuilder.exe` | `dotnet publish -p:Version=<version>` in `windows-builder.yml`; the project file's `0.1.0` is only the default for a local build |

`nx2/version.py` also appends a fingerprint of the source files, `(source 1a2b3c4d)`. It is not a version: it tells
two builds of the same release apart, and it is the only identifier a build from a modified checkout has.

Old tags that are not `v*` (`Release`, `amd`, `text-hotfix` and others) are not releases; the tooling matches only
`v[0-9]*`.

## The changelog

`CHANGELOG.md` is written by release-please, newest first, one section per release candidate with the changes since
the one before. A promoted version's section is a line naming the release candidate it is. Do not rewrite a released
entry; a correction is a new pull request and a new release. `changelog.txt` is the hand-written changelog of `0.1.0`
and is not updated.

## Rules

- Do not edit a version number in a file, move a tag, or reuse a version. Only the release pull request and Promote
  change the manifest.
- Do not put game files, keys, builds or anything made from a dump in a release. `scripts/release_upload.sh` refuses
  file names that look like them, or like NVIDIA's runtime files.
