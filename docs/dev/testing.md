# Testing

Hookshot has two kinds of checks: game-free ones, which CI runs on every pull request, and checks that need your dump
or a game run, which only you can run.

- [Running the game-free checks](#running-the-game-free-checks)
- [Writing a check](#writing-a-check)
- [Checks that need your dump](#checks-that-need-your-dump)
- [In-game checks](#in-game-checks)
- [What CI runs](#what-ci-runs)

## Running the game-free checks

One command runs them all, from the repository's root:

```sh
python -I -B tests/run_all.py
```

It runs, each in its own process:

- every `tests/test_*.py` and `nx2/test_*.py`;
- the C++ unit tests in `gpu/vk/tests`;
- a byte-compile of every tracked Python file.

It goes on after a failure, and ends with a table of every check, slowest first, and the whole output of each
failure. It exits with 1 when anything failed. A full run takes about a minute on a desktop CPU.

| Option | What it does |
|---|---|
| `<name> ...` | Run only the checks whose path contains one of the names: `run_all.py ub_ menu` |
| `--jobs <n>` | Checks at once. Default: one per CPU thread |
| `--timeout <s>` | Seconds before a check is stopped. Default 600 |
| `--strict` | A check whose tool is missing fails instead of being skipped |
| `--no-skip` | Also run the checks a test skips on this OS |
| `--shard K/N` | Run only the K-th of N parts |
| `--write-times` | After a full run, write this run's times to `tests/run_all_times.json` for this OS |

The slowest checks start first, by the times in `tests/run_all_times.json`. The same times split a run into parts of
about equal length for `--shard`; every check is in exactly one part, so stale times only make the parts uneven.

Some checks need a tool: a C++ compiler (`$CXX`, `clang++`, `g++` or `c++`), the SPIR-V validator (`spirv-val`),
glslang, `dotnet`, the SPIR-V or Vulkan headers (`HOOKSHOT_SPIRV_HEADERS`, `HOOKSHOT_VULKAN_HEADERS`, or the CPM cache
in `RX_CPM` or `build-linux/deps/cpm`), or a Python package such as `zstandard`. A check whose tool is missing is
skipped and says so; with `--strict` it fails. `pip install -r requirements.txt` covers the packages.

## Writing a check

Add a game-free check whenever the behaviour can be tested without the dump.

- **Name it `tests/test_<topic>.py`** (or `nx2/test_<topic>.py` for the lift pipeline). The runner finds it by its name:
  there is no list or workflow to edit.
- **Make it a script.** It runs as `python -I -B <file> [arguments]`, passes with exit code 0, and fails with any other,
  usually through `raise SystemExit("<what is wrong>")`. Start it with a docstring that says what it checks and how to
  run it.
- **Use the standard library.** CI installs no packages for the tests beyond the pipeline's own. Any compiler or other
  tool comes in through the runner, below.
- **Keep it fast and portable.** Every check shares one CI job with a 20-minute limit, and runs on Ubuntu and Windows.

Most checks read a source file and test a piece of it: they find a function by its text, cut it out, and compile it
with stubs or check what it contains. `tests/test_upscaler_rows.py` is a short example. This means **renaming or
reshaping a function can break a check far from your change.** Run the whole suite, and when a check fails because
the code moved, update the check in the same pull request rather than weakening it.

### Declaring what a check needs

A check that needs a tool, a package, or cannot run on an OS says so in its own file, as top-level assignments of
plain literals after its docstring and imports:

```python
RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]   # its command-line arguments
RUN_ALL_MODULES = ["zstandard"]                                       # Python packages it imports
RUN_ALL_SKIP = {"windows": "POSIX signals: checked on Linux"}         # OS -> why it is skipped there
```

| Placeholder | Filled with |
|---|---|
| `{cxx}` | A C++ compiler |
| `{vulkan_headers}`, `{spirv_headers}` | The headers' `include` folder |
| `{spirv_val}`, `{glslang}`, `{dotnet}` | The tool's path |

The runner reads these with `ast` and never imports the test. A check that declares nothing runs with no arguments. A
declaration that is not a plain literal of that shape, names an unknown placeholder or OS, or is changed anywhere but
its own top-level line stops the run with the file and line. A check skipped on both OSes (one that needs a GPU or the
game) names both. Naming a skipped check on the command line runs it anyway. The docstring of `tests/run_all.py` has
the full rules.

### Generated files

The SPIR-V headers in `gpu/vk/shaders/` (`*_spv.h`) and `gpu/vk/host_shaders/` are compiled from the shader beside
them. Regenerate them with glslang rather than editing them: `python -I -B scripts/host_shaders.py` for the host
shaders. For the others, the check that compares a header with its source has the command; `tests/test_dlss_actor.py` is one.

## Checks that need your dump

These read `work/dump.txt` (from `nx2/dump.py --set`) and are slow. They are skipped by the runner on both OSes.

| Command | What it checks |
|---|---|
| `python -I nx2/test_insn.py [--per 6 --states 12] [--only <set>]` | Every instruction form the game uses: Unicorn's ARMv8 "max" CPU against the lifted C, comparing registers, flags and memory |
| `python -I nx2/test_leaf.py [--count 3000 --states 4] [--calls]` | Random whole functions, or with `--calls` call trees, on the real relocated image: native code against Unicorn |
| `python -I nx2/test_dll.py [--count 2000] [--calls]` | The same against the library build, after `nx2/lift.py --write` and `nx2/build.py --dll` |
| `python -I nx2/census.py --nx2` | The instruction census per module, after the Switch 2 forms |
| `python -I nx2/lower_test.py work/lowfail` | Shader programs that failed to lower |

## In-game checks

A change to the renderer or the runtime needs a run in the game. [Running](running.md) has the tools:

- `scripts/run-vk.ps1` on Windows, or a standalone build started with `HOS_HEADLESS=1` and `RX_VK_SHOTS`, for timed
  screenshots;
- the flash detector, `RX_VK_FLASH=1` with `RX_VK_SHOTS` and `RX_VK_SHOT_EVERY=1`, which writes the frames around a
  one-frame flash;
- the frame dumps and frame logs in [switches](switches.md), read by `scripts/framelog.py` and `scripts/probe.py`;
- the sampled profiler and its scripts, for performance.

In the pull request, say what you saw before and after, on which GPU and driver, and where in the game. Add a row to
[tested configurations](../tested-configurations.md) for a run worth recording. Screenshots of the game are fine to
post; the screenshot folders themselves are game-derived and gigabytes in size, so delete them and never commit them.

## What CI runs

No workflow has the game. Every workflow is in `.github/workflows/`.

| Workflow | When | What |
|---|---|---|
| Game-free source regressions (`source-regressions.yml`) | Every pull request to `main`, every push to `main` | `tests/run_all.py --strict` on Ubuntu 24.04 and Windows Server 2022, each in two parts (`--shard 1/2`, `--shard 2/2`). Windows' first part also builds a C++ test with MSVC and compiles the Windows builder |
| PR title (`pr-title.yml`) | Every pull request, again when its title is edited | The title is a Conventional Commit (see [CONTRIBUTING.md](../../CONTRIBUTING.md#pull-request-titles)) |
| Linux AppImage (`linux-appimage.yml`) | Pull requests that change more than docs, pushes to `main`, tags | Builds the AppImage and starts a player's build from it without a game (`scripts/linux/check_player_build.sh`) |
| Windows builder (`windows-builder.yml`) | The same | Builds the builder, its setup and the Vulkan back end with llvm-mingw |
| Vulkan back end with NVIDIA DLSS (`vulkan-dlss.yml`) | By hand, or when a file the DLSS build reads changes | Checks only that `hookshot_vk.dll` links with NVIDIA's SDK and AMD FSR 4. Accepts NVIDIA's license for that run alone and uploads nothing |

The AppImage job's package setup retries its two phases, the base indexes and the toolchain repository, separately,
at most three times each, and bounds each repository enrollment to 180 seconds. `tests/test_appimage_package_retry.py`
runs that shell with stand-ins.
