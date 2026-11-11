# Contributing to Hookshot

Hookshot is a static recompilation of the Switch 2 *The Legend of Zelda: Ocarina of Time* remake, built on each
player's PC from their own copy. This page has the rules for issues and pull requests. How to build, run and test is in
the [developer documentation](docs/dev/README.md).

## No game files, ever

**No game files, keys, or anything made from them leave your PC.** The repository does not contain the game and never
will. That covers:

- the `.nup`, `romfs`, `exefs`, `.nso`, `.nca`, `.nsp`, `.xci`, `.nsz` and `.xcz` files, and title keys;
- everything in `work/` and in a game folder: the dump, `image.bin`, the lifted C, builds, caches and screenshot
  folders;
- saves, `hookshot_options.ini`, `hookshot_env.txt` and `language.txt`.

Screenshots and videos of the game, and `hookshot_log.txt`, are fine to post. Do not ask, in an issue or a pull request,
where to get the game, how to decrypt it, or for someone else's files. `.gitignore` covers most of this, but check
`git status` before you commit. If you are not sure whether a file is game data, leave it out.

## Ways to help

| | What |
|---|---|
| **Test on your hardware** | Reports from AMD and Intel cards, other drivers, other distributions and SteamOS are useful even when everything works. Add a row to [tested configurations](docs/tested-configurations.md) |
| **Play further** | Reaching new areas, cutscenes, menus and items finds problems nobody has seen yet |
| **Report what is broken** | Use the [issue forms](https://github.com/NotRexed/Hookshot/issues/new/choose), with the version, your hardware, where you were and `hookshot_log.txt` |
| **Fix something** | The [worklist](docs/worklist.md) has the open work, scored; pick from its top. [Workflow](docs/dev/workflow.md) says how work is chosen and claimed |
| **Improve the docs** | Corrections and clearer steps are welcome |

## Before you open an issue or a pull request

- Try the [newest release](https://github.com/NotRexed/Hookshot/releases/latest).
- Search the open issues. If yours is there, add your details to it.
- Write in English, and keep to one topic.
- Give the version you ran: the release name, or the first line of `hookshot_log.txt`.
- For a graphics or performance problem, test without ReShade, overlays, shader-cache tools and frame-generation
  injectors.

## Pull requests

1. Fork the repository and branch from `main`. Name the branch for the change: `fix/...`, `linux/...`, `builder/...`,
   `docs/...`.
2. Keep to one topic. A fix does not carry a refactor, and two unrelated fixes are two pull requests.
3. Start the description with why the pull request is needed, in one or two plain sentences a player could follow.
   Then say what changed and how you tested it: GPU, driver, where in the game, fps before and after.
4. Link the issues it fixes with `Fixes #<n>`, one line each. Use `Part of #<n>` or `See #<n>` to keep an issue open.
5. Include screenshots when the change shows on screen: before and after for a fix, the new screen for a feature.
6. Add or update a game-free check where you can, and run `python -I -B tests/run_all.py` (see
   [testing](docs/dev/testing.md)). CI must pass.
7. Rebase on `main` when it moves, and resolve conflicts in your branch.
8. Commit no build output, dumps or generated files.

If you used an AI tool, record it with `Assisted-by:` and `Co-Authored-By:` trailers in your commits.

### Pull request titles

Pull requests are squash-merged, so the title becomes the commit on `main`, and that commit decides the next version
and its changelog line. The *PR title* check requires a [Conventional Commit](https://www.conventionalcommits.org/)
title: a type, an optional scope in parentheses, a colon, and a short description.

```text
fix(vk): keep the menu's text inside the window at 4K
```

| Type | For |
|---|---|
| `feat` | Something new for players or modders |
| `fix` | A bug fix |
| `perf` | Faster, or less memory |
| `refactor` | A change with no effect on behaviour |
| `docs` | Documentation only |
| `test` | Tests only |
| `ci` | The GitHub workflows |
| `build` | The build scripts, the AppImage, the builder package |
| `chore` | Anything else |
| `revert` | Undoing an earlier change; name the reverted pull request in the body |

The scope names the part of the project: `vk`, `linux`, `builder`, `menu`, `video`, `runtime` and so on. A `!` after
the type or scope (`feat(builder)!: ...`) marks a breaking change. How each type moves the version is in
[releasing](docs/dev/releasing.md). Commits inside your branch can be written any way: only the title reaches `main`.

## Code conventions

- Match the file you edit: there is no formatter. Do not reformat code you are not changing.
- New switches use `RX_` in the renderer and `HOS_` in the runtime. They are off unless set, and cost nothing while off.
  Add them to [switches](docs/dev/switches.md).
- The GPU replay never reads live guest memory, honours waits per queue, and keeps texture and sampler registrations
  in submission order. The [architecture](docs/dev/architecture.md#gpu-replay-rules) page has these rules.
- Do not edit `third_party/`. Add a new folder with its provenance note instead.
- Keep `nx2/`, `host/` and `gpu/` close to mkw-recomp, where they come from, and put OoT-specific code in new files
  where you can.
- Run Python with `-I`. Tests use the standard library; the pipeline's existing packages are the exception.
- Keep line endings LF.

## Licensing

Hookshot is free software under the [GNU General Public License, version 3 or later](LICENSE). By submitting a change,
you agree to license it under those terms. Send only code you can license that way: no code from projects with an
incompatible license, and no decompiled game code or anything generated from the dump.

The third-party parts (Eden, suyu, Sirit, the Vulkan Memory Allocator, SDL, Opus, Dear ImGui, zstd, the Libertinus
fonts, zbic, the a64-kit tools, the FidelityFX SDK and Kenney's input prompts) keep their own notices. Preserve them.
NVIDIA's DLSS SDK and AMD's FSR runtime are never in the repository; see [building](docs/dev/building.md#nvidia-dlss).

## Where to talk

- **Issues:** [the issue forms](https://github.com/NotRexed/Hookshot/issues/new/choose).
- **Discord:** https://discord.gg/rexed. Claim work in #dev-work before you start; first bug reports go in
  #bug-reporting.
- **Newest release:** https://github.com/NotRexed/Hookshot/releases/latest.
