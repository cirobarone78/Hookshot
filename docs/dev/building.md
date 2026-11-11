# Building from source

Hookshot Builder, on Windows and Linux, runs one script: `nx2/make_game.py`. This page sets up a clone so you can run
that script yourself, run its stages one at a time while you work on the code, and build the optional parts.

- [What you need](#what-you-need)
- [Setting up Windows](#setting-up-windows)
- [Setting up Linux](#setting-up-linux)
- [Building a game folder](#building-a-game-folder)
- [Building in stages](#building-in-stages)
- [Rebuilding only the renderer](#rebuilding-only-the-renderer)
- [The Windows game, built on Linux](#the-windows-game-built-on-linux)
- [NVIDIA DLSS](#nvidia-dlss)
- [AMD FSR 4](#amd-fsr-4)
- [The AppImage](#the-appimage)
- [Hookshot Builder for Windows](#hookshot-builder-for-windows)
- [The pipeline state list](#the-pipeline-state-list)
- [Compilers and memory](#compilers-and-memory)
- [Build environment variables](#build-environment-variables)

## What you need

**Your own copy of the game, at the supported version:** program `0400486024DEC000`, update v131072, build
`e0f3ccfa`. Other versions are refused. The build reads the dump where it lies and never changes it. Nothing made from
it is ever committed: see [CONTRIBUTING.md](../../CONTRIBUTING.md).

**Room:** a build reads and writes tens of gigabytes. Keep about 45 GB free for a development checkout, and expect a
game run to use about 10 GB of RAM. An SSD is much faster: on a hard drive `make_game.py` warns and builds anyway.

**Python 3 and the pipeline's packages.** Run every script with `python -I` from the repository's root.

```sh
git clone https://github.com/NotRexed/Hookshot.git
cd Hookshot
python -m pip install -r requirements.txt
```

`requirements.txt` pins the pipeline's packages (lz4, numpy, capstone, unicorn, zstandard) and includes
`nx2/prompt_requirements.txt`, the packages that draw the button prompts.

## Setting up Windows

1. Install Python 3 from [python.org](https://www.python.org/downloads/). The Microsoft Store build installs packages
   where `python -I` does not look.
2. Get [llvm-mingw](https://github.com/mstorsjo/llvm-mingw), the `ucrt-x86_64` build, and set `HOOKSHOT_MINGW` to its
   folder. `make_game.py` also finds it unpacked as `llvm-mingw` in the clone, but `nx2/build.py` run on its own needs
   the variable. This fetches the release the project pins, checks its SHA-256 and prints the folder it unpacked:

   ```powershell
   python -I scripts/release_parts.py llvm-mingw C:\path\llvm
   ```

3. Install Hookshot Builder from the [latest release](https://github.com/NotRexed/Hookshot/releases/latest) once, and
   take what a clone does not carry from its tools folder,
   `%LOCALAPPDATA%\HookshotBuilder\versions\<version>\HookshotBuilder\tools`:

   | From `tools` | Use | Without it |
   |---|---|---|
   | `cpm` | Set `RX_CPM` to it: the Vulkan, SPIR-V and VMA headers, and FFmpeg | The build stops unless the headers come from elsewhere (see [Headers](#headers)) |
   | `wgpu-native` | Set `WGPU_NATIVE` to it | The game is built without the WebGPU fallback renderer |
   | `third_party` | Copy its files into the same places under `third_party\` | `SDL2.dll` and `SDL3.dll` are missing beside the game. `a64emit` and `zbic` are built on first use |

4. Fetch the play profile into `work\`: the hot-function list, the link order, the profile-guided optimisation data
   and the icon. They hold addresses and counts, no game code. Without them the game builds and runs a little slower.

   ```powershell
   python -I scripts/release_parts.py previous setup.txt --repo NotRexed/Hookshot
   python -I scripts/release_parts.py profile setup.txt work
   ```

Without llvm-mingw the build uses emsdk's clang (`EMSDK`, default `C:\emsdk`) with Visual Studio's C++ tools and the
Windows SDK. `HOOKSHOT_MSVC=1` picks that route even when llvm-mingw is there.

## Setting up Linux

`scripts/linux/deps.sh` fetches and builds everything the AppImage carries into `build-linux/deps`: LLVM's clang and
lld, a Python 3.12 with the packages, FFmpeg with dav1d, SDL2, and the Vulkan, SPIR-V and VMA headers. Each part is
built once and kept until its pinned version changes. Point the build at it:

```sh
scripts/linux/deps.sh
export EMSDK=$PWD/build-linux/deps/emsdk RX_CPM=$PWD/build-linux/deps/cpm
```

Or use your distribution's packages:

- `clang` and `lld`. LLVM 23 or newer reads the play profile; an older one builds without it.
- The C library headers (`libc6-dev` on Debian and Ubuntu, `glibc-devel` on Fedora).
- FFmpeg's development files, found through `pkg-config`, with dav1d for the game's AV1 movies.
- SDL3 or SDL2 at run time. The game loads SDL3 when it finds it, else SDL2 (`HOS_SDL_VERSION=2` skips SDL3).
- Vulkan, SPIR-V and VMA headers (see [Headers](#headers)).

The play profile comes the same way as on Windows:
`python -I scripts/release_parts.py previous setup.txt --repo NotRexed/Hookshot`, then
`python -I scripts/release_parts.py profile setup.txt work`.

### Headers

`nx2/build.py` looks for the Vulkan, SPIR-V and VMA headers in this order, and stops when one is missing rather than
build a game without a renderer:

1. a CPM cache: `RX_CPM`, else `cpm` in the clone;
2. `HOOKSHOT_VULKAN_HEADERS`, `HOOKSHOT_SPIRV_HEADERS`, `HOOKSHOT_VMA_HEADERS` (a package root or its `include`
   folder);
3. `/usr/local` and `/usr`.

## Building a game folder

```sh
python -I nx2/make_game.py --nup /path/to/game.nup --out ~/Games/Hookshot --language en-US
python -I nx2/make_game.py --romfs /path/to/romfs --exefs /path/to/exefs --out ~/Games/Hookshot
python -I nx2/make_game.py --check --nup /path/to/game.nup
```

The first build takes about 40 minutes. An update of the same folder translates again and compiles only what changed.

| Option | What it does |
|---|---|
| `--nup <file>` | Your game as a `.nup` package |
| `--romfs <dir>` `--exefs <dir>` | Your game as extracted folders |
| `--game <file or dir>` | Either of the above: a `.nup`, or a folder holding `romfs` and `exefs` |
| `--out <dir>` | The game folder to make |
| `--check` | Check the game and its version, then stop. Builds nothing |
| `--update <dir>` | Build a folder made before again, from the game files it keeps. Keeps its language and its FSR 4 choice |
| `--language <code>` | The game's language, written to `language.txt`. Default `en-US` |
| `--work <dir>` | The build files folder. Default `~/.cache/hookshot-builder` on Linux, `%LOCALAPPDATA%\HookshotBuilder` on Windows |
| `--jobs <n>` | Compilers at once. `0` or unset: automatic (see [Compilers and memory](#compilers-and-memory)) |
| `--log <file>` | Also write the output to a UTF-8 file, replaced if it exists |
| `--no-prepare-shaders` | Leave the shader preparation to the game's first start |
| `--fsr`, `--no-fsr` | Build with AMD FSR 4; with `--update`, build without it |
| `--fetch-fsr-runtime`, `--accept-amd-license` | Download AMD's FSR runtime into the game folder (Windows) |
| `--fetch-ngx-sdk`, `--accept-nvidia-license` | Download NVIDIA's DLSS SDK into `HOOKSHOT_NGX_SDK` before the build |
| `--prepare` | For launchers: no window, progress lines on stdout, `--out` defaults to `~/Games/Hookshot` |

A folder built from a source checkout has the game itself at its top (`hookshot.exe` or `hookshot`), with no launcher.
The packaged builders put the game in `bin/` and a launcher in its place.

After a build, `make_game.py` deletes the build files in the work folder except this build's compiled objects, so the
next build compiles only what changed. `HOOKSHOT_KEEP_BUILD_FILES=1` keeps everything. A work folder that is the clone's
own `work/` is always kept.

## Building in stages

While you work on the lifter, the runtime or the renderer, run the stages yourself. They read and write the clone's
`work/` (or `OOT_WORK`).

| Step | Command | Output |
|---|---|---|
| 1. Unpack a `.nup` | `python -I nx2/nup.py <file.nup> --extract work/dump` | `work/dump/exefs` and `work/dump/romfs` (the newest title) |
| 2. Record the dump | `python -I nx2/dump.py --dump work/dump --set` | What the dump is; its folder in `work/dump.txt` |
| 3. Lift | `python -I nx2/lift.py --standalone --write` | The C in `work/sa/gen`, the image in `work/sa/image/image.bin` |
| 4. Compile | `python -I nx2/build.py --standalone --jobs 8` | `work/sa/build/hookshot.exe` and `hookshot_vk.dll` (`hookshot` and `hookshot_vk.so` on Linux) |

`make_game.py` runs steps 3 and 4 with `RX_RELEASE=1` and the play profile. Step 4 recompiles only the files whose source
or flags changed. `nx2/nup.py <file.nup> --verify` checks a package's hashes without extracting it.

The dump can also come from the environment: `OOT_DUMP` (the folder holding `exefs` and `romfs`), or `OOT_EXEFS` and
`OOT_ROMFS` separately. These win over `work/dump.txt`.

Without `--standalone`, `lift.py --write` and `build.py --dll` make the library build in `work/gen` and `work/build`,
which only the dump-backed checks use (see [testing](testing.md#checks-that-need-your-dump)). [Running](running.md)
starts a standalone build.

## Rebuilding only the renderer

The Vulkan back end needs no game. With `RX_VK_ONLY=1`, `build.py` compiles it alone, with no lift:

```sh
RX_VK_ONLY=1 python -I nx2/build.py --standalone --jobs 8
```

```powershell
$env:RX_VK_ONLY = "1"; python -I nx2/build.py --standalone --jobs 8
```

Copy `work/sa/build/hookshot_vk.dll` (or `hookshot_vk.so`) beside the game executable to try it. The executable and the
renderer must agree on `MKWVK_API_VERSION` (`gpu/vk/vk_api.h`): on a mismatch the game logs it and does not use the
renderer.

## The Windows game, built on Linux

Unpack llvm-mingw's Linux release (`ucrt-ubuntu-22.04-x86_64`) and build with `RX_TARGET=windows` and `HOOKSHOT_MINGW`
set to it:

```sh
RX_TARGET=windows HOOKSHOT_MINGW=~/llvm-mingw python -I nx2/make_game.py --nup game.nup --out ~/Games/Hookshot-win
```

Its objects go to `~/.cache/hookshot-builder-windows`, apart from the Linux game's. The folder runs on Windows or under
Proton.

## NVIDIA DLSS

DLSS (`gpu/vk/vk_dlss.cpp`) is built in only with NVIDIA's DLSS SDK. The SDK is NVIDIA's, under NVIDIA's license, and is
never committed, bundled or uploaded: not in a pull request, a release or a CI artifact. Never share a game folder
built with it.

1. Fetch the SDK. The script prints NVIDIA's license and asks you to accept it, or takes `--accept-nvidia-license`;
   each file is checked against its SHA-256.

   ```sh
   python -I scripts/ngx_sdk.py --platform windows C:\path\ngx-sdk   # headers, nvsdk_ngx_s.lib, nvngx_dlss.dll
   scripts/linux/ngx-sdk.sh ~/ngx-sdk                                # Linux: libnvsdk_ngx.a, libnvidia-ngx-dlss.so.<version>
   ```

2. Build with `HOOKSHOT_NGX_SDK` set to that folder. `make_game.py` puts DLSS's runtime in the game folder's `ngx`
   folder.

`make_game.py --fetch-ngx-sdk --accept-nvidia-license` does both in one run, into `HOOKSHOT_NGX_SDK`.

On Windows the llvm-mingw build links NVIDIA's static `nvsdk_ngx_s.lib`, which is built for Microsoft's static runtime;
`gpu/vk/vk_ngx_msvc_rt.cpp` and `host/mingw_msvc_shims.c` provide what it needs of that runtime. Never put NGX's core,
`_nvngx.dll`, beside the game: it comes with the driver. A Windows game with DLSS also builds on Linux with
`RX_TARGET=windows`.

A change to the pinned SDK release updates the file table and SHA-256s in `scripts/ngx_sdk.py` and
`tests/test_ngx_sdk.py`, and the release named in the builder's license text
(`builder/HookshotBuilder/MainWindow.xaml.cs`).

How players turn DLSS on, and where the game looks for the runtime, is in [upscaling](../user/upscaling.md).

## AMD FSR 4

FSR 4 is built in with `make_game.py --fsr`, or `HOOKSHOT_FSR=1` for `nx2/build.py`. The build uses only AMD's
MIT-licensed API headers in `third_party/fidelityfx`. At run time the game needs AMD's runtime, which Hookshot does not
include:

- **Windows:** `amd_fidelityfx_loader_vk.dll` and `amd_fidelityfx_upscaler_vk.dll` from the FidelityFX SDK 2.4
  release, beside the game's executable or in the game folder. `--fetch-fsr-runtime --accept-amd-license` downloads
  them at the pinned tag, checks their SHA-256 and copies them in, with AMD's license as `LICENSE-AMD-FSR-SDK.md`.
  `HOOKSHOT_FFX_SDK` keeps the download between builds (default `work/ffx-sdk`). For a folder built already:
  `python -I scripts/ffx_sdk.py --accept-amd-license --game <game folder>`. DLLs of another version already in the
  folder are left alone.
- **Linux:** a Vulkan FSR 4 library, `amd_fidelityfx_upscaler_vk.so`, in the game folder. `--fetch-fsr-runtime` does
  nothing on Linux. The AppImage's prebuilt renderer has no FSR 4, so `--fsr` needs a build from source.

`RX_VK_FSR_DIR` names another folder for the runtime, for testing.

## The AppImage

```sh
scripts/linux/deps.sh                    # once: the toolchain and libraries, into build-linux/deps
scripts/linux/appimage.sh                # build-linux/Hookshot-<version>-x86_64.AppImage and its .zsync
scripts/linux/check_player_build.sh      # a player's build started from the image, without a game
```

`appimage.sh` builds the Vulkan back end once (`RX_VK_ONLY=1`, for `x86-64-v3`), so the image carries it prebuilt; the
player's PC compiles only the game. It carries `work/`'s play profile when the clone has one, and stops when
`assets/pipeline_states/` holds no list. CI builds it on Ubuntu 22.04: the sysroot it carries is that system's C
library, so the game it builds runs on glibc 2.35 and newer. It needs a CPU with AVX2 and a Vulkan 1.3 driver with
mesh shaders.

The system libraries copied into the sysroot are copied by value: an absolute symlink on the build machine becomes a
real file. The updater rebases absolute links only in sysroot parts from older releases, when their targets resolve
inside the sysroot; any other absolute link is an error.

The image's own options:

| Command | What it does |
|---|---|
| `Hookshot-<version>-x86_64.AppImage` | The builder window |
| `... --cli <make_game.py options>` | `make_game.py` itself, with the image's toolchain |
| `... --play [<folder>]` | Start the game the builder built last, or the one in that folder |
| `... --launch <folder>` | That folder's launcher: Play, and Update when a newer release is out |
| `... --update <folder>` | Download the new release (only the parts that changed) and build that folder again |

The game folder's `hookshot` script starts the builder named by `builder=` in its `hookshot_version.txt`, the one that
last built it. When that builder is gone, it falls back to the installed one under
`$HOOKSHOT_BUILDER_HOME/hookshot/builder`, or `$XDG_DATA_HOME/hookshot/builder` (default `~/.local/share`), and with
neither, starts `bin/hookshot`. Versions are ordered by `release_key` in `builder/linux/linux_update.py`: release
candidates before their release, git-describe builds after their tag. Installing an older version always asks first.

## Hookshot Builder for Windows

The Windows builder is a .NET 8 WPF app (`net8.0-windows`). Open `builder/HookshotBuilder.sln` in Visual Studio 2022
with the .NET desktop workload, or build it from a developer prompt:

```powershell
dotnet build builder/HookshotBuilder.sln
```

You need Visual Studio only for the builder. The game builds with llvm-mingw. The builder sets `EMSDK`, `RX_CPM` and
`WGPU_NATIVE` to the folders in its own tools folder before it runs `make_game.py`.

Before a new build, the builder stops processes left over from an interrupted one, but only those it can prove belong
to the selected work folder: a `make_game.py` or `lift.py` with that `--work`, a `build.py` started by such a
`make_game.py`, or a compiler or linker writing into the folder. Anything else is left running. Linux does no such
cleanup.

The builder can also run portable, keeping everything in one folder: see [portable builder](portable-builder.md).

## The pipeline state list

Every release ships a list of Vulkan pipelines that the first start's shader preparation builds before the title.
Without it, a new install compiles them in play, and draws left out meanwhile wash the first field load white for
seconds.

The list is merged from sources in `assets/pipeline_states/`:

| Source | Written by |
|---|---|
| `tour.bin.xz`, `tour.md` | The maintainers' pipeline tour, through `nx2/pipeline_states.py tour`. Replaced whole each time |
| `contrib/<name>.bin.xz`, `contrib/<name>.md` | One contributor each, through `nx2/pipeline_states.py add` |

Each record holds a pipeline's shader hashes, its program variant's hash, and the target formats, vertex formats and
draw state it was made with. It holds no game code: a player's build turns the hashes back into shaders from their own
`hookshot_shaders.bin`. `nx2/pipeline_states.py` documents the layout.

`make_game.py` merges the sources at every build into the game folder's `hookshot_pipeline_states_shipped.bin`: the
tour's list first, then the contributed ones by name, each pipeline once. The same sources always give the same bytes.
The sources are xz-compressed with fixed settings, so the repository stays small; xz because the AppImage's Python 3.12
has `lzma` but not `compression.zstd`.

The release packages refuse to ship without them: `scripts/linux/appimage.sh` stops, `scripts/linux/check_player_build.sh`
reads them with the image's Python, and `scripts/release_parts.py package` stops when there are none or one does not
read.

```sh
python -I nx2/pipeline_states.py add <name> <game folder>/hookshot_pipeline_states.bin --who ... --gpu ... --build ... --settings ... --route ...
python -I nx2/pipeline_states.py tour <lists>... --gpu ... --build ... --settings ... --route ...
python -I nx2/pipeline_states.py check
python -I nx2/pipeline_states.py merge --out merged.bin
```

A game run writes `hookshot_pipeline_states.bin` beside the executable, adding each pipeline it makes in play. `add`
keeps only the pipelines no other contributed list holds. [`assets/pipeline_states/README.md`](../../assets/pipeline_states/README.md)
has the steps for contributing a list.

A list depends on the settings it was recorded with: one recorded at 1440p with DLSS shares few pipelines with one
recorded at 360p. Refresh the tour's list before each release, and after a change to the shader translation or to the
state a pipeline is made from. When the record format changes (`MAGIC` and `SIZE` in `nx2/pipeline_states.py`), old
lists no longer read and the release checks stop: convert each source or record it again.


Players send their lists with **Save my pipeline list** (the menu's Debug tab: `gpu/vk/pipeline_share.h`,
`share_pipeline_list` in `vk_menu.cpp`; the builders: `nx2/pipeline_share.py`, which the Linux builder imports and the
Windows one runs with `--json`). It checks the list as `pipeline_states.py --check` does, writes
`hookshot-pipelines-<date>.zip` to Downloads with exactly two files (the list and `hookshot_pipeline_report.txt`, the
issue template filled in), copies the template, shows the folder and opens the "Submit your pipelines" issue; with
`HOS_HEADLESS` it opens nothing. By hand: `python -I nx2/pipeline_share.py <game folder> [--out-dir <folder>]`.
`tests/test_pipeline_share.py` covers it.

## A faster build for development

The eight hot pieces of lifted code (`code_hot_*.c`, the functions the game spends its time in) are built at `-O2`
with the play profile. They're a small part of the lifted C but about a third of its compile time, and each is one of
the longest single compiles. When you're checking that something works (the game starts, a menu, a screenshot, a log)
and not how fast it runs, build them at `-O1` like every other lifted file:

```sh
RX_HOT_OPT=O1 python -I nx2/build.py --standalone --jobs 8
```

That saves about a quarter of the compile time. `build.py` run on its own uses no profile unless `RX_PGO` is set, and
lacks the rest of `make_game.py`'s environment (`RX_RELEASE`, `A64_HOT_CHUNK`), so its objects differ from a
`make_game.py` build's. Through `make_game.py`, `RX_HOT_OPT=O1` still uses the shipped profile and saves less.

Objects are cached by their flags, so `-O1` and `-O2` objects sit side by side: in the checkout's own `work/` (or with
`HOOKSHOT_KEEP_BUILD_FILES=1`), switching back and forth neither lifts again nor recompiles. In any other `--work`
folder, `make_game.py`'s clean-up keeps only the last build's objects, so each switch lifts again and recompiles the hot
pieces.

**Never use it for numbers:** no frame-rate or frame-time measurements, build timings, stutter checks or profiles, and
no release or player build.

## Compilers and memory

By default the build starts up to one compiler per CPU thread, each only when the free memory holds it. It counts a
running compiler together with its child processes, and keeps `HOOKSHOT_MEM_RESERVE_GB` (default 1.5) free. A floor
always runs: on Windows up to 4 compilers (half the threads on smaller CPUs), because Windows pages rather than fails;
on Linux one, because Linux stops a compiler that does not fit, and that file is compiled again alone at the end.

| Setting | Effect |
|---|---|
| `--jobs <n>` or `HOOKSHOT_JOBS=<n>` | At most that many compilers. `0`: automatic |
| `HOOKSHOT_MEM_LIMIT_GB=<n>` | The compilers may take that much together, whatever is free now. The floor still runs |
| `HOOKSHOT_MEM_RESERVE_GB=<n>` | Memory kept free for everything else. Default 1.5 |
| `HOOKSHOT_MEM_GATE=0` | No memory check: compilers start as `--jobs` allows |
| `HOOKSHOT_LIFT_JOBS=<n>` | Processes that write the lifted C. Default: the cores, at most 16, at most one per 2 GB of free memory |

The Windows builder's **Build workers** and **Build memory** choices set `HOOKSHOT_JOBS` and `HOOKSHOT_MEM_LIMIT_GB`
for the build they start.

## Build environment variables

| Variable | What it does |
|---|---|
| `HOOKSHOT_MINGW=<dir>` | The llvm-mingw to build the Windows game with |
| `HOOKSHOT_MSVC=1` | Windows: emsdk's clang with Visual Studio's tools, even when llvm-mingw is there |
| `EMSDK=<dir>` | Where clang and lld are found (`upstream/bin`). Default `C:\emsdk`, or `~/emsdk`; else `PATH` |
| `RX_CPM=<dir>` | The CPM package cache: Vulkan and SPIR-V headers, VMA, FFmpeg |
| `HOOKSHOT_VULKAN_HEADERS`, `HOOKSHOT_SPIRV_HEADERS`, `HOOKSHOT_VMA_HEADERS` | Header packages, when the CPM cache has none |
| `WGPU_NATIVE=<dir>` | wgpu-native, for the WebGPU fallback renderer (Windows) |
| `RX_TARGET=windows` | On Linux: build the Windows game |
| `RX_RELEASE=1` | A release build: no console window, the shaders prepared before the title. `make_game.py` sets it |
| `RX_PGO=gen` or `RX_PGO=<file>` | Build the hot code to count its branches, or with a profile. `make_game.py` passes the play profile |
| `RX_MARCH=<level>` | The CPU level: `x86-64-v3`, `x86-64-v2` or `x86-64`. Default: the best this CPU runs |
| `RX_VK_ONLY=1` | Build only the Vulkan back end, with no lift |
| `HOOKSHOT_KEEP_BUILD_FILES=1` | Keep the lifted C and every object after a `make_game.py` build |
| `HOOKSHOT_NGX_SDK=<dir>` | Build with NVIDIA's DLSS SDK from that folder |
| `HOOKSHOT_FSR=1` | `build.py`: the Vulkan back end with AMD FSR 4 (`make_game.py --fsr` sets it) |
| `HOOKSHOT_FFX_SDK=<dir>` | Where `--fetch-fsr-runtime` keeps AMD's runtime |
| `OOT_WORK=<dir>` | The work folder, instead of the clone's `work/` |
| `OOT_DUMP`, `OOT_EXEFS`, `OOT_ROMFS` | The dump's folders, over `work/dump.txt` |

The compiler and memory variables are in [Compilers and memory](#compilers-and-memory). The AppImage sets
`HOOKSHOT_SYSROOT`, `HOOKSHOT_FFMPEG`, `HOOKSHOT_SDL2` and `HOOKSHOT_VK_PREBUILT` for its own builds.

### The offline shader bake

An experimental, CPU-only shader bake lives in `nx2/bake*.py`, `nx2/bake_ds/` and `gpu/shaderbatch.cpp`. Nothing in
the build calls it. It needs `requirements.txt` installed (for `zstandard`) and a C++23 compiler: `BAKE_CXX` names one,
else the first of `clang++`, `g++` and `c++` on `PATH`. [BAKE.md](../../BAKE.md) has the details.
