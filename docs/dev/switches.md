# Switches

Switches are environment variables the game, the renderer and the build read. They turn on test and debug features,
override an in-game setting for one run, or work around a problem on a particular GPU or driver. Most players never
need one: the [in-game menu](../user/settings.md) has a row for everything a player normally changes.

- [Setting a switch](#setting-a-switch)
- [Finding every switch](#finding-every-switch)
- [Window and display](#window-and-display)
- [Graphics for one run](#graphics-for-one-run)
- [Upscalers, Reflex and Anti-Lag](#upscalers-reflex-and-anti-lag)
- [Video memory](#video-memory)
- [Shaders, pipelines and driver workarounds](#shaders-pipelines-and-driver-workarounds)
- [GPU debugging](#gpu-debugging)
- [Input](#input)
- [Audio](#audio)
- [Game, launcher and integrations](#game-launcher-and-integrations)
- [Scripted test runs](#scripted-test-runs)
- [Pictures, frames and logs](#pictures-frames-and-logs)
- [Time and profiles](#time-and-profiles)
- [Building](#building)

## Setting a switch

The running game reads a switch from its environment or from `hookshot_env.txt` in the game folder (the folder with
`image.bin` and `hookshot_options.ini`). The file has one `NAME=VALUE` a line; lines starting with `#` are notes, and
blank lines and lines without `=` are skipped. The game reads it once at the start, before anything else reads a
switch (`load_hookshot_env` in `host/hos_main.c`).

`hookshot_env.txt` is a file players pass around, so it accepts only some lines. The log names each line it leaves
out.

| Rule | Detail |
|---|---|
| Names | Only names starting with `RX_`, `HOS_`, `HOOKSHOT_`, `EDEN_`, `NVN_` or `SDL_`, made of `A`-`Z`, `0`-`9` and `_`. Never `HOS_ENV_FILE`, `SDL_DYNAMIC_API`, or an SDL name that loads a library (`SDL_VULKAN_LIBRARY` and other names with `_LIB` or `GL_DRIVER`) |
| Values | No path: a value with `/` or `\`, a drive letter (`C:`), a leading `~`, `.` or `..` is left out |
| Switches that name a file or folder | No value at all, not even a bare name: every name ending in `_FILE` or `_DIR`, `RX_VK_FRAME_LOG`, `HOS_PRESENT_TRACE`, and `HOS_AUDIO_DUMP`, `HOS_AUDIO_WB_DUMP`, `HOS_SHADER_DUMP`, `HOS_FS_OVERLAY`, `HOS_MODS`, `HOS_SAMPLE_ALL`, `HOS_WATCH`, `HOOKSHOT_BUILDER_HOME`, `RX_VK_SHOTS`, `RX_VK_SHOT_GO`, `RX_VK_FRAMELOG`, `RX_VK_HANG_DUMP`, `RX_VK_DUMP`, `RX_VK_DUMP_SPV`, `RX_VK_DUMP_MESH_SPV`, `RX_VK_DUMP_STAGES`, `RX_VK_DUMP_FAILED`, `RX_VK_IR`, `RX_DUMP_WGSL`, `RX_DUMP_SLOW_WGSL`, `RX_DUMP_TICS`, `RX_WGSL_OVERRIDE` |
| Timed presses | No value for `HOS_INPUT_SCRIPT`, `HOS_INPUT_LIVE` or `RX_VK_MENU_SCRIPT` |
| `RX_VK_DLSS_DIR` | The one path the file takes: a folder on this PC, not a network share (`\\server\...` or `//server/...`) |

`HOS_ENV_FILE=<path>`, set in the environment, makes the game read that file instead of `hookshot_env.txt`. That file
has none of the rules above: it can set any variable and any path. A scripted or A/B test run uses it to bring its own
switches and leave the player's `hookshot_env.txt` alone.

When a name is set both in the environment and in the file, the environment wins and the log says the file's line was
left out. Within the file, a later line for a name replaces an earlier one. `HOS_PGO` is read before the file, so set
it in the environment.

A switch that stands in for a menu row (`RX_VK_PACE`, `RX_VK_UPSCALE`, `RX_VK_FRAMEGEN_MULT`, `HOS_REALTIME_STEP`,
`HOS_DYNRES`, `HOS_OUTPUT_RES`, `RX_VK_ASTC_RGBA8` and others) applies to that run only. `hookshot_options.ini` keeps
the value chosen in the menu (`env_override` in `gpu/vk/vk_menu.cpp`), and the row shows that a switch has set it.

The build tools read their own switches from the environment only; `hookshot_env.txt` is the game's.

### Values

An on/off switch, shown as `(set)` in the tables below, is off when it is unset, empty, `0`, `false`, `off` or `no`
(any case) and on for any other value (`env_on` in `gpu/vk/compat/hookshot_env.h`; `kit.env_on` in Python). Some
switches are older and read their value as a number instead: for those the tables give the values that work, and
`1` and `0` are always safe.

### Switches and the shader cache

Switches that change the shader translation are part of the program cache's stamp (`disk_stamp` in
`gpu/vk/vk_shader.cpp`; `tests/test_program_stamp_knobs.py` checks the translator's). Changing one makes the next
start prepare the shaders again.

### Removed switches

A switch the game no longer reads is logged at the start with what replaced it (`removed_switch_notes` in
`host/hos_main.c`), for example `env: RX_VK_NO_NAN_GUARD is no longer read: use RX_VK_NAN_GUARD=0`.

## Finding every switch

This page lists the supported switches and the ones players are asked to try. The code reads several hundred more,
most of them one-off experiments. The comment where each is read says what it does. To list every name the game and
the renderer read:

```sh
grep -rhoE '\b(getenv|env_on|env_int|env_flag|env_float|env_switch|env_path)\s*\(\s*L?"[A-Z][A-Z0-9_]+"' host gpu \
  | grep -oE '"[A-Z0-9_]+"' | tr -d '"' | sort -u
```

`env_flag` is the WebGPU renderer's (`gpu/render`); `env_switch`, `env_float` and `env_path` are local helpers in
`gpu/vk`. A few switches are read through other helpers that take the name as a string (`menu_env_on`, `EnvSwitch`),
so `grep -rn '"<NAME>"' host gpu` finds where any one name is read. The build's switches are in `nx2/` and
`builder/`.

On this page, **Player** marks a switch that is safe for a player to put in `hookshot_env.txt`. The others are for
developers and testers.

## Window and display

| Switch | Values | What it does |
|---|---|---|
| `HOS_WINDOW_SIZE` | `<w>x<h>` | **Player.** The window's size in pixels, each side at least 64. Default 1280x720 |
| `HOS_FULLSCREEN` | `1` | **Player.** Starts in fullscreen; the Insert menu's Fullscreen row is then left alone |
| `HOS_OUTPUT_RES` | `<w>x<h>` | **Player.** The output resolution for this run, over the menu's row (`output_res` in `hookshot_options.ini`) |
| `HOS_HANDHELD` | `0`, `1` | **Player.** The handheld profile on or off for this run, over the menu's row |
| `HOS_ASPECT` | a ratio, such as `2.3889` | **Player.** The picture's aspect ratio (2.3889 is 3440x1440's). Default: the menu's Ultrawide row, which takes the main monitor's shape. The HUD, menus and movies keep the middle 16:9 |
| `HOS_WIDE_MAX_PX` | pixels | The most pixels a picture wider or narrower than 16:9 takes (`host/hos_wide_size.h`). Default 5120x2160's |
| `HOS_DYNRES` | `0`, `1` | **Player.** Render resolution for this run: `0` is 100%, any other value Auto |
| `HOS_FPS_MAX` | `61` to `1000` | **Player.** A frame rate cap for this run, over the Frame rate cap row. `1000` is Uncapped; a value of 60 or less is 60 |
| `HOS_DPI_UNAWARE` | (set) | **Player.** Windows: the game does not declare itself DPI-aware, so Windows scales the window |
| `HOS_WINDOW_NOACTIVATE` | (set) | Windows: the window opens behind the others and does not take the focus |
| `HOS_HEADLESS` | (set) | No window: the renderer draws offscreen, for screenshots and frame dumps. The menu's **Save my pipeline list** then opens nothing (no browser, folder or clipboard) |
| `RX_VK_STARTUP_SCREEN` | `0` | No start-up screen while the game starts and prepares its shaders |

## Graphics for one run

These go over the Insert menu's rows for one run; the options file keeps the menu's value.

| Switch | Values | What it does |
|---|---|---|
| `RX_VK_DEVICE` | `<n>` | **Player.** The graphics card listed as `vk: device <n>` in the log, over the GPU device row |
| `RX_VK_FRAMEGEN` | `0` | **Player.** No frame generation, whatever the menu says |
| `RX_VK_FRAMEGEN_MULT` | `2` to `8` | **Player.** The frame generation multiplier |
| `RX_VK_PACE` | `0`, `1` | **Player.** Frame pacing off or on |
| `RX_VK_UPSCALE` | `0`, `1`, `2` | **Player.** The upscaling filter: Off, Catmull-Rom, Lanczos |
| `RX_VK_FIFO` | (set) | **Player.** V-Sync On (FIFO), over the V-Sync row |
| `RX_VK_IMMEDIATE` | (set) | **Player.** V-Sync Off (immediate), over the V-Sync row |
| `RX_VK_LOW_SPEC` | (set) | **Player.** For a first run on a 4 GB card: starts with the Minimum (4GB) preset, frame generation and upscaling off. Applies only while there is no `hookshot_options.ini` |
| `RX_VK_AUTO_PRESET` | `0` | **Player.** The first start keeps the default Quality preset instead of choosing one for the card's memory (Minimum for an integrated GPU or up to 4.5 GB, Low up to 6.5 GB) |
| `RX_VK_AUTO_PRESET_VRAM_MB` | MB | The first start chooses its preset as if the card had this much memory, to try the choice on another card |
| `RX_VK_MOVIE_UPSCALE` | `auto`, `linear` | **Player.** `linear`: the movies get a plain linear upscale instead of the game's neural one. `auto` (default) keeps the networks on NVIDIA cards and switches to linear when a movie frame takes the GPU more than 40 ms; on cards that cannot run the networks' matrix multiplies natively, movies are always linear. The gameplay upscaler is not affected |
| `RX_VK_NETWORK_KEEP` | key prefixes, or `all` | Which neural networks run on a card without native matrix multiplies. Default: the gameplay upscaler's. `all`: every network, the movies' too, whatever `RX_VK_MOVIE_UPSCALE` says |
| `RX_VK_NAN_GUARD` | `0` | No NaN guard on float colour outputs. It is on by default: one NaN texel spreads through bloom into glowing blocks |
| `RX_VK_PRESENTS_AHEAD` | `1` to `8` | How many presents the game may hand over ahead of the replay. Default 2. Not `RX_VK_PRESENT_AHEAD` |
| `RX_VK_PRESENT_AHEAD` | `0` | Frame generation's copies into the window are submitted each at its own time. By default a set's copies go to the GPU together. Not `RX_VK_PRESENTS_AHEAD` |
| `RX_VK_REACTIVE` | `1` | A reactive mask for DLSS and FSR 3.1 (not FSR 4); off by default and not yet checked in the game (`gpu/vk/vk_reactive.h`). The scene's colour is copied before its blended draws that test depth without writing it (water, smoke, fire, glows); where the scene then differs from the copy, the upscaler leans on the current frame, so those smear and ghost less. A blended draw after the last transparent run, such as a full-screen fade, is in the mask too. The log's `vk: reactive mask:` lines say whether one is made |
| `RX_VK_REACTIVE_SCALE` | `0` to `64` | The mask is the difference times this. Default 1 |
| `RX_VK_REACTIVE_MAX` | `0` to `1` | The mask's maximum. Default 0.9 |
| `RX_VK_REACTIVE_DEBUG` | `1` | Shows the mask in the picture in magenta |

## Upscalers, Reflex and Anti-Lag

The upscalers themselves are described in [upscaling](../user/upscaling.md). These switches choose them for one run.

| Switch | Values | What it does |
|---|---|---|
| `RX_VK_DLSS` | `0`, `1`, `2` | **Player.** NVIDIA DLSS for this run: `0` never, `1` DLSS, `2` DLAA. Goes over the Upscaler row |
| `RX_VK_DLSS_PRESET` | a letter, or `0` | **Player.** The DLSS preset for this run, over the DLSS model row. `0`: NVIDIA's default. The log's `vk: NVIDIA DLSS: ... preset <letter>` line says which was asked for |
| `RX_VK_DLSS_DIR` | a folder | **Player.** Another folder NGX looks in for `nvngx_dlss.dll` (Linux: `libnvidia-ngx-dlss.so.*`). It uses the newest runtime it finds across its folders. On Linux this folder's whole path must be ASCII |
| `RX_VK_FSR4` | `0`, `1`, `2` | **Player.** AMD FSR 4 for this run: `0` never, `1` FSR 4, `2` FSR 4 Native AA. Goes over the Upscaler row |
| `RX_VK_FSR_DIR` | a folder | Another folder for AMD's FSR 4 DLLs. Not from `hookshot_env.txt`: use the environment or a `HOS_ENV_FILE` file |
| `RX_VK_FSR` | `0`, `1` | **Player.** AMD FSR 3.1 for this run: `1` uses it, `0` never. It goes over `RX_VK_DLSS` and `RX_VK_FSR4`: one upscaler runs at a time |
| `RX_VK_FSR_FG` | `0`, `1` | `1`: with Frame generation at 2x, FSR 3.1's frame interpolation makes the frame in between instead of the renderer's own. Off by default, because FSR 3.1 has no HUD-less colour and the HUD smears |
| `RX_VK_FSR_JITTER` | `0` | No camera jitter for FSR 3.1 |
| `RX_VK_FSR3_CHAIN` | `0` | FSR 3.1 upscales with inputs of its own (`vk_fsr3_inputs.cpp`: the camera's motion alone) instead of on `vk_temporal.cpp`'s chain with the skinned draws' own motion. For comparisons. The log says `vk: fsr3 on the chain: N frames drawn` on the chain |
| `RX_VK_DLSS_JITTER` | `0` | No camera jitter for DLSS and FSR 4 (and FSR 3.1 on the chain) |
| `RX_VK_DLSS_HDR` | `0` | DLSS keeps its LDR feature and clamped colour with Native HDR on, for comparisons |
| `RX_VK_FSR4_HDR` | `0` | With HDR on Native, FSR 4 keeps its LDR context and clamps colour at the paper white. By default it takes the game's HDR colour as linear light |
| `RX_VK_DLSS_LOG` | `1` | NGX's own log lines in `hookshot_log.txt` (`ngx:`) |
| `RX_VK_DLSS_TRACE` | `<frames>` | Logs one frame's large draws every that many frames. Applies to DLSS, FSR 4 and FSR 3.1 on the chain |
| `RX_VK_DLSS_DEBUG` | `motion`, `alternate` | `motion` shows the motion vectors; `alternate` the game's own upscale every other frame. Applies to DLSS, FSR 4 and FSR 3.1 on the chain |
| `RX_VK_REFLEX` | `0`, `1`, `2`, `-` | **Player.** NVIDIA Reflex for this run: Off, On, On + Boost. `-`: its extensions are not even enabled |
| `RX_VK_REFLEX_LOG` | `1` | With Reflex on, the driver's own latency timings averaged in the log every 300 frames |
| `RX_VK_REFLEX_SUBMIT_IDS` | `0` | Sends the queue submits without their game frame (`VkLatencySubmissionPresentIdNV`, `gpu/vk/vk_reflex.cpp`), for comparisons. With frame generation, Reflex's "to the GPU's end" timing then goes wrong by hundreds of ms |
| `RX_VK_ANTILAG` | `0`, `1`, `-` | **Player.** AMD Anti-Lag 2 for this run. `-`: its extension is not even enabled |

## Video memory

| Switch | Values | What it does |
|---|---|---|
| `RX_VK_LOW_VRAM_MIPS` | `0` | Turns off the low-memory texture rule: on the Minimum (4GB) preset, when the driver's budget is at most 4.5 GiB, sampled ASTC textures get a 1024 dimension limit and an 8 MiB threshold for leaving out their top mip levels (otherwise 2048 and 64 MiB). The budget is sampled at the first texture and kept for the session. `RX_VK_TEX_MAX_DIM` and `RX_VK_TEX_SKIP_MB` override the limit and the threshold separately |
| `RX_VK_VRAM_MB` | MB | **Player.** The texture cache's budget. Default: 45% of what the driver allows on a card with 8.5 GB or less, 70% on a larger one, at most 6 GB; at most 2560 MB on an integrated GPU; 4096 when the driver does not say. A smaller Quality preset can set a lower budget |
| `RX_VK_ASTC_RGBA8` | `0`, `1` | **Player.** ASTC textures decoded to RGBA8 for this run, over the Debug tab's ASTC as RGBA8 row. While it is set, the row shows "Set by RX_VK_ASTC_RGBA8" |
| `RX_VK_WB_MAX_KB` | KB | **Player.** GPU-written bindings larger than this are not copied back to guest memory. `1024` keeps the small results the CPU reads (the exposure meter) and skips the large culling lists and per-frame buffers, which can lift the frame rate where write-backs are heavy. `0` or unset: every written binding is copied |
| `RX_VK_MIRROR` | `0`, `1` | VRAM mirrors of the game's memory pools. On by default for discrete cards except GCN (RX 400/500, Vega) |
| `RX_VK_MIRROR_MB` | MB | The mirrors' budget. Default: an eighth of the card on cards of 6.5 GB or less, else a quarter, at most 3 GB |
| `RX_VK_COMPACT` | `0` | No VRAM compaction. Compaction moves textures that are not render targets out of sparsely used blocks a few a present so the blocks go back to the driver, and holds the driver's count at `RX_VK_COMPACT_PCT` of what it allows by letting go of render targets drawn over since and textures unused for ten seconds |
| `RX_VK_COMPACT_PCT` | `50` to `90` | Compaction's target share of what the driver allows. Default 85; textures unused for thirty seconds go at five points under it |
| `RX_VK_COMPACT_MB` | MB | The free space that starts a compaction run. Default 512 |
| `RX_VK_NO_WRITEBACK` | (set) | GPU writes to mirrored pools are not copied back to guest memory. An experiment, for A/B |
| `RX_VK_WB_DIFF` | `0` | Write-backs copy every byte instead of only what changed against a VRAM shadow |
| `RX_VK_WB_OBSERVE` | `1` | Diagnostics for actual mirror and shadow differences in the write-back diff pass: completed chunks and bytes in changed chunks every 600 submissions. Copy decisions do not change. See [write-back observations](writeback-observations.md) |
| `RX_VK_UB_WORD_HASH` | `0` | Cached uniform words use the plain low-address-bit index instead of mixing in the upper address bits. For A/B |
| `HOS_GPU_ALLOC_RETRY` | `0` | A model's material-block allocations from a full heap are not retried in the heap's parents (`host/oot_heap_retry.c`) |
| `HOS_GPU_ALLOC_TEST_FAIL` | `<n>`, or `<gpu>,<cpu>` | A test: the first n of those allocations of each kind (or that many GPU-memory and CPU-buffer ones) are refused, as a full heap would, so the retry runs |

## Shaders, pipelines and driver workarounds

| Switch | Values | What it does |
|---|---|---|
| `RX_VK_FETCH_BOUNDS`, `RX_VK_NAN_BITS`, `RX_VK_GATHER_OFFSET` | `0`, `1` | The shader translation's vendor and driver workarounds (`gpu/vk/vk_vendor.h`) off or on for one run, whatever the GPU; the log's `vk: vendor fixes` line says which are on. By default: out-of-bounds texel fetches answered with 0 on every GPU but NVIDIA's; NaN tests on a value's bits on AMD's older Windows shader compiler (RX 5000 and RX 6000); gathers nudged by 1/512 of a texel on AMD's and Intel's drivers |
| `RX_VK_GM_LOOP` | `0`, `1` | How a global memory access's storage-buffer tables are searched: in a loop (`1`) or written out entry by entry (`0`). On by default on Intel, whose compiler didn't finish the culling programs with the entries written out |
| `RX_VK_MESH_NOCULL` | key prefixes | **Player.** Turns off culling in the task shaders whose native code key starts with one of the prefixes: every meshlet is drawn and the rasterizer clips what is off screen. On a Steam Deck, `2c56dc1006942f74` avoids the GPU hang in Kokiri Forest and the Great Deku Tree without leaving anything out. It costs some GPU time, so it is off unless set. The log says "culling off, every meshlet drawn" for each task shader it changed |
| `RX_VK_SKIP_CODE` | key prefixes | **Player.** Leaves out the draws of every program with a stage whose native code key starts with one of the prefixes (the keys the log prints after "its code:"). A workaround: on a Steam Deck `2c56dc1006942f74` also avoids the hang, but the models those task + mesh programs draw are missing. Prefer `RX_VK_MESH_NOCULL` |
| `RX_VK_FALLBACK_PHI_LIMIT` | `<n>` | RADV on GCN 1-4 cards (RX 400/500, R9 2xx/3xx/Fury): a mesh-fallback compute stage with more than this many phis isn't built and its draws are left out (default 50000; `0`: no limit; the limit in use is logged). That compiler didn't finish the two biggest mesh programs (`gpu/vk/fallback_size_policy.h`) |
| `RX_VK_TASK_MESH_FALLBACK` | `0`, `1` | **Player.** Task + mesh draws through the compute fallback (`1`) or the driver's mesh shaders (`0`). Default: the fallback on AMD Navi 21 and Navi 22 on Windows (RX 6800, 6800 XT, 6900 XT, 6950 XT, 6700 XT), where the native path times out the driver; the Mesh shaders row's Native turns it off |
| `RX_VK_ROBUST` | `0`, `1` | **Player.** Bounds-checked buffer access off or on for this run, over the Robust buffers row (default on) |
| `RX_VK_SAMPLER_CACHE` | `0`, `1` | **Player.** The sampler cache off or on, over the Sampler cache row |
| `RX_VK_NO_PROGRAM_CACHE` | (set) | **Player.** Neither reads nor writes `hookshot_programs.bin` and the pipeline notes, to rule the cache out |
| `RX_VK_DESC_REUSE` | `0`, `1`, `never` | Over the Descriptor reuse row: `0` Off (a draw keeps the previous draw's descriptors while no registration was made), `1` On (through registrations of slots it does not sample; the default), `never` every draw builds its own |
| `RX_VK_PRECOMPILE` | `0`, `1` | The shader preparation before the title off or on. On in release builds (`RX_RELEASE=1`, as the builders make) |
| `RX_VK_PIPE_SKIP` | `0`, `1`, `2` | Unset or `1`: wait for shader translation; a pending pipeline is skipped only for attachment-only draws whose targets hold an earlier frame. `0`: wait for every pipeline too. `2`: also skip untranslated draws with persistent targets, which can omit writes made before the shader is known. Translated draws that write memory always wait |
| `RX_VK_SKIP_PROG` | key prefixes, or `-` | Leaves out the draws of these programs. Default: program `53509044401d78d2`, only while its targets have no view. `-` leaves out none |
| `RX_VK_DRIVER_FAULTS` | `0`, `1`, `2` | Programs the driver's compiler faulted on. `1` (default): left out for the rest of the run and, through `hookshot_driver_faults.txt` beside the executable, on later runs with the same driver; on AMD one program's builds go to the driver one at a time. `0`: they are asked of the driver again. `2`: one at a time on every driver |
| `RX_VK_NOOPT` | (set) | Pipelines built without the driver's optimisations |
| `RX_VK_SKIP_COMPRESSED_OVER_RT` | `1` | A compressed (ASTC, BC, ETC2/EAC) texture made over storage render targets is not uploaded. Bosses and new enemies then draw blue the first time; for comparisons |
| `RX_VK_DUMP_FAILED` | a folder | The native code of every program that does not translate, for `nx2/lower_test.py`. Game data: keep it local |

## GPU debugging

| Switch | Values | What it does |
|---|---|---|
| `RX_VK_VALIDATION` | (set) | The Khronos validation layer |
| `RX_VK_CHECKPOINTS` | `0` | No NVIDIA checkpoints. They are on by default; after a lost device they name the draw it stopped at |
| `RX_VK_HANG_DUMP` | a file | Windows: every thread's stack written to the file once no frame was shown for `RX_VK_HANG_SEC` seconds |
| `RX_VK_HANG_SEC` | seconds, at least 5 | Default 20 |
| `RX_VK_ASYNC` | `1` | The replay on a thread of its own instead of the game's submitting thread |
| `RX_VK_PRESENT_THREAD` | `1` | On (off by default: the game's thread presents). Where the device has a second queue that can present (a second queue of the replay's family, else a compute family's), each present goes to a thread and queue of its own once the frame's copy into the window is done, and the game's thread carries on. At most one present is outstanding |
| `RX_VK_GPU_HANG_SEC` | `<s>` | GPU work that finishes nothing for this long (default 30) counts as a hang: the lost-device report, then the game ends. `0`: the stall is logged and the game waits |
| `RX_BACKEND` | `vulkan`, or another name | Unset or `vulkan`: `hookshot_vk.dll`. Any other value: the WebGPU renderer, when the executable was built with one |
| `HOS_TRACE` | `1` | Every Horizon OS call logged, as the `--trace` argument does |
| `HOS_VCORES` | `0` | No virtual cores |
| `HOS_CORES` | `1` to `8` | The cores the game sees. Default 6, or the game's own core setup when it has one |
| `HOS_RESERVE_CORE` | `0`, `1` | `0`: no core kept for the replay. By default one is kept with 8 or more logical processors, except on Windows where the game is kept to the cores of the largest L3 cache. `1` keeps one there too |

## Input

Controls and rebinding are in [controls](../user/controls.md).

| Switch | Values | What it does |
|---|---|---|
| `HOS_INPUT_BACKGROUND` | `0`, `1` | **Player.** `1`: physical controllers keep playing while the window is behind another one, as the Controller in background row does; `0` overrides that row. Keyboard and mouse always stay with the foreground window |
| `HOS_MOUSE_SENS` | a number, such as `1.5` | **Player.** The mouse camera's sensitivity, over the Mouse sensitivity row. While it is set, `-` and `=` change it and keep it in `<user>/mouse_sens.txt` |
| `HOS_MOUSE_INVERT_Y` | (set) | **Player.** Inverts the mouse camera's vertical axis, as the Invert mouse vertical row does |
| `HOS_MOUSE_NATIVE` | `0`, `1` | **Player.** The Mouse camera row for this run: `1` Native, `0` As the stick |
| `HOS_HD_RUMBLE` | `0` | **Player.** No HD rumble for Switch Pro Controllers and Joy-Cons, plain rumble instead |
| `HOS_XINPUT` | (set) | **Player.** Windows: XInput controllers are polled even while SDL has a controller open. By default XInput is read only when SDL has none, so a pad that Steam Input or a wrapper also shows as XInput is not read twice |

## Audio

| Switch | Values | What it does |
|---|---|---|
| `HOS_AUDIO` | `0` | **Player.** No sound device is opened; the mixer still runs |
| `HOS_AUDIO_DEVICE` | a device number | **Player.** Windows: the output device to open first, by its waveOut number. Default: the system's default device, followed when it changes. On Linux SDL follows the default device |
| `HOS_AUDIO_MUTE` | (set) | Windows: the device is opened and fed as usual, at volume 0. For test runs that need real audio timing |

## Game, launcher and integrations

| Switch | Values | What it does |
|---|---|---|
| `HOS_LANGUAGE` | a code from `language.txt` | **Player.** The game's language for this run, over `language.txt` |
| `HOS_TEXT_SPEED` | `0` to `3` | **Player.** Text speed for this run: Normal, 2x, 4x, Instant |
| `HOS_TEXT_SIZE` | `0` to `4` | **Player.** Text size for this run: Original, 110%, 125%, 150%, 175% |
| `HOS_REALTIME_STEP` | `0`, `1` | **Player.** Game speed for this run: `0` Per frame, `1` Real time |
| `HOS_DISCORD` | `0` | **Player.** No Discord Rich Presence |
| `HOS_DISCORD_APP_ID` | a Discord application ID | Rich Presence under another Discord application |
| `HOOKSHOT_NO_UPDATE_CHECK` | `1` | **Player.** No check for a newer release at the start |
| `HOOKSHOT_NO_AV1_NOTICE` | (set) | **Player.** Windows: no window telling the player to install the AV1 Video Extension when no AV1 decoder is found. The log still says so |
| `HOS_OOT_CHEATS` | `1` | **Player.** Turns on the Debug tab's Debug tools, as the Debug tools row does |
| `HOS_MODS` | a folder | **Player.** Where the game looks for mods instead of its `mods` folder. Not from `hookshot_env.txt`: set it in the environment (see [mods](../user/mods.md)) |

## Scripted test runs

| Switch | Values | What it does |
|---|---|---|
| `HOS_CONTROL` | a socket path, or a pipe name on Windows | Turns on the [control bridge](automation.md), a local socket a tool or coding agent drives the running game through |
| `HOS_CONTROL_MEM` | `ro`, `rw` | Lets the control bridge read (`ro`) or also write (`rw`) guest memory |
| `HOS_INPUT_SCRIPT` | presses | Presses timed from the game's first controller read (format below) |
| `HOS_INPUT_LIVE` | a file | A file the test appends lines of presses to, read every 30 ms; each line's times count from when it is read. A line `!cheat <n>` sends a Cheats page action, `!synclog` logs the NVN syncs (`!dump`, `!shots`, `!rdoc` and `!flasharm` are the WebGPU renderer's) |
| `HOS_INPUT_FRAME_CLOCK` | `1` | The script's time runs at 60 game frames a second instead of the wall clock |
| `HOS_INPUT_EXCLUSIVE` | (set) | The script alone drives the game until 5 s after its last press. Without it, the player's devices add to the script's presses. It is not a focus override |
| `HOS_INPUT_SCRIPT_BACKGROUND` | (set) | Every device counts while the window is behind another one |
| `RX_VK_MENU_SCRIPT` | `<seconds>:<key>,...` | Timed Insert menu keys: `INS`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `ESC`, `ENTER`, `TABL`, `TABR` |
| `RX_VK_UI_PROMPTS` | `pad`, `keys` | The menu's button prompts for a controller or the keyboard, whatever was used last. For screenshots |
| `RX_VK_UI_GAME_FONT` | `0` | The menu, the counter and the start-up screen in the included Libertinus font, not the game's own |

Presses are `<seconds>:<button>[+<button>...][/<ms>]`, separated by commas, for example `2:A,5.5:LUP/1500,9:ZL+R`.
The buttons are `A B X Y L R ZL ZR PLUS MINUS LS RS LEFT UP RIGHT DOWN`, and the sticks pushed to their edge are `LUP
LDOWN LLEFT LRIGHT RUP RDOWN RLEFT RRIGHT`. A press is held for 200 ms unless `/<ms>` says otherwise. The names are
case-sensitive, and an unknown one is ignored.

Scripted input is applied before the window-focus check, so a log line saying the game window is not in front does not
mean the presses were discarded. `HOS_HEADLESS` and `HOS_WINDOW_NOACTIVATE` change how the window is created, not this
routing. The game still has to reach a state that reads the controller.

`scripts/run-vk.ps1 [-Window] [-Seconds 120] [-Name x]` makes a muted test run on Windows, with screenshots in
`work/runs/<name>/shots`; it sets `HOS_AUDIO=0` unless given `-Sound`.

## Pictures, frames and logs

| Switch | Values | What it does |
|---|---|---|
| `RX_VK_SHOTS` | a folder | A PNG every `RX_VK_SHOT_EVERY` presents, as `vk_<present>.png` |
| `RX_VK_SHOT_EVERY` | presents | Default 300 |
| `RX_VK_SHOT_W`, `RX_VK_SHOT_H` | pixels | The screenshots' size. Default 1280x720. A value that is not a positive decimal integer, or a size the device, the readback or the PNG writer cannot hold, turns screenshots off for the run with one log line; it never falls back to another size |
| `RX_VK_FLASH` | `1` | The flash detector, with `RX_VK_SHOTS` and `RX_VK_SHOT_EVERY=1`: each screenshot is compared with its two neighbours on a 64x36 grid of mean colours, and the frames around a flash are written and the next frame dumped |
| `RX_VK_FRAMELOG` | a file | Every frame shown, as 320x180 pictures, while `<file>.go` exists. `python -I scripts/framelog.py <file>` finds the flashes. Not `RX_VK_FRAME_LOG` |
| `RX_VK_DUMP` | `<present>[+<count>][,...]` | Every step of the frame after that present as PNGs, in `dump_<present>` under `RX_VK_DUMP_DIR` (or `RX_VK_SHOTS`, or the current folder) |
| `RX_VK_DUMP_DIR` | a folder | Where `RX_VK_DUMP` writes |
| `RX_VK_DUMP_STEPS` | `<lo>-<hi>` | Only these steps of a dumped frame |
| `RX_VK_DUMP_PROGS` | keys | Only the draws of these programs |
| `RX_VK_PASS_TRACE` | `1` | The passes of the last frames, logged at a flash or a dark frame |
| `RX_VK_PASS_TRACE_AT` | `<n>` | With `RX_VK_PASS_TRACE`: every n-th present instead |
| `RX_VK_PROBE` | `1`, `2` | The centre texel after every pass: `probe_<frame>.txt` at a flash (`1`), or `probe_all_<n>.txt` at speed (`2`). `python -I scripts/probe.py` reads them |
| `RX_VK_PRESENT_LOG` | `1` | Logs the presentation geometry when it changes: texture size, crop, clipped size, swapchain size, destination rectangle, host aspect, and the route taken (`direct`, `scaled`, `clear` or `hdr`). Filter, sharpness and frame generation values are labelled `*-request`. Up to 256 changes a run are logged, then one suppression notice |

`tests/test_capture_dimensions.py`, `tests/test_flash_sampling.py` and `tests/test_present_geometry_trace.py` check
the screenshot size rules, the flash detector's sampling and the geometry log without a GPU or game data.

## Time and profiles

| Switch | Values | What it does |
|---|---|---|
| `HOS_PROFILE` | seconds | Every interval, the busiest threads in the log. It also starts the samplers below |
| `HOS_SAMPLE` + `HOS_SAMPLE_FILE` | a thread, a file | One thread's stacks, sampled every millisecond (needs `HOS_PROFILE`). `python -I scripts/prof.py <file>` reads them |
| `HOS_SAMPLE_ALL` | a file | Every game and renderer thread every 2 ms while `<file>.go` exists (needs `HOS_PROFILE`). `scripts/crit.py`, `scripts/vkprof.py`, `scripts/hotlist.py` and `scripts/cpu_report.py` read it; see the [CPU profile](cpu-profile.md) |
| `HOS_CHAIN` | a file | While `<file>.go` exists, records every blocking wait of a game thread, every signal that can end one, every sleep and every present (time, thread, object, caller), written to `<file>` when `<file>.go` goes away. `python -I scripts/chain.py <file> [<HOS_SAMPLE_ALL file>]` walks each frame back from its present and prints its critical path by thread |
| `RX_MAPS` | the game folder | For the profile readers on Linux: name frames from that folder's `hookshot` and `hookshot_vk.so` |
| `HOS_THREAD_TIMES` | seconds | Every interval, the threads that used over 5% of a core |
| `HOS_FPS_LOG` | (set) | The game's frame limiter, VRR flags and nominal rate every 300 presents, and the game clock's speed (1.000 is real time) |
| `HOS_PRESENT_TRACE` | a CSV file | A line per game present with host-clock times: before queue flushing, around the renderer call, after virtual-core reacquisition, and at the return. CPU wall times, not GPU completion or scanout; with async rendering it measures the enqueue call |
| `RX_VK_FRAME_LOG` | a CSV file | A line per present: frame, seconds, frame time in ms. With `HOS_HEADLESS` the times are CPU intervals after the offscreen copy is submitted, without display waits. Not `RX_VK_FRAMELOG` |
| `RX_VK_PASS_TIMING` | `1`, `2` | GPU time per pass (`2`: per program too), logged every 600 presents |
| `RX_VK_SLOW_LOG` | ms | The replay's times for each frame that took longer than this |
| `HOS_PGO` | a file | In a run of an `RX_PGO=gen` build: `<file>.reset` clears the counters, `<file>.dump` writes them to `<file>`. Set it in the environment: it is read before `hookshot_env.txt` |

## Building

The build reads these from the environment. [Building](building.md) has the build itself. A build reads and writes
tens of gigabytes; on a hard drive `make_game.py` warns and builds anyway.

| Switch | Values | What it does |
|---|---|---|
| `HOOKSHOT_JOBS` | `<n>` | Compilers at once (or `--jobs`). Default one per CPU thread, each started when the free memory holds it |
| `HOOKSHOT_MEM_GATE` | `0` | Starts compilers without the free-memory check |
| `HOOKSHOT_LIFT_JOBS` | `<n>` | Processes that write the lifted C and make its edits. Default the cores, at most 16, and one per 2 GB of free memory |
| `RX_HOT_OPT` | `O1`, `O2` | The optimisation level of the hot pieces (`code_hot_*.c`), default `O2`. `O1` for [a faster build for development](building.md#a-faster-build-for-development) |
| `HOOKSHOT_KEEP_BUILD_FILES` | `1` | Keeps the lifted C and the objects after a build, so the next one compiles only what changed |
| `HOOKSHOT_MINGW` | a folder | The llvm-mingw to build with |
| `HOOKSHOT_MSVC` | `1` | The Visual Studio route instead |
| `HOOKSHOT_VULKAN_HEADERS`, `HOOKSHOT_SPIRV_HEADERS`, `HOOKSHOT_VMA_HEADERS` | folders | The Vulkan, SPIR-V and VMA headers, when they are not under `/usr` or in the CPM cache |
| `RX_CPM` | a folder | The CPM package cache (Vulkan and SPIR-V headers, VMA, FFmpeg, dav1d). Default `cpm` in the clone |
| `WGPU_NATIVE` | a folder | wgpu-native, for the WebGPU renderer |
| `HOOKSHOT_NGX_SDK` | a folder | NVIDIA's NGX SDK, fetched by `scripts/ngx_sdk.py`: the build then offers DLSS |
| `HOOKSHOT_FSR` | `1` | For `nx2/build.py`: build with FSR 4 (`make_game.py --fsr`) |
| `HOOKSHOT_FFX_SDK` | a folder | Where `make_game.py --fetch-fsr-runtime` keeps AMD's DLLs between builds |
| `RX_TARGET` | `windows` | On Linux: build the Windows game, with llvm-mingw's Linux build in `HOOKSHOT_MINGW` |
| `RX_RELEASE` | `1` | A release build (`make_game.py` sets it): no console window, the shaders prepared before the title |
| `RX_PGO` | `gen`, or a file | The hot code counting its branches for a profile, or built with one (`make_game.py` passes the shipped profile) |
| `RX_MARCH` | a CPU level | The CPU level to build for. Default this PC's: `x86-64-v3`, else `x86-64-v2`, else `x86-64` |
| `RX_VK_ONLY` | `1` | Only the Vulkan back end, with no lift |
| `OOT_WORK` | a folder | The work folder, instead of `work/` |
| `OOT_DUMP`, `OOT_EXEFS`, `OOT_ROMFS` | folders | The dump's folders, over `work/dump.txt` |
