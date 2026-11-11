# Tested configurations

What has actually been run, where, and how it went: one row per test run, newest first. The README's
[status table](../readme.md#project-status) sums this up by vendor; this page keeps the runs themselves, so a
regression can be traced to a build and a driver, and so the next tester knows what is already covered.

Add a row for your own runs (a PR, or paste it in an issue and a maintainer adds it). A run that worked is as useful as
one that did not. Keep it to facts you saw: the build (`hookshot vX.Y.Z-N-gHASH` from the first line of
`hookshot_log.txt`), the hardware and driver, the settings that matter, where in the game, and what you measured.
Frame rates come from `hookshot_log.txt` ("N presents, X fps") at a named spot, standing still unless the row says
otherwise.

## Runs

| Date | Build | OS / desktop | GPU / driver | CPU / RAM | Settings | Where | Result |
|---|---|---|---|---|---|---|---|
| 2026-11-10 | v2.0.14 (source 3a9998c3), Hookshot Builder; later v2.0.14 + the scale-image SAMPLED fix (as in #1940) | Windows 11 Pro 26200, fullscreen | RTX 5090, 621.14 | Ryzen 7 5800X3D, 64 GB | 3840x2160 output, DLSS Quality (67%), Steam Controller (2026) | Castle Town market, Kokiri Forest | Plays well. On the release: HDR Expanded a black picture, Native flat (#1613); with the fix Expanded is right, frame generation 3x too. One crash in `nvoglv64.dll` (0xc0000005) after about 17,000 frames with frame generation 5x. Steam Controller started from Steam: no gyro until Steam's `SDL_GAMECONTROLLER_IGNORE_DEVICES` and `SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD` were cleared (#1897) |
| 2026-11-10 | v2.0.11-449-g1987d8c (main caaee0b + the VRAM compaction branch, unmerged then) | Windows 11, no window (unattended, scripted input) | RTX 4070 SUPER 12 GB, 617.42 | Ryzen 9 9950X3D (SMT off), 32 GB | 2560x1440, DLAA, `RX_VK_COMPACT=1`; other programs open (10.2-10.5 GB of VRAM allowed) | Hyrule Field, a scripted five-minute walk (not standing still) | Two runs: 58.2, 58.6 fps mean; VRAM 8.3, 7.9 GB; GPU time over 12.5 ms a frame in 6 of 122 and 10 of 123 120-present windows; 88, 62 frames over 33 ms; 1% low 21.1, 26.5 fps. No device lost |
| 2026-11-10 | as above | as above | as above | as above | as above, without the switch | as above | Two runs: 53.2, 54.4 fps mean; VRAM 9.5, 9.6 GB; the write-back shadows given back in 73 of 111 and 80 of 114 windows; GPU time over 12.5 ms in 69 of 111 and 55 of 114; 107, 112 frames over 33 ms; 1% low 19.4, 20.6 fps. No device lost |
| 2026-11-10 | host `v2.0.11-438-gcd544a7` (source `8bdd7a54`); renderer main `8bac8aa` + #1502 + the host-clock capture change | Windows 11 Home N, 26300 | RX 9070 XT 16 GB, 32.0.32015.12012 | Ryzen 7 5700X3D, 64 GB | 2560x720 window, 32:9 camera, serial, FG off, dense capture, core validation; fresh prepared shader bank | Boot, title, save load; gameplay not reached | 96 s: 1,476 consecutive original capture records; all 1,461 records covered by the flushed native trace align one-to-one with native returns. Movement window rejected: no filled gameplay interval. No new validation IDs; existing `02251`, and two `08737` errors during full preparation. No gameplay speed or performance claim |
| 2026-11-10 | v2.0.11-447-gcbe49eb, sampler admission branch (main 8bac8aa + sampler checks + staging fixture repair) | Windows 11, windowed | RTX 5070 Ti, 621.01 | Ryzen 7 9800X3D, 32 GB | 3440x1440 picture, native upscaling, fixed FG 2x, 1 MB recording streams; serial and parallel replay (2 workers, batch 1) | Kokiri Forest, inside Link's house; copied checkpoint | Both runs rendered the scene, maximized/restored (client 1444x720 to 1440x829 and back), and exited normally. Six representative PNGs decoded at 3440x1440; original checkpoint hashes unchanged. Healthy-path validation only; no FPS comparison or native OOM recovery claim |
| 2026-11-10 | main b2bb214 (+ #1447 #1451 #1520 #1660 #1619 #1448 #1654 #1612 #1600, unmerged then) | Ubuntu 26.04.1, KDE Plasma 6.6.6 Wayland | RTX 4070 Ti 12 GB, 595.99.02 | Ryzen 7 9800X3D, 32 GB | 3840x2160 output, DLSS Quality, no mods | Hyrule Castle road (child) | 48-50 fps. Same spot at 2560x1440 output: 56.3 fps. No device lost, saves written |
| 2026-11-10 | main b2bb214 + #1459 (Dear ImGui menu) | as above | as above | as above | as above, windowed | Title, Hyrule Castle road | F1 menu, help box, prompts, the game's font and the FPS badge all correct; 60 fps |
| 2026-11-10 | main b2bb214 | as above | as above | as above | HDR on | start-up | KDE offers an HDR10 surface (`vk: HDR: an HDR10 surface (format 58)`) |
| 2026-11-09 | main 7eac5bf | as above | as above | as above | 3840x2160, DLSS Quality, no mods | Hyrule Castle road | 52.8 fps (replay submit 17.5 ms, memory sync 4.8 ms, GPU 12.8 ms) |
| 2026-11-09 | main 7eac5bf | as above | as above | as above | fullscreen (`HOS_FULLSCREEN=1`) | Hyrule Castle road | fullscreen works, no device lost |
| 2026-11-09 | v2.0.11-142 (7dbdcdc) | as above | as above | as above | 3840x2160, DLSS Quality | Water Temple 1F, Hyrule Castle road, Deku Tree 2F | Water Temple walls missing with the 23.3 GB dump, drawn with stand-in textures (#1308) or a complete dump. Slingshot and bow aiming: no fps change (51-52 fps, #1305). Pause / unpause: no freeze |

| 2026-11-10 | host `v2.0.11-741-gd003a75` (source `74e73a05`), combined #1541/#1542/#1543/#1544 on main `1392ea3` | Bazzite, KDE Wayland | RTX 5080, 615.78.08 | Ryzen 7 9850X3D, 32 GB | Saved player settings: 5120x1440 picture, 3840x1080 scene, 2560x720 mailbox window; FG off, external neural effect off; silent, copied saves | Hyrule Field child checkpoint: 6 s standing, four 2 s camera/walking phases | Native present-call mean 59.98 FPS standing, 57.79/59.95 FPS camera, 59.98/59.97 FPS walking. First camera pan had two intervals over 50 ms, max 73.70 ms. Source suites pass; not a constant-60 or physical-display timing claim. Warm Forest movement test completed at 57.03-60.01 FPS (max 27.38 ms). Earlier Forest and Market attempts hit the local 3 GiB free-swap guard; no completed Market event result. Enabled external neural effect: all Forest phases completed, 42.58-47.39 FPS, max 31.01 ms; model/composition counters advanced |

| 2026-11-10 | host `v2.0.11-769-g9aaf160` (source `5ba993f3`), combined #1541/#1542/#1543/#1544 on main `117eae7`, local F10 companion hook | Bazzite, KDE Wayland | RTX 5080, 615.78.08 | Ryzen 7 9850X3D, 32 GB | Same saved settings as the combined 1392ea3 run above; FG and external neural effect off; current generated output-size hooks, silent copied save | Hyrule Field child: 6 s standing, four 2 s camera/walking phases | All phases completed, native present-call means 59.82-60.05 FPS. Warm smoke test only, not an uncached or whole-game performance result. Player build installed after checking copied-save gameplay |

## Limits of the original RTX 4070 Ti runs

- Real mouse aiming with Mouse camera = Native after #1462 (the camera states were traced, but not tested with a real mouse).
- Frame generation at 120 Hz or above (the displays here top out at 75 Hz).
- HDR output on an HDR monitor (the surface is offered, the picture was not judged on one).
