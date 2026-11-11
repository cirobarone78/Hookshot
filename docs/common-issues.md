# Common issues and answers

These are examples from maintainer responses to reports, mostly about v2.0.14, collected on November 10, 2026.
They describe what was reported and suggested at that time. **Use the linked trackers for current status and advice.**
This page does not maintain a separate list of open or fixed bugs. A report closed as a duplicate is not evidence of a fix.

## Quick lookup

| Symptom | Follow the source |
|---|---|
| [Incomplete compressed frame](#the-build-says-a-compressed-file-ends-before-its-frame-completes) | [#1996](https://github.com/NotRexed/Hookshot/issues/1996) |
| [DLSS SDK download fails](#nvidias-dlss-sdk-could-not-be-downloaded) | [#1962](https://github.com/NotRexed/Hookshot/issues/1962) |
| [Builder stays at reading game files](#the-builder-stays-at-reading-game-files) | [#1876](https://github.com/NotRexed/Hookshot/issues/1876) |
| [Game closes after Play](#the-game-closes-immediately-after-play) | [#1288](https://github.com/NotRexed/Hookshot/issues/1288) |
| [Gohma stops attacking](#gohma-walks-into-a-wall-or-stops-attacking) | [#1742](https://github.com/NotRexed/Hookshot/issues/1742) |
| [HUD ghosts with frame generation](#the-hud-ghosts-or-shimmers-with-frame-generation) | [#1635](https://github.com/NotRexed/Hookshot/issues/1635) |
| [FPS stays low after changing areas](#fps-stays-low-after-changing-areas) | [#1400](https://github.com/NotRexed/Hookshot/issues/1400) |
| [Invisible dungeon walls on an older GPU](#dungeon-walls-or-blocks-are-invisible-on-an-older-gpu) | [#1001](https://github.com/NotRexed/Hookshot/issues/1001) |
| [Steam Deck freezes or loses geometry](#steam-deck-freezes-or-has-missing-dungeon-geometry) | [#1000](https://github.com/NotRexed/Hookshot/issues/1000) |
| [Controller layout mismatch](#controller-buttons-do-not-match-the-selected-layout) | [#1655](https://github.com/NotRexed/Hookshot/issues/1655) |
| [AMD texture problems](#textures-look-low-resolution-or-corrupted-on-amd) | [#1006](https://github.com/NotRexed/Hookshot/issues/1006) |

## The build says a compressed file ends before its frame completes

In [the response to #1996](https://github.com/NotRexed/Hookshot/issues/1996#issuecomment-6781832382), the maintainer
traced the error to an incomplete game copy and recommended copying or dumping it again. The file size mentioned
in that report applies to that particular copy, not every supported input.

## NVIDIA's DLSS SDK could not be downloaded

[The response to #1962](https://github.com/NotRexed/Hookshot/issues/1962#issuecomment-6781832944) identified a
connection reset during download. The suggested options were retrying later or building without optional DLSS.
Use the thread for subsequent advice if the error persists.

## The builder stays at reading game files

The v2.0.14 report [#1988](https://github.com/NotRexed/Hookshot/issues/1988#issuecomment-6781829857) was redirected
to [#1876](https://github.com/NotRexed/Hookshot/issues/1876). Follow that tracker and include the exact stage, build,
and builder output if adding a report.

## The game closes immediately after Play

[The response to #2004](https://github.com/NotRexed/Hookshot/issues/2004#issuecomment-6783021365) pointed to
[#1288](https://github.com/NotRexed/Hookshot/issues/1288). Check that thread for current troubleshooting steps.
Include your OS, GPU, driver, build, and log when reporting the symptom.

## Gohma walks into a wall or stops attacking

[The response to #1927](https://github.com/NotRexed/Hookshot/issues/1927#issuecomment-6778842949) recommended a
60 FPS game cap for the reported fight behavior. The [explanation in #1742](https://github.com/NotRexed/Hookshot/issues/1742#issuecomment-6781800673)
described timers above 60 FPS. Check [#1742](https://github.com/NotRexed/Hookshot/issues/1742) and the
[current menu guidance](../readme.md#in-game-menu) before applying that advice to a newer build.

## The HUD ghosts or shimmers with frame generation

For v2.0.14, [the response to #1976](https://github.com/NotRexed/Hookshot/issues/1976#issuecomment-6781826704)
pointed to [#1635](https://github.com/NotRexed/Hookshot/issues/1635) and suggested changing frame pacing or the
frame-generation multiplier. [An earlier response](https://github.com/NotRexed/Hookshot/issues/1635#issuecomment-6778823477)
narrowed a case to 2× frame generation with pacing on.

Results differed between reports. [The reporter in #1953](https://github.com/NotRexed/Hookshot/issues/1953#issuecomment-6780086181)
said a restart helped temporarily before shimmering returned in another area. Read the tracker for current settings
and fixes rather than treating one report's result as a general solution.

## FPS stays low after changing areas

[The response to #2023](https://github.com/NotRexed/Hookshot/issues/2023#issuecomment-6783024595) redirected the report
to [#1400](https://github.com/NotRexed/Hookshot/issues/1400). Use the README's
[performance-reporting instructions](../readme.md#low-fps-or-stutter) and record which transitions trigger the drop.

## Dungeon walls or blocks are invisible on an older GPU

[The response to #1900](https://github.com/NotRexed/Hookshot/issues/1900#issuecomment-6778205354) connected missing
geometry on a GTX 1050 Ti to its lack of mesh shaders and pointed to
[#1001](https://github.com/NotRexed/Hookshot/issues/1001). That tracker covers subsequent fallback work and reports.

## Steam Deck freezes or has missing dungeon geometry

The v2.0.14 Steam Deck OLED report [#1956](https://github.com/NotRexed/Hookshot/issues/1956#issuecomment-6780103592)
was redirected to [#1000](https://github.com/NotRexed/Hookshot/issues/1000). Follow it for current Linux/Steam Deck
advice. AMD-on-Windows reports have a separate [tracker, #996](https://github.com/NotRexed/Hookshot/issues/996).

## Controller buttons do not match the selected layout

[The response to #1923](https://github.com/NotRexed/Hookshot/issues/1923#issuecomment-6778840222) pointed to
[#1655](https://github.com/NotRexed/Hookshot/issues/1655) for play and ocarina controls disagreeing with the selected
layout. Include the controller, Hookshot bindings, and the game's own control settings if adding a report.

## Textures look low resolution or corrupted on AMD

The RX 9060 XT report [#1986](https://github.com/NotRexed/Hookshot/issues/1986#issuecomment-6781829223) was redirected
to [#1006](https://github.com/NotRexed/Hookshot/issues/1006). Check that tracker and the README's
[texture-workaround guidance](../readme.md#amd-texture-workaround) for current advice and tradeoffs.
