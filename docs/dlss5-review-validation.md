# DLSS 5 review follow-up validation

This follow-up integrates the feature with upstream main through
`fc375e9612ae528e9ec62dd98bc4a4578f84bb67` (10 November 2026). The shared
`vk_temporal` chain, FSR engines, recorder, Audio tab and current Debug layout
are retained. NR remains part of the DLSS engine alone.

## Review changes

| Review point | Change | Evidence |
| --- | --- | --- |
| Dynamic resolution recreation | NR creation and allocations use the SR maximum input size; each evaluation supplies the current subrect | Real synthetic GPU subrect probe; Windows engine build |
| Native HDR resets SR every frame | Reset only when leaving an active NR path | Production early-exit policy executed over 600 blocked frames |
| Unavailable NR resets SR every second | Availability checks preserve SR history after the initial transition and avoid repeated destruction | Production policy executed with a fake clock and repeated failed probes |
| Off retains model VRAM | Keep it for Compare, release after two seconds Off outside Compare using the shared deferred lifetime | Clock-driven grace/re-enable/Compare tests |
| Recorder ordering | Drain B_DIRECT before both native NGX NR calls | Source validation and negative mutations that remove the boundaries |
| Jitter metadata | No verified NR keys found; reset NR history for jittered inputs and preserve SR jitter/history | Contract inspection and code; temporal visual quality remains unverified |
| Production fault injection | Requires HOOKSHOT_NR_TESTING; ordinary builds do not read the variable | Windows build and source inspection |
| Always-visible DLSS 5 tab | Graphics submenu under Upscaler, hidden without NGX | Executed production row visibility and parent/submenu navigation |
| Compiler discovery | Four original NR tests and the lifecycle test declare RUN_ALL_ARGS | Full test runner uses its detected compiler; main has replaced the old ARGS table |
| Shader header coverage | Composite shader added to test_dlss_actor.py | glslang shader-to-header comparison passed |
| Debug persisted into next launch | Ignore legacy dlss5_debug on load and omit it on save | Executed production ini load/save loops; legacy debug=5 did not bypass NR in the live renderer |

## Builds and automated checks

- Windows NGX Vulkan renderer: linked successfully with llvm-mingw 23 and the
  local NGX SDK. No SDK files or binaries are part of the change.
- Complete isolated Windows game: built successfully, including the current
  host/renderer API, in 16 minutes 27 seconds. The installed renderer is the
  final separately checked NR build.
- Windows no-SDK: vk_dlss.cpp compiles without HOOKSHOT_NGX.
- Native Linux (offline Debian 12 / GCC 12.2): vk_menu.cpp, vk_imgui.cpp and
  vk_dlss.cpp with NGX, plus vk_dlss.cpp without NGX, compile; four native CPU
  checks pass. This is not a Linux renderer link or GPU run.
- Full game-free Windows suite: **323 passed, 6 failed, 21 skipped**. All five
  NR checks, shader header comparison, affected menu fixtures and FPS ordering
  checks passed. The six failures were also reproduced on a separate clean
  upstream-main checkout with the same tools:
  - nx2/test_nup_paths.py: Windows link/junction privileges and sandbox limits.
  - test_bake_ds.py: zstd command-line tool unavailable.
  - test_builder_details_hitbox.py, test_builder_dlss_update.py and
    test_updater_asset_digest.py: .NET runtime present, .NET SDK absent.
  - test_recorder_sync.py: its Windows negative exit fixture also exits cleanly
    with the intentionally old recorder destructor, so the mutation is not
    caught on this local toolchain. Its NR boundary/source checks and normal
    command-stream runs passed before that unchanged negative fixture failed.

The runner's Windows result is not reported as an all-green suite or a CI
result. No unrelated tests were weakened to hide these failures.

## Real GPU checks

Hardware: NVIDIA GeForce RTX 5080, driver 617.42, user-supplied NR 310.9.16.
The optional tests/dlss_nr_subrect_probe.cpp uses synthetic gradients and
constant depth/motion; it writes no images. It was compiled with both
llvm-mingw and MSVC. One 640x360 feature evaluated 640x360, 512x288, 432x240,
then 640x360 without recreation. GPU readback found no writes outside each
active subrect and no NaN/Inf; the first and last full-size outputs matched
bit for bit. This is evidence for that runtime and those sizes only.

The headless game exercised over 5,400 actual NR evaluations with the upstream
threaded recorder, at an active size of 1440x810. It logged no NR evaluation
or device-loss failure. The headless path does not normally tick menu input,
so that run is not counted as a Toggle/Hold, menu or normal-window-exit test.
It was stopped by the test harness.

The normal-window test then exercised both missing-runtime and available-runtime
starts with RX_VK_RECORDER=thread, without image capture. The missing-runtime
run rendered normally, logged the missing nvngx_dlssnr.dll, and produced no
native modal dialog. After restoring the DLL and restarting, preflight reported
available=1 and NR evaluated successfully. A legacy dlss5_debug=5 entry was
ignored: NR ran normally, and a subsequent settings save omitted that key.

Scripted menu input entered Graphics > DLSS 5 > Compare with Right, toggled NR
four times, cancelled back to settings, selected Hold, held/released the shortcut
and cancelled again. Evaluation counters stayed unchanged while NR was bypassed.
No feature was recreated during these comparison transitions. Ordinary Off then
released NR resources after two seconds; switching On created one new feature.
Both normal-window runs exited after WM_CLOSE to their own Hookshot window,
within the 30-second watchdog and without forced termination. This is not a
claim that the earlier intermittent shutdown/TDR cause has been fixed.

The test used a separate copy of the saves. The DLL and original options were
restored afterwards; the original and restored options have identical SHA-256.
The contributor's main game installation was not changed.

## Remaining validation limits

No screenshots or generated previews were taken. The contributor reviewed and approved the updated menu in the running game
before authorizing publication of this follow-up. Physical controller navigation, every aspect ratio,
all DRS ranges, injected device loss and temporal NR image quality have not
been exhaustively verified. The earlier Windows exit/TDR report remains an
open limitation; this follow-up does not claim a general shutdown fix.
Native Linux NR has no known compatible runtime and remains capability
probing/fallback, not verified Linux GPU support.

## Main integration on 11 November 2026

Integrated 144 upstream commits through
`2ed98c46843b37a45b9afec531aba5abcd579e1a`, preserving the new direct NGX
Frame Generation, HDR SR, rounded render ranges, runtime control bridge,
environment overrides and FPS-counter levels/graph/corner selection.

The NR Statistics option and its GPU timestamp queries have been removed.
The FPS counter keeps upstream's rendering, levels and selected corner; old
`dlss5_stats` preferences are ignored and removed on the next save.
The control bridge has a DLSS 5 submenu name;
NR model drags publish an atomic flag for the render thread. NGX initialization
is serialized for the background probe, SR/NR and the new FG caller. Native
HDR bypasses the SDR-only NR/composite path without disturbing SR history.
Temporary environment values remain temporary when settings are saved.

Windows NGX renderer and complete isolated game built successfully (the game
build took 5:03, including 1:56 compilation with existing local object caches).
The no-NGX Windows DLSS object also compiled. The full game-free suite ended
with **377 passed, 5 failed, 30 skipped**. NR, affected menu/environment,
control bridge, HDR and shader checks passed. Remaining failures were the
three .NET SDK-dependent checks, Windows link-privilege extraction fixtures,
and the previously observed recorder negative exit fixture. No assertions
were removed to hide these failures.

The Linux check could not run: Docker's Linux engine pipe was unavailable,
including after attempting to start the installed Docker Desktop. Previous
Linux object checks above apply to the earlier revision, not this merge.
The contributor approved the menu in the running game, then requested removal
of Statistics before publication. No screenshots or generated previews are used.

Four further upstream commits through `d8f4a173dafb3dc20553145e37d6dbf46dccc91b`
were integrated before publication, retaining the new reactive mask, VRAM
budget row and DLSS size diagnostics. The NR settings migration coexists with
the new memory-budget migration. The reactive mask still feeds SR independently
of NR; it is not presented as a semantic NR control mask.

Final Windows NGX renderer link and no-SDK DLSS object compile passed after
Statistics removal. The complete suite passed **379 checks, with 6 failures
and 30 skips**. NR, FPS overlay ordering, reactive-mask and affected menu
checks passed, including loading the retired `dlss5_stats=1` preference
without enabling FPS or changing NR. The additional failure is the new
`test_vram_budget_row.py` fixture's unused `kVramMinimumOnly` constant under
llvm-mingw clang 23 with `-Werror`; it reproduces identically from unmodified
upstream `d8f4a173` sources. The other five failures have the causes listed
above. No test assertions were weakened. The rebuilt renderer was staged in
the isolated game folder; this last removal has not had another GPU play test.

## Follow-up review and compact-menu merge

Integrated main through `6c8c1bfb08f34a7f9742b768001480d9710664d2`, including
its compact tuning bar, texture mip bias and recorder test fix. NR keeps a
separate Compare toolbar and retains General/Quality selection in the shared
row-value renderer. Full-menu navigation and the upstream compact-mode state
are preserved; the placement option does not display or resize a toolbar.

Compare, Retry detection and Reset NR settings accept normal confirm or Right
as well as mouse input. Simultaneous confirm/Right executes once. The setting
is named Compare Toolbar position. Merge-corrupted Inventory/Teleport UTF-8
strings and the NGX path comment were restored from upstream. RX_VK_DLSS_START
was removed and NR environment overrides documented. The periodic capability
probe uses try_lock and returns the cached issue while NR is busy; explicit
Retry still checks synchronously. The actions regression executes production
branches and tests lock contention from another thread without a GPU.

Windows NGX renderer linked and the no-SDK DLSS object compiled. The rebuilt
renderer was staged in the isolated game directory while the game was closed.
No fresh GPU play test, screenshot or Linux build was performed in this update.

Final complete suite: **383 passed, 5 failed, 30 skipped** in 96 seconds. NR
actions/menu, FPS ordering, compact tuning and recorder checks pass. Remaining
failures are the three missing .NET SDK fixtures, Windows link privileges and
the upstream VRAM-budget fixture unused-constant warning documented above.


## Maintainer follow-up on 12 November 2026

Merged 73 upstream commits through `fce53453a2fdd701bb466c4e2c0de839bd6f2042`,
retaining the new Graphics sections, native HDR tone mapper, field-of-view
control, secondary controller bindings and renderer API version 18. The
Graphics entry and compact-page title now read DLSS 5 Neural Rendering. Its
entry is immediately after DLSS model, within the upstream scaling section.

The keyboard regression now ends the shortcut-routing extraction before the
periodic NR probe, supplies the NR state/persistence stubs, and exercises F1
cancelling Compare for both queued and polled input. Existing shortcut and
saved-configuration assertions remain intact. The NR menu check verifies the
new label and ordering; Graphics-section and affected menu tests pass.

Windows NGX renderer link and no-SDK DLSS object compile passed. Linux and a
new live NR GPU evaluation have not been verified for this merge. The menu
conversion is prepared for contributor review in the running game, in
accordance with their earlier request to approve official menu conversions
before publication. No screenshots or generated previews were captured.


The complete Windows suite finished with **433 passed, 9 failed, 34 skipped**
(106 seconds, eight concurrent checks). Menu keys, NR, Graphics sections,
audio/stick/framegen, recorder and FPS checks pass. Six failures require the
missing .NET SDK (including new portable-builder checks); extraction-path
fixtures require Windows link privileges. The remaining two are upstream's
unused `kVramMinimumOnly` fixture constant under clang 23 / Werror and the new
`HOS_FPS_LOG` set-means-on check in `host/oot_high_fps.c`, which also exists
unchanged on upstream `fce53453`. Assertions were not weakened to hide them.

The complete isolated Windows game build passed in 15:11, with 650 compilation
units and zero compilation failures. The SDK-enabled build compiled and staged
its own API-18 renderer (current upstream ignores the prebuilt override when
building with NGX). Intermediate build outputs were cleaned by the builder.
The normal-window live review starts with NGX initialized and NR preflight
available. Shader preparation is in progress; this is not a fresh NR quality
or physical-input validation claim. Publication remains held for the
contributor's explicit approval after trying the game.


## Publication after live approval

The contributor approved the renamed/repositioned menu in the running game.
Before publication, four more upstream commits through
`9df055f23cd4604a6f520631a6dd4154a55a22b4` were integrated without conflicts.
They change Reflex submit tagging, RADV fallback/optimization and the sound
clock, and do not change the approved menu or renderer API. Final Windows
NGX renderer link and no-SDK DLSS object compilation pass. The complete suite
now reports **435 passed, 9 failed, 34 skipped** (105 seconds). All NR/menu,
Graphics sections, recorder, FPS, Reflex and high-FPS checks pass. The nine
failures retain the environmental/upstream causes listed above. The full-game
build and live approval precede only these last four non-menu upstream commits;
no fresh Linux or GPU-quality validation is claimed for this final merge.
