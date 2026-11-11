# macOS (Apple Silicon) port — progress

Status of the native Apple Silicon / WebGPU-Metal port that lands through
[PR #1872](https://github.com/NotRexed/Hookshot/pull/1872).

How to build and run: [development.md § macOS](development.md#macos-apple-silicon) and the macOS section of
[readme.md](../readme.md). This page is the changelog of what landed, who did it, and which PRs carry the work.

## Current status (2026-11-11)

| Area | State |
|---|---|
| Native arm64 build + link | Working (SDK via `toolchain.native_target`, pthread CS/CV, wgpu/SDL copy) |
| Hookshot Builder (macOS) | Packaged, ad hoc signed; CI `macos-builder` / `macos-posix` green |
| Title logo / menu text / subtitles | Fixed (whole-stride verts; draw base/instance/ID in c0) |
| Title + opening movies | Fixed (NVN2 compute push constants; HMMA → linear upscale stub) |
| 3D gameplay (black) | Fixed (shared sampler made non-filtering for unfilterable depth-as-color) |
| 3D gameplay (blown-out / white) | Mitigated in tree (NVN2 SSBO table, WGSL globals, 64 KiB writeback prefix); **needs Mac re-test** |
| Metal Occluded black window | Fixed (skip frame; do not reconfigure) |
| Save path backslashes on POSIX | Fixed (`/` mounts) |
| Spurious SDL focus loss | Mitigated (focus check + click/key recovery + Apple recheck) |
| Depth32Float CPU uploads | Fixed (clear via pass; WebGPU forbids `WriteTexture` into depth) |
| Game-free CI | Green on `bcf9e1a` (MERGEABLE / CLEAN) |

CI does **not** run the game. Please try a Mac Builder artifact and report chip, macOS version, steps, and log.

## Thanks

This port is the work of many people. In particular, thanks to:

- **[@yeetbot90](https://github.com/yeetbot90) (BED)** — first native macOS support (#715), the rebased #1872 branch, Builder packaging, CI, and keeping the PR mergeable against `main`
- **[@jrldorival](https://github.com/jrldorival) (Dorival Junior)** — WebGPU/Metal renderer fixes that made the title, menus, movies, and sampler path work (#1088 and follow-ups)
- **[@MatthewFeroz](https://github.com/MatthewFeroz)** — macOS toolchain/SDK fixes, condition-variable wake fix, build copy fix, and the unfilterable shared-sampler fix that turned black 3D into a visible (if overexposed) picture ([yeetbot90#4](https://github.com/yeetbot90/Hookshot/pull/4), [#5](https://github.com/yeetbot90/Hookshot/pull/5))
- **[@Arkex-ai](https://github.com/Arkex-ai) (Issai)** — portable offline-bake / zstd / Clang 18 work ([#1931](https://github.com/NotRexed/Hookshot/issues/1931), [#1954](https://github.com/NotRexed/Hookshot/pull/1954))
- **[@madebyjordan](https://github.com/madebyjordan)** — early reports and fixes carried through the #715 → #1088 line
- **[@hckrman101](https://github.com/hckrman101)** — Linux driver-cache room (#2033) and review pressure to stay current with `main`
- **[@NotRexed](https://github.com/NotRexed)** — display-startup test stub (#2051), maintainership, and Mac-tester coordination
- Everyone who tested on Apple Silicon and filed logs when we had no Mac in CI

## Related pull requests and issues

### Lineage (macOS port)

| PR | Repo | Author | State | What |
|---|---|---|---|---|
| [#715](https://github.com/NotRexed/Hookshot/pull/715) | NotRexed/Hookshot | yeetbot90 | Closed | Initial native macOS build support |
| [#1088](https://github.com/NotRexed/Hookshot/pull/1088) | NotRexed/Hookshot | jrldorival | Closed | #715 rebased on `main` + WebGPU/Metal renderer fixes (title/menu/movies; 3D still white) |
| [#4](https://github.com/yeetbot90/Hookshot/pull/4) | yeetbot90/Hookshot | MatthewFeroz | Open (into #1872) | Game builds, links, reaches the title on Apple Silicon |
| [#5](https://github.com/yeetbot90/Hookshot/pull/5) | yeetbot90/Hookshot | MatthewFeroz | Open (into #1872) | Title, menu text, movies, and 3D picture on Apple Silicon (includes Jrldorival’s #1088 commits + sampler fix) |
| [#1872](https://github.com/NotRexed/Hookshot/pull/1872) | NotRexed/Hookshot | yeetbot90 | Open | Current merge vehicle: #1088/#4/#5 + bake portability + gameplay/runtime follow-ups |

### Adjacent / unblocking work folded into #1872

| PR / issue | Author | State | Why it matters here |
|---|---|---|---|
| [#1931](https://github.com/NotRexed/Hookshot/issues/1931) | Arkex-ai | Closed | Offline bake portability tracking |
| [#1954](https://github.com/NotRexed/Hookshot/pull/1954) | Arkex-ai | Merged | Portable zstd + Clang 18 bake path (also carried on the #1872 branch) |
| [#2033](https://github.com/NotRexed/Hookshot/pull/2033) | hckrman101 | Merged | `driver_cache_room` on Linux; broke the display-startup fixture until #2051 |
| [#2051](https://github.com/NotRexed/Hookshot/pull/2051) | NotRexed | Merged | Stub `driver_cache_room` in the display-startup test so game-free CI is green again |

## Progress timeline (high level)

1. **#715** — POSIX host, Metal/WebGPU path, macOS Builder scripts; closed when it drifted from `main`.
2. **#1088** — Rebase + Jrldorival renderer work: whole-stride vertices, c0 draw IDs, NVN2 push constants, sampler sharing past 16, Eden `lower_to_maxwell.h`, HMMA upscale stubs. Title/menu/movies good; 3D white. Closed for conflicts / no Mac CI.
3. **yeetbot90 #4 / #5** — Matthew’s build/runtime fixes and the shared-sampler non-filter fix (black → overexposed 3D), plus cherry-picks of the #1088 renderer commits.
4. **#1872** — Rebased onto current `main` (conflicts resolved), #4+#5 renderer/build commits folded in, bake portability kept, then:
   - NVN2 compute SSBO table + WGSL `LoadGlobal`/`WriteGlobal` + small/prefix dispatch writebacks (exposure)
   - CI: skip Linux-only checks on macOS; shard macOS source tests; portable `inherit_errexit`
   - Runtime: Occluded present, POSIX save separators, SDL focus recovery, Depth32Float clear path

## What still needs a Mac

- Confirm 3D gameplay exposure / brightness after the writeback-prefix change (was white/blown-out on M1 Max / M5 reports).
- Confirm Occluded / focus / save-path behaviour with the window in front and when briefly covered.
- Builder install, update, save/load, rumble, controller, and long play sessions.

Report against [PR #1872](https://github.com/NotRexed/Hookshot/pull/1872): Mac model/chip, macOS version, Builder or source build, steps, and log (Metal frame capture for render bugs if you can).
