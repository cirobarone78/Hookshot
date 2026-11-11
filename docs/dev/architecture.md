# Architecture

Hookshot is a native x86-64 Windows and Linux build of the Switch 2 *The Legend of Zelda: Ocarina of Time*. The
game's AArch64 code is translated to C ahead of time from the player's own dump and compiled with clang. The parts
of Horizon OS and the Nintendo SDK the game talks to are implemented natively, and the game's NVN2 graphics work is
recorded and replayed on Vulkan. Nothing is emulated: there is no CPU interpreter or JIT and no emulated GPU.

This page describes how the pieces fit and the rules the code keeps. How to build and run it is in
[building](building.md) and [running](running.md); the switches named here are listed in [switches](switches.md).

- [The pieces](#the-pieces)
- [From dump to game folder](#from-dump-to-game-folder)
- [The host layer](#the-host-layer)
- [Graphics: recording and replay](#graphics-recording-and-replay)
- [Shaders](#shaders)
- [Threads](#threads)
- [GPU replay rules](#gpu-replay-rules)
- [Resource rules](#resource-rules)
- [Textures, buffers and recording streams](#textures-buffers-and-recording-streams)
- [Presentation](#presentation)
- [Upscalers and frame generation](#upscalers-and-frame-generation)
- [Pipeline and program caches](#pipeline-and-program-caches)
- [Capture and frame logs](#capture-and-frame-logs)
- [Lineage and third-party code](#lineage-and-third-party-code)

## The pieces

| Directory | What it is |
|---|---|
| `nx2/` | The build pipeline, in Python: reading the dump, lifting the code to C, compiling and linking, the game folder (`make_game.py`) |
| `third_party/a64-kit/` | The AArch64 lifter, NSO loader and guest runtime that `nx2/` builds on |
| `host/` | The host layer: Horizon OS and the SDK's OS-facing functions, the window, input, audio, video, files, and the NVN2 recorder |
| `host/posix/` | Win32 calls the host layer makes, implemented on POSIX for Linux, and the SDL window |
| `gpu/vk/` | The Vulkan back end: the replay, textures, shaders, pipelines, presentation, upscalers, the Insert menu |
| `gpu/vk/eden/` | Eden's shader recompiler, with Hookshot's changes |
| `gpu/render/` | The record format shared by recorder and replay (`rx_nvn.h`), and a WebGPU renderer used only when the build has wgpu-native |
| `builder/` | Hookshot Builder: the Windows app, the Linux launcher and updater, the Windows setup |

A built game folder has two binaries:

| | Windows | Linux |
|---|---|---|
| The game: lifted code and `host/` | `hookshot.exe` | `hookshot` |
| The Vulkan back end: `gpu/vk/` | `hookshot_vk.dll` | `hookshot_vk.so` |

The back end is a library of its own because Eden's recompiler and the WebGPU renderer's suyu copy share C++
namespaces (`Shader::`, `Common::`), so they cannot link into one binary. `host/rx_backend.c` loads it at start-up and
routes the host's `rx_*` calls to the table it returns. The two sides exchange function tables declared in
`gpu/vk/vk_api.h` (`MkwVkHost` and `MkwVkRenderer`), which carries an API version: both binaries are always built
together.

## From dump to game folder

`nx2/make_game.py` runs every step; the builders call it. The steps:

```
 .nup package, or exefs/ + romfs/ folders          (the player's dump)
        │  nx2/nup.py: extract the newest title; nx2/unpack.py: ZBIC-compressed NSOs rewritten as plain ones
        ▼
 exefs: rtld, main, subsdk*, sdk (NSOs) + main.npdm
        │  a64-kit's NSO loader + nx2/nso2.py (DT_RELR relocations)
        ▼
 image: modules placed in Eden's layout from 0x80000000, relocated, imports bound   (nx2/image.py)
        │  the HLE set hooked (nx2/standalone.py)
        │  function discovery and lifting: a64-kit + nx2/insn.py, lift_fixes.py, poll.py, chunks.py   (nx2/lift.py)
        ▼
 one C function per guest function, in chunks; game-specific patches (nx2/oot_patches.py)
        │  hot code split into pieces that compile in parallel (nx2/split_hot.py)
        │  clang: -O1, the hot functions -O2 with a profile (PGO); linked with host/ (nx2/build.py)
        ▼
 bin/hookshot(.exe) + hookshot_vk.dll/.so, image.bin, romfs, shader list, pipeline state list
        │  hookshot --prepare-shaders: shaders and pipelines built before the first start
        ▼
 game folder
```

The inputs it expects are fixed: program `0400486024DEC000` at update v131072. `main` is ZBIC-compressed (zstd with
its own framing, firmware 22.0.0 and later; decoder in `third_party/zbic`); the other modules are LZ4. The romfs is
read in place; its `.zs` files are zstd.

The lifted code runs in a **64-bit guest window** (`nx2/rtgen.py`): a guest address is an offset into one large host
reservation, so a guest pointer is used directly. The address map is in `host/hos.h`:

| Guest range | What |
|---|---|
| `0x01000000` to `0x07000000` | Host-made guest objects: main stack, TLS blocks, thread regions |
| `0x80000000` to image end | rtld, main, subsdk*, sdk, in Eden's layout (the addresses the lift uses) |
| `0x1000000000` up | The heap (`SetMemoryHeapSize`), from 64 GB |
| down to `0x8000000000` | Address regions (`AllocateAddressRegion`), from 512 GB down |

Memory is committed as it is handed out or first touched. Lifted loops carry interrupt polls at loop headers
(`nx2/poll.py`), which is where a guest thread can be asked to give up its virtual core.

## The host layer

The SDK is replaced at the `nn::` boundary. A function in `host/` defined as `HLE(<mangled name>)` replaces the SDK
function of that name, both where the game imports it and at the SDK's own definition. The rest of the SDK (libc,
`nn::util`, `nn::mem`, the NVN2 driver front end) runs as lifted code. An OS-facing import with no `HLE` definition
gets a generated stub that logs its first call and returns 0.

| Area | Files |
|---|---|
| Start-up, boot constants, the game thread | `hos_main.c` |
| Threads, sync, virtual cores | `hos_thread.c`, `nn_os_sync.c`, `hos_svc.c` |
| Memory | `hos_mem.c` |
| File system and saves | `nn_fs.c` |
| Window | `display.c` (Windows), `posix/display_sdl.c` (Linux, SDL) |
| Controllers, keyboard, mouse, motion | `nn_hid.c`, `pad_sdl.c`, `mouse_native.c`, `hos_motion.h` |
| Audio output | `nn_audio.c`: the audio renderer's graph, mixed on the host |
| Microphone | `nn_audio_in.c`: input streams fed from SDL (SDL3, or SDL2 in the AppImage); silence without a device |
| Video | `nn_video.c`: nn::codec's decoders on FFmpeg. AV1 movies use dav1d through FFmpeg when the build has it; on Windows without it, Media Foundation (`mf_av1.c`) |
| NVN2 | `nvn_native.c`, `nvn_layout.c` |
| The control bridge | `control.c` (see [automation](automation.md)) |
| Game-specific hooks | `oot_menu.c`, `oot_heap_retry.c`, `oot_text_size.c`, `mods.c` |

**Pointer input.** The window thread publishes one pointer sample (client position and size in physical pixels,
buttons, pending presses, wheel) through `host/display_pointer.h`, and the renderer reads it without calling the
window system. The Insert menu works in swapchain coordinates. On Windows, the game's own menus read a separate
mailbox.

**Sticks.** An SDL stick axis steers only once it has been seen at rest, so a trigger or an unused axis mapped onto a
stick cannot hold the camera (`pad_sdl.c`). Camera inversion is applied after that check.

## Graphics: recording and replay

The game calls NVN2. `host/nvn_native.c` implements the NVN2 procs over guest memory:

- **Objects with semantics** (device, memory pools, buffers, textures, samplers, descriptor pools, queues, the
  window, syncs, events, command buffer memory) are implemented as NVN defines them, in place in the memory the game
  gives them.
- **State changes and GPU work** (binds, draws, dispatches, clears, copies) are recorded as commands into an op stream
  in host memory, in the format of `gpu/render/rx_nvn.h`.
- **A queue submit** hands the recording to the back end (`rx_nvn_submit`), which replays it.

`gpu/vk/vk_replay.cpp` replays the stream on Vulkan 1.3:

| Concern | How |
|---|---|
| Guest memory | Each NVN memory pool is imported as host memory (`VK_EXT_external_memory_host`) with one buffer over it (`vk_memory.cpp`). A GPU address maps to a buffer and offset. Pools are imported on first GPU use |
| Fences | NVN fences map to timeline semaphore values; submissions are numbered per queue |
| Render targets and textures | Images keyed by storage address (`vk_texture.cpp`) |
| Draws and pipelines | Dynamic rendering, extended dynamic state, push descriptors (`vk_draw.cpp`) |
| Shaders | Translated to SPIR-V on demand and cached ([Shaders](#shaders)) |
| Mesh and task programs | `VK_EXT_mesh_shader` where the GPU has it; otherwise a fallback with a generated vertex stage |
| Matrix (HMMA) instructions | Cooperative matrices (`vk_coopmat.cpp`) |

**GPU timestamps.** The game's dynamic-resolution controller reads GPU timestamp reports. The replay writes fake
ones (`NOP_REPORT_COUNTER`): the 31.25 MHz tick count since the frame's present, scaled by `RX_VK_TS_SCALE` (0.1 by
default), so the controller settles at a size the PC can hold rather than at its floor.

**Device loss is terminal.** `device_lost()` writes the checkpoint report once, and `replay_fatal()` flushes the host
log and exits with code 3. Every replay and presentation call site checks for it before dependent work; there is no
recovery path.

## Shaders

The game's programs are Ampere (SM86) machine code in NVN2 packages. `gpu/vk/vk_shader.cpp` translates each
program variant:

1. The control section (in guest memory) and the code area (in GPU memory) are read.
2. The Ampere instructions are lowered to Maxwell
   (`gpu/vk/eden/shader_recompiler/frontend/ampere/lower_to_maxwell.h`).
3. Eden's recompiler translates the Maxwell program to IR and then SPIR-V. Its questions (constant buffers, texture
   types) are answered from the NVN state: driver banks, the code area's constants, guest memory, the registered
   textures.

Translation and pipeline builds run on background workers (`vk_jobs.cpp`). A draw waits for its program's
translation. A draw whose pipeline is still building may be left out for a frame only when none of its stages writes
memory and its targets still hold the previous frame's picture; otherwise it waits (`RX_VK_PIPE_SKIP=0`: always
wait). Results persist across runs; see
[Pipeline and program caches](#pipeline-and-program-caches).

## Threads

| Thread | Created in | What it does |
|---|---|---|
| Main | `hos_main.c` | Opens the window and runs its event loop (`hos_display_loop`), which publishes pointer samples; on Linux it also pumps SDL's controller events |
| Renderer start | `display.c`, `posix/display_sdl.c` | Starts the Vulkan back end (`rx_start`); the game's first GPU work waits for it |
| Game | `hos_main.c` | Boots the guest (libc init, `nnMain`) |
| Guest threads | `hos_thread.c` | One host thread per `nn::os::CreateThread`, with a 64 MB host stack |
| Replay | the submitting guest thread | By default the replay runs synchronously on the thread that submits, pinned while it runs to a core kept free of the game's threads (`hos_reserved_cpus`). `RX_VK_ASYNC=1` moves it to a thread of its own |
| Replay workers | `vk_replay.cpp` | With `RX_VK_PARALLEL`, large command buffers are recorded in segments on several threads |
| Presenter | `vk_replay.cpp` | With `RX_VK_PRESENT_THREAD=1` (off by default) and a second queue that can present, each present is made on this thread and queue once the frame's copy into the window is done, so the game's thread carries on |
| Recorder | `vk_recorder.h` | With `RX_VK_RECORDER=thread`, the Vulkan calls of the replay are made by a recorder thread from a ring |
| Background workers | `vk_jobs.cpp` | Shader translation and pipeline builds: a third of the CPU threads, 2 to 4 |
| Capture helpers | `vk_memory.cpp` | Split large submit-time memory captures (`RX_VK_CAPTURE_THREADS`, 0 to 4) |
| Pool imports | `vk_memory.cpp` | Imports pools in the background ahead of their use |
| Texture conversion | `vk_texture.cpp` | Converts CPU-side texture uploads in parallel |
| Frame generation display | `vk_framegen.cpp` | Shows generated and game frames at their times, when frame generation is on |
| Audio mixer | `nn_audio.c` | Renders one audio frame (240 samples at 48 kHz) every 5 ms |
| Control bridge | `control.c` | Serves the local socket or named pipe |
| Pipeline cache save, PNG and frame-log writers | `vk_draw.cpp`, `vk_replay.cpp` | Short-lived or single-purpose writers off the replay path |

**Virtual cores.** Horizon runs at most one thread per core, and the game keeps per-core data without locks. So a
guest thread holds one of a fixed number of virtual cores while it runs guest code, and gives it up wherever Horizon
would switch threads: blocking waits, sleeps, yields, NVN waits, and exit. A better-priority waiter asks a holder to
give up its core at the holder's next checkpoint (every `nn::os` call and SVC). Guest code with no checkpoint keeps
its core; after a long wait (2 s by default) a waiter runs without one as a deadlock breaker, and the escape is
logged. `HOS_VCORES=0` turns virtual cores off.

**The CPU saturates first.** The game's threads, the replay, captures and pipeline compiles share the CPU, so extra
helper threads can lower the frame rate. Thread counts are measured before they are raised: `HOS_THREAD_TIMES`, the
`HOS_SAMPLE` profiler with `scripts/prof.py`, and the replay timeline (`RX_VK_TIMELINE`).

## GPU replay rules

These keep the replay correct for any NVN2 game. A change to `gpu/vk/` must keep all of them.

1. **Cross-queue event waits are honoured.** Games pass work between queues with `nvnCommandBufferWaitEvent`.
   `submit_job` in `vk_replay.cpp` replays each submission as far as its waits allow, with per-queue state, and
   holds the rest until the event is signalled. `RX_VK_EVENT_WAITS=0` turns this off, for A/B comparison only.
2. **Nothing the replay reads comes from live guest memory.** The game writes the next frame's data while the GPU
   is still on this one. Every read is from a submit-time capture (`memory_capture_submit`), and pools are captured
   from their creation, not from their first GPU use (`vk_memory.cpp`, `RX_VK_CAPTURE_POOL_MB`).
3. **Texture and sampler registrations are queued in order with the submits**, never applied out of band.
4. **Fake GPU timestamps keep dynamic resolution sensible** (see
   [Graphics](#graphics-recording-and-replay)). Check the render size the controller picks over time after
   touching timing.
5. **Clears after draws, and sample-after-write hazards, get passes of their own.** A clear that follows draws in a
   pass, a draw that samples a target its pass already wrote, and a draw that writes a target an earlier draw of the
   pass sampled, each start a new pass (`clear_after_draws`, `draw_hazards` in `vk_draw.cpp`). A draw that samples a
   target it writes itself stays in the pass.
6. **2D views of 3D textures need `VK_EXT_image_2d_view_of_3d`.**
7. **Game-specific hooks are gated on the game.** Hooks at fixed guest addresses inherited from Mario Kart World are
   gated on its build id (`hos_game_is_mkw`), and Ocarina of Time's hooks on its own. A hook never applies by
   address coincidence.

## Resource rules

Three rules recur across the back end's caches and resources.

**Mapped memory is not assumed coherent.** Host-visible memory may be non-coherent, so:

- CPU writes are flushed through VMA before the GPU uses them. Recording streams are flushed per recording slot at
  submit, covering every stream the submission used, worker slots included. Texture staging is flushed per slice
  after the conversion workers join (ASTC after gathering its layers), and staging slices start on a
  `nonCoherentAtomSize` boundary so a rounded flush never shares an atom with a slice a submitted segment is still
  reading. The Insert menu's texture uploader flushes its staging the same way.
- A GPU write the CPU reads takes three steps: a transfer-to-host-read barrier after the copy, a fence or timeline
  wait, then a VMA invalidate before the read. Screenshots, generated shots, frame-log slots and frame dumps all do
  this. Dumps invalidate before converting depth or RGB9E5 data, not after.

**A failed Vulkan creation is never cached.** Only successful handles enter a cache or are published.

- A failure is retried later, at most once per present (or texture frame) per key. Out-of-memory failures are
  transient; an unsupported configuration stays negatively cached.
- An object created but not committed to its cache is destroyed at once. A partially built resource set (a recording
  stream's buffer, allocation, mapping and ownership entry; frame generation's images) is committed whole or not at
  all.
- Error output handles are never returned or destroyed.
- An imported buffer is published only after `vkBindBufferMemory` succeeds.

**GPU lifetimes come from fences and the timeline, not frame counts.** A resource the GPU may still use is released
after a timeline value signalled after its last use has completed. Present count or CPU frame age is not GPU
completion. When no timeline value is available, the resource stays owned: a leak is preferred to an early destroy.

## Textures, buffers and recording streams

**Textures** (`vk_texture.cpp`) are one `VkImage` per texture storage, keyed by storage address and descriptor.
Images are uploaded on first use and again when page write generations show the storage written. An image the GPU
wrote is the content from then on. Formats of the same class share one image (`MUTABLE_FORMAT`). Block-linear
unswizzling is suyu's on the CPU; ASTC decodes on the GPU with Eden's decoder. Destruction is deferred.

**Image views and samplers.** A failed image view is not cached as null; it is retried on the next texture frame.
`bind_descriptors` rejects a descriptor array containing a failed sampler before pushing or allocating, and leaves
the pushed-state cache untouched; the draw fails and a later rebuild retries.

**Texel-buffer views** are keyed by the backing `VkBuffer`, format, offset and range, not by guest address, since a
guest address can be remapped. Every lookup stamps the import's use value. All imported-buffer destruction goes
through `destroy_import_buffer`, which releases the buffer's views first. Lock order: `pools_mu` before the view
mutex; release never takes `pools_mu`.

**Imports.** A failed DMA-buf import falls back to a host-pointer import before the range is held (`import_hold.h`).

**Recording streams** carry CPU-written shader banks, copied uniform buffers and generated indices for one
recording. A stream is committed by `stream_insert` only when complete. Growing a recording adds streams and keeps the
earlier ones, because already-recorded bindings point into them. A driver-bank cache generation commits only after
its upload succeeds. An extra descriptor pool is owned only after its first set allocation and its ownership entry
both succeed.

## Presentation

The texture, its active crop, the display aspect of that picture, and the swapchain size are separate inputs.
`gpu/vk/vk_present_rect.h` holds the geometry, independent of Vulkan:

- `present_source_rect` is the one source region that direct presentation, capture, scaling and interpolation
  sample. An empty region presents black.
- `PresentAspect` is the aspect of the picture after crop, not of the texture. An invalid value (zero, negative, NaN,
  infinite) falls back to the crop's pixel aspect.
- The fit rounds to the nearest pixel and centres the bars.

Normal and interpolated frames go through the same `present_image`. The Insert menu overlay stays in swapchain
coordinates.

**Swapchain replacement.** Passing `oldSwapchain` retires the old chain even when creation fails, so the old chain is
released after any attempt. A failed recreation skips that present and retries; the requested size is kept unless
the window has published a newer one. Reflex checks the swapchain generation after its latency sleep, so a replaced
chain gets no stale markers.

## Upscalers and frame generation

| Feature | Files |
|---|---|
| NVIDIA DLSS and DLAA | `vk_dlss.cpp` (built only with NVIDIA's SDK) |
| AMD FSR 3.1 upscaling | `vk_fsr3.cpp`, `vk_fsr3_inputs.cpp` |
| AMD FSR 3.1 frame generation | `vk_fsr3fi.cpp` |
| AMD FSR 4 | `vk_fsr4.cpp` (built only with AMD's runtime) |
| Hookshot's own frame interpolation | `vk_framegen.cpp` |
| The shared temporal chain | `vk_temporal.cpp`, `temporal_jitter.h` |
| Latency | `vk_reflex.cpp` (NVIDIA Reflex), `vk_antilag.cpp` (AMD Anti-Lag) |

The player's side is in [upscaling](../user/upscaling.md).

**Jitter.** The host asks the renderer for one `MkwVkJitter` sample per frame: width, height and sequence length of
one completed upscale, or zeros when no temporal upscaler is active. The host caches it for every view of that frame.
A sample expires after 30 renderer frames. The host never takes the upscaler's GPU or NGX lock.

**History.** DLSS and FSR 4 share the temporal chain; FSR 3.1 prepares its own inputs. When camera reprojection fails
or gives non-finite values, history is reset in the same frame.

**FSR resources.** FSR's constants are written to the recording's upload stream, not a per-frame ring. When the
output size changes, the old-size image bundle is retired on a global timeline value after its last use.

**Frame generation.** Any creation failure disables interpolation for the session and releases its resources;
ordinary presentation continues. The new size and multiplier take effect only after every image exists. The disabled
flag is atomic, because Reflex reads it from another thread.

## Pipeline and program caches

| File | What |
|---|---|
| `hookshot_programs.bin` | Translated programs (SPIR-V), so a program is translated once |
| `mkw_vk_pipelines.bin` | The driver's `VkPipelineCache` |
| `hookshot_pipelines.bin` | The pipelines this build was asked for, rebuilt before the game starts on the next run |
| `hookshot_pipeline_states.bin` | Pipeline states seen in play, valid for any build |
| `hookshot_pipeline_states_shipped.bin` | The list shipped with a release (`assets/pipeline_states/`, merged by `nx2/pipeline_states.py`), built by the first start's shader preparation |

`pipeline_cache_save` writes the driver cache on a background thread: to a temporary file that then replaces the old
one. An exception in that worker stays in the worker, clears its busy flag, and leaves later saves possible.

## Capture and frame logs

Screenshots, frame dumps (`vk_dump.cpp`) and the binary frame log read GPU output back to the CPU, following the
mapped-memory rule above.

- **Screenshots** use two readback buffers, chosen by present parity. Before a new copy reuses a slot whose capture
  is still pending, the pending pixels are copied to CPU memory.
- **PNG files** are written to an exclusively created temporary file in the same folder and renamed over the target
  only if every write and the close succeeded. A set of related PNGs (a flash triplet) is not atomic as a set.
- **The binary frame log** (`RX_VK_FRAMELOG`, read by `scripts/framelog.py`) is ready only when its image, three
  readback buffers, file and writer thread all exist. Its write queue is bounded. A failed write or flush disables
  logging for the rest of the run; the last record may be truncated, and the strict reader rejects it.

## Lineage and third-party code

Hookshot is a fork of mkw-recomp, the native port of Mario Kart World, which is also a Switch 2 game: ARMv8.2 code
with PAC and LSE atomics, DT_RELR relocations, NVN2, and SM86 shaders. From it come the lift driver and its fixes, the
host runtime, the NVN2 layer and the Vulkan back end; game-specific code lives in separate files where possible.

| Component | Origin | Where |
|---|---|---|
| AArch64 lifter, NSO loader, image builder, suyu's instruction translator | a64-kit | `third_party/a64-kit` |
| Shader recompiler (SM86 to IR to SPIR-V, task and mesh programs) | Eden | `gpu/vk/eden` |
| SPIR-V emitter | sirit, with Eden's mesh shader patch | `gpu/vk/sirit` |
| Texture decoders | suyu | `gpu/vk`, `gpu/third_party/suyu` |
| ZBIC decompression | kinnay/zbic | `third_party/zbic` |

Licences and exact provenance are in the `PROVENANCE.md` files (`host/`, `gpu/`, `third_party/*/`) and `third_party/a64-kit/NOTICE.TOTKPort.md`. The lifted code and every
build are derived from GPL code (suyu, GPL-2.0-or-later; Eden, GPL-3.0) and from the player's own game, so no game
files, lifted C or builds go into the repository or a release.
